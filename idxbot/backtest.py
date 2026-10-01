import math
import numpy as np
import pandas as pd
from . import idx_rules as idx
from . import risk
from .strategy import get_signal_fn


def run_backtest(data: dict, cfg: dict) -> dict:
    sig_fn = get_signal_fn(cfg)
    lot = cfg["idx"]["lot_size"]
    c = cfg["costs"]
    pf = cfg["portfolio"]
    # sinyal dihitung di close t, dipakai di open t+1
    want = {s: sig_fn(df).shift(1).fillna(0) for s, df in data.items()}
    dates = sorted(set().union(*[df.index for df in data.values()]))

    cash = float(pf["initial_cash"])
    pos = {}          # sym -> dict(shares, entry, stop)
    trades, curve = [], []
    last_close = {}

    def sell(sym, date, px, reason):
        nonlocal cash
        p = pos.pop(sym)
        gross = p["shares"] * px
        cash += gross * (1 - c["sell_fee"])
        cost_in = p["shares"] * p["entry"] * (1 + c["buy_fee"])
        pnl = gross * (1 - c["sell_fee"]) - cost_in
        trades.append(dict(symbol=sym, entry_date=p["date"], exit_date=date,
                           entry=p["entry"], exit=px, shares=p["shares"],
                           pnl=pnl, ret=pnl / cost_in, reason=reason))

    for d in dates:
        todays = {s: df.loc[d] for s, df in data.items() if d in df.index}
        # 1) stop loss (gap ke bawah -> keluar di open)
        for s in list(pos):
            if s in todays and pos[s]["stop"]:
                bar = todays[s]
                if bar["Low"] <= pos[s]["stop"]:
                    px = min(bar["Open"], pos[s]["stop"])
                    sell(s, d, idx.sell_price(px, c["slippage_bps"]), "stop")
        # 2) exit karena sinyal
        for s in list(pos):
            if s in todays and want[s].get(d, 0) == 0:
                sell(s, d, idx.sell_price(todays[s]["Open"], c["slippage_bps"]), "signal")
        # 3) entry baru
        equity = cash + sum(p["shares"] * last_close.get(s, p["entry"]) for s, p in pos.items())
        for s, bar in todays.items():
            if s in pos or want[s].get(d, 0) != 1:
                continue
            if len(pos) >= pf["max_positions"]:
                break
            px = idx.buy_price(bar["Open"], c["slippage_bps"])
            lots = risk.size_lots(equity, cash, px, cfg)
            if lots < 1:
                continue
            shares = lots * lot
            cash -= shares * px * (1 + c["buy_fee"])
            pos[s] = dict(shares=shares, entry=px, date=d,
                          stop=risk.stop_price(px, cfg))
        # 4) mark to market
        for s, bar in todays.items():
            last_close[s] = bar["Close"]
        eq = cash + sum(p["shares"] * last_close.get(s, p["entry"]) for s, p in pos.items())
        curve.append((d, eq, len(pos)))

    eq = pd.Series({d: e for d, e, _ in curve})
    expo = pd.Series({d: n for d, _, n in curve})
    return dict(equity=eq, trades=pd.DataFrame(trades),
                metrics=_metrics(eq, expo, pd.DataFrame(trades), pf))


def _metrics(eq: pd.Series, expo: pd.Series, tr: pd.DataFrame, pf: dict) -> dict:
    ret = eq.pct_change().dropna()
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    dd = (eq / eq.cummax() - 1).min()
    m = dict(
        start=str(eq.index[0].date()), end=str(eq.index[-1].date()),
        final_equity=float(eq.iloc[-1]),
        total_return=float(eq.iloc[-1] / pf["initial_cash"] - 1),
        cagr=float((eq.iloc[-1] / pf["initial_cash"]) ** (1 / years) - 1),
        max_drawdown=float(dd),
        sharpe=float(ret.mean() / ret.std() * math.sqrt(245)) if ret.std() > 0 else float("nan"),
        trades=int(len(tr)),
        win_rate=float((tr["pnl"] > 0).mean()) if len(tr) else float("nan"),
        avg_trade_ret=float(tr["ret"].mean()) if len(tr) else float("nan"),
        time_in_market=float((expo > 0).mean()),
    )
    return m


def buy_and_hold(data: dict, cfg: dict) -> pd.Series:
    """Benchmark kasar: equal-weight beli-tahan semua saham universe."""
    closes = pd.concat({s: df["Close"] for s, df in data.items()}, axis=1).ffill().dropna()
    norm = closes / closes.iloc[0]
    return norm.mean(axis=1) * cfg["portfolio"]["initial_cash"]
