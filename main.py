import argparse
from pathlib import Path
import pandas as pd
from idxbot.config import load_config
from idxbot.data import load_universe
from idxbot import backtest, runner, monitor


def fmt(m):
    pct = {"total_return", "cagr", "max_drawdown", "win_rate", "avg_trade_ret", "time_in_market"}
    for k, v in m.items():
        if k in pct:
            v = f"{v:.1%}"
        elif isinstance(v, float):
            v = f"{v:,.2f}"
        print(f"  {k:<15} {v}")


def main():
    ap = argparse.ArgumentParser(description="IDX bot prototype (semi-otomatis, paper)")
    ap.add_argument("cmd", choices=["backtest", "daily", "portfolio", "reset",
                                     "monitor", "screener", "tv"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--provider", help="override: yfinance|csv|synthetic (monitor: yahoo|synthetic)")
    ap.add_argument("--once", action="store_true", help="monitor: satu siklus lalu keluar")
    ap.add_argument("--force-open", action="store_true", help="monitor: abaikan jam bursa (tes)")
    ap.add_argument("--digest", action="store_true", help="monitor: kirim ringkasan sekarang")
    a = ap.parse_args()
    cfg = load_config(a.config)

    if a.cmd == "reset":
        Path(cfg["paper"]["db_path"]).unlink(missing_ok=True)
        print("paper DB dihapus")
        return

    if a.cmd == "monitor":
        monitor.watch(cfg, a.provider, a.once, a.force_open, a.digest)
        return

    data = load_universe(cfg, a.provider)
    if a.cmd == "backtest":
        res = backtest.run_backtest(data, cfg)
        print(f"\nStrategi: {cfg['strategy']['name']} {cfg['strategy'].get('params')}")
        print("Hasil backtest:")
        fmt(res["metrics"])
        bh = backtest.buy_and_hold(data, cfg)
        print(f"\nBenchmark equal-weight buy&hold: {bh.iloc[-1] / bh.iloc[0] - 1:.1%}")
        out = Path("data/out"); out.mkdir(parents=True, exist_ok=True)
        res["equity"].to_csv(out / "equity.csv", header=["equity"])
        res["trades"].to_csv(out / "trades.csv", index=False)
        print("Tersimpan: data/out/equity.csv, data/out/trades.csv")
    elif a.cmd == "daily":
        runner.run_daily(cfg, data)
    elif a.cmd == "portfolio":
        runner.show_portfolio(cfg, data)
    elif a.cmd == "screener":
        from idxbot.screener import Screener
        sc = Screener(cfg, data)
        print(sc.format_report(data))
    elif a.cmd == "tv":
        try:
            from idxbot.sources.tradingview import TVScreener, format_scan_table, format_analysis
            tv = TVScreener(exchange="IDX")
            symbols = cfg.get("universe", [])
            print(f"\nAnalisis TradingView untuk {len(symbols)} saham...")
            analyses = tv.scan_signals(symbols)
            print(format_scan_table(analyses))
            # Detail untuk saham dengan sinyal kuat
            for a_item in analyses:
                if "BUY" in a_item.recommendation or "SELL" in a_item.recommendation:
                    print(f"\n{format_analysis(a_item)}")
        except ImportError:
            print("tradingview_ta belum diinstall. Jalankan: pip install tradingview_ta")


if __name__ == "__main__":
    main()
