"""Siklus harian (jalankan SETELAH market tutup):
1) isi order PENDING kemarin dengan harga open hari ini (paper),
2) cek stop loss, 3) hitung sinyal dari close hari ini -> order baru,
4) kirim ringkasan. Order asli di Stockbit tetap kamu pasang manual."""
import pandas as pd
from . import idx_rules as idx, risk, notify
from .paper import PaperBroker
from .strategy import get_signal_fn


def run_daily(cfg: dict, data: dict) -> str:
    c, pf, lot = cfg["costs"], cfg["portfolio"], cfg["idx"]["lot_size"]
    broker = PaperBroker(cfg["paper"]["db_path"], pf["initial_cash"])
    sig_fn = get_signal_fn(cfg)
    last_date = max(df.index[-1] for df in data.values())
    lines = []

    if (pd.Timestamp.today().normalize() - last_date).days > 4:
        lines.append(f"!! Data terakhir {last_date.date()} -- kemungkinan basi, cek sumber data.")

    # 1) fill order pending (bar pertama setelah signal_date)
    for o in broker.pending():
        df = data.get(o["symbol"])
        if df is None:
            continue
        nxt = df[df.index > pd.Timestamp(o["signal_date"])]
        if nxt.empty:
            continue
        d, bar = nxt.index[0], nxt.iloc[0]
        if o["side"] == "BUY":
            px = idx.buy_price(bar["Open"], c["slippage_bps"])
            if px > o["limit_price"]:
                broker.cancel(o["id"], f"open {px:.0f} > limit {o['limit_price']:.0f}")
                lines.append(f"BATAL beli {o['symbol']} (open di atas limit)")
                continue
            if o["symbol"] in broker.positions():
                broker.cancel(o["id"], "sudah punya posisi")
                continue
            broker.fill_buy(o, px, d.date(), lot, c["buy_fee"], risk.stop_price(px, cfg))
            lines.append(f"FILL beli {o['symbol']} {o['lots']} lot @ {px:.0f}")
        else:
            if o["symbol"] not in broker.positions():
                broker.cancel(o["id"], "posisi tidak ada")
                continue
            px = idx.sell_price(bar["Open"], c["slippage_bps"])
            broker.fill_sell(o["symbol"], px, d.date(), c["sell_fee"], o["id"])
            lines.append(f"FILL jual {o['symbol']} @ {px:.0f}")

    # 2) stop loss pada bar yang belum dicek
    for s, p in broker.positions().items():
        df = data.get(s)
        if df is None or not p["stop"]:
            continue
        for d, bar in df[df.index > pd.Timestamp(p["last_checked"])].iterrows():
            if bar["Low"] <= p["stop"]:
                px = idx.sell_price(min(bar["Open"], p["stop"]), c["slippage_bps"])
                broker.fill_sell(s, px, d.date(), c["sell_fee"], reason="stop")
                lines.append(f"STOP {s} @ {px:.0f}")
                break
        else:
            broker.set_checked(s, last_date.date())

    # 3) sinyal baru dari close terakhir
    prices = {s: df["Close"].iloc[-1] for s, df in data.items()}
    equity = broker.equity(prices)
    held, pend = broker.positions(), broker.pending()
    pend_syms = {o["symbol"] for o in pend}
    slots = pf["max_positions"] - len(held) - sum(o["side"] == "BUY" for o in pend)
    new = []
    for s, df in data.items():
        want = int(sig_fn(df).iloc[-1])
        if s in pend_syms:
            continue
        if s in held and want == 0:
            new.append((s, "SELL", held[s]["shares"] // lot, prices[s], None, "sinyal keluar"))
        elif s not in held and want == 1 and slots > 0:
            ref = prices[s]
            limit = idx.round_to_tick(ref * 1.02, "down")
            lots = risk.size_lots(equity, broker.cash, idx.buy_price(ref, c["slippage_bps"]), cfg)
            if lots >= 1:
                new.append((s, "BUY", lots, ref, limit, "sinyal masuk"))
                slots -= 1
    for s, side, lots, ref, limit, why in new[: pf["max_daily_orders"]]:
        broker.place(last_date.date(), s, side, lots, ref, limit, why)

    # 4) ringkasan
    lines.append(f"\n== Rencana order untuk sesi berikutnya (data {last_date.date()}) ==")
    plan = broker.pending()
    if not plan:
        lines.append("(tidak ada order)")
    for o in plan:
        if o["side"] == "BUY":
            st = risk.stop_price(o["limit_price"], cfg)
            lines.append(f"BUY  {o['symbol']} {o['lots']} lot, limit <= {o['limit_price']:.0f}"
                         f"  (stop ~{st:.0f})  [{o['reason']}]" if st else
                         f"BUY  {o['symbol']} {o['lots']} lot, limit <= {o['limit_price']:.0f}")
        else:
            lines.append(f"SELL {o['symbol']} {o['lots']} lot (market/limit dekat close {o['ref_price']:.0f})")
    lines.append(f"\nEquity paper: Rp{equity:,.0f} | cash Rp{broker.cash:,.0f} | posisi {len(broker.positions())}")
    msg = "\n".join(lines)
    notify.send(msg, cfg)
    return msg


def show_portfolio(cfg: dict, data: dict):
    broker = PaperBroker(cfg["paper"]["db_path"], cfg["portfolio"]["initial_cash"])
    prices = {s: df["Close"].iloc[-1] for s, df in data.items()}
    print(f"Cash: Rp{broker.cash:,.0f} | Equity: Rp{broker.equity(prices):,.0f}")
    for s, p in broker.positions().items():
        px = prices.get(s, p["entry"])
        print(f"  {s}: {p['shares']} lbr, entry {p['entry']:.0f}, last {px:.0f}, "
              f"PnL {px / p['entry'] - 1:+.1%}, stop {p['stop']}")
    for o in broker.pending():
        print(f"  PENDING {o['side']} {o['symbol']} {o['lots']} lot")
