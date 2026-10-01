"""Screener dan analisis teknikal dari TradingView via library tradingview_ta.

Ditulis dari nol — BUKAN salinan dari tradingview-mcp.
Library tradingview_ta adalah open-source (MIT) dan tersedia via pip.

Untuk saham IDX, gunakan:
    screener = "indonesia"
    exchange = "IDX"
    symbol   = "BBCA"  (tanpa .JK)

Penggunaan:
    from idxbot.sources.tradingview import TVScreener
    tv = TVScreener()
    rec = tv.get_analysis("BBCA")
    gainers = tv.top_gainers()
    signals = tv.scan_signals(["BBCA", "BBRI", "BMRI"])
"""
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    from tradingview_ta import TA_Handler, Interval, TradingView
    HAS_TV = True
except ImportError:
    HAS_TV = False

import pandas as pd


# ---------------------------------------------------------------------------
# Exchange mapping — untuk pasar Indonesia cukup satu entry
# ---------------------------------------------------------------------------
EXCHANGE_SCREENER = {
    # exchange_code: screener_name
    "IDX": "indonesia",
    "NASDAQ": "america",
    "NYSE": "america",
    "AMEX": "america",
    "ASX": "australia",
    "TSE": "japan",
    "HKEX": "hongkong",
    "SGX": "singapore",
    "KRX": "korea",
    "SET": "thailand",
    "KLSE": "malaysia",
    "PSE": "philippines",
    "BINANCE": "crypto",
    "BYBIT": "crypto",
    "COINBASE": "crypto",
}

INTERVALS = {
    "1m": Interval.INTERVAL_1_MINUTE if HAS_TV else "1m",
    "5m": Interval.INTERVAL_5_MINUTES if HAS_TV else "5m",
    "15m": Interval.INTERVAL_15_MINUTES if HAS_TV else "15m",
    "1h": Interval.INTERVAL_1_HOUR if HAS_TV else "1h",
    "4h": Interval.INTERVAL_4_HOURS if HAS_TV else "4h",
    "1d": Interval.INTERVAL_1_DAY if HAS_TV else "1d",
    "1w": Interval.INTERVAL_1_WEEK if HAS_TV else "1w",
    "1M": Interval.INTERVAL_1_MONTH if HAS_TV else "1M",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class TVAnalysis:
    symbol: str
    exchange: str
    interval: str
    recommendation: str          # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    buy_count: int = 0
    sell_count: int = 0
    neutral_count: int = 0
    # Indikator kunci
    rsi: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    ema_20: float = 0.0
    sma_50: float = 0.0
    sma_200: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    adx: float = 0.0
    atr: float = 0.0
    stoch_k: float = 0.0
    stoch_d: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    # Oscillator & MA breakdowns
    oscillators: dict = field(default_factory=dict, repr=False)
    moving_averages: dict = field(default_factory=dict, repr=False)
    indicators: dict = field(default_factory=dict, repr=False)


@dataclass
class ScreenerResult:
    symbol: str
    recommendation: str
    rsi: float = 0.0
    change_pct: float = 0.0
    volume: float = 0.0
    close: float = 0.0


# ---------------------------------------------------------------------------
# Screener utama
# ---------------------------------------------------------------------------
class TVScreener:
    """Wrapper TradingView TA untuk screener saham IDX."""

    def __init__(self, exchange: str = "IDX", delay: float = 0.5):
        if not HAS_TV:
            raise ImportError(
                "tradingview_ta belum diinstall. Jalankan: pip install tradingview_ta"
            )
        self.exchange = exchange
        self.screener = EXCHANGE_SCREENER.get(exchange, "indonesia")
        self.delay = delay
        self._last_req = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_req
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_req = time.time()

    def get_analysis(self, symbol: str,
                     interval: str = "1d") -> Optional[TVAnalysis]:
        """Ambil analisis teknikal lengkap untuk satu saham."""
        self._throttle()
        iv = INTERVALS.get(interval, Interval.INTERVAL_1_DAY)
        try:
            handler = TA_Handler(
                symbol=symbol,
                screener=self.screener,
                exchange=self.exchange,
                interval=iv,
            )
            a = handler.get_analysis()
        except Exception as e:
            print(f"[tv] gagal analisis {symbol}: {e}")
            return None

        ind = a.indicators or {}
        summary = a.summary or {}
        return TVAnalysis(
            symbol=symbol,
            exchange=self.exchange,
            interval=interval,
            recommendation=summary.get("RECOMMENDATION", "NEUTRAL"),
            buy_count=summary.get("BUY", 0),
            sell_count=summary.get("SELL", 0),
            neutral_count=summary.get("NEUTRAL", 0),
            rsi=float(ind.get("RSI", 0) or 0),
            macd=float(ind.get("MACD.macd", 0) or 0),
            macd_signal=float(ind.get("MACD.signal", 0) or 0),
            ema_20=float(ind.get("EMA20", 0) or 0),
            sma_50=float(ind.get("SMA50", 0) or 0),
            sma_200=float(ind.get("SMA200", 0) or 0),
            bb_upper=float(ind.get("BB.upper", 0) or 0),
            bb_lower=float(ind.get("BB.lower", 0) or 0),
            adx=float(ind.get("ADX", 0) or 0),
            atr=float(ind.get("ATR", 0) or 0),
            stoch_k=float(ind.get("Stoch.K", 0) or 0),
            stoch_d=float(ind.get("Stoch.D", 0) or 0),
            close=float(ind.get("close", 0) or 0),
            volume=float(ind.get("volume", 0) or 0),
            oscillators=a.oscillators or {},
            moving_averages=a.moving_averages or {},
            indicators=ind,
        )

    def scan_signals(self, symbols: list[str],
                     interval: str = "1d") -> list[TVAnalysis]:
        """Scan sinyal untuk daftar saham."""
        results = []
        for sym in symbols:
            a = self.get_analysis(sym, interval)
            if a:
                results.append(a)
        return results

    def screen_by_recommendation(self, symbols: list[str],
                                 target: str = "BUY",
                                 interval: str = "1d") -> list[TVAnalysis]:
        """Filter saham yang rekomendasinya cocok (BUY, STRONG_BUY, dll)."""
        all_signals = self.scan_signals(symbols, interval)
        return [a for a in all_signals
                if target.upper() in a.recommendation.upper()]

    def top_by_rsi(self, symbols: list[str],
                   interval: str = "1d",
                   oversold: float = 30.0,
                   overbought: float = 70.0) -> dict:
        """Identifikasi saham oversold dan overbought berdasarkan RSI."""
        all_signals = self.scan_signals(symbols, interval)
        return {
            "oversold": [a for a in all_signals if 0 < a.rsi <= oversold],
            "overbought": [a for a in all_signals if a.rsi >= overbought],
            "neutral": [a for a in all_signals
                        if oversold < a.rsi < overbought],
        }

    def multi_timeframe(self, symbol: str,
                        intervals: list[str] | None = None) -> list[TVAnalysis]:
        """Analisis multi-timeframe: cek konsistensi sinyal."""
        intervals = intervals or ["1h", "4h", "1d", "1w"]
        results = []
        for iv in intervals:
            a = self.get_analysis(symbol, iv)
            if a:
                results.append(a)
        return results


# ---------------------------------------------------------------------------
# Format output
# ---------------------------------------------------------------------------
def format_analysis(a: TVAnalysis) -> str:
    """Format analisis ke string ringkas."""
    lines = [
        f"{'='*50}",
        f" {a.symbol} ({a.exchange}) | {a.interval}",
        f"{'='*50}",
        f" Rekomendasi : {a.recommendation}",
        f"   Buy {a.buy_count} | Neutral {a.neutral_count} | Sell {a.sell_count}",
        f" Close       : {a.close:,.0f}",
        f" RSI         : {a.rsi:.1f}",
        f" MACD        : {a.macd:.2f} (signal: {a.macd_signal:.2f})",
        f" ADX         : {a.adx:.1f}",
        f" Stoch K/D   : {a.stoch_k:.1f} / {a.stoch_d:.1f}",
        f" EMA20       : {a.ema_20:,.0f}",
        f" SMA50       : {a.sma_50:,.0f}",
        f" SMA200      : {a.sma_200:,.0f}",
        f" BB          : {a.bb_lower:,.0f} - {a.bb_upper:,.0f}",
    ]
    return "\n".join(lines)


def format_scan_table(analyses: list[TVAnalysis]) -> str:
    """Tabel ringkas scan sinyal."""
    header = f"{'SAHAM':<7}{'CLOSE':>9}{'RSI':>7}{'ADX':>7}{'MACD':>9}  REKOMENDASI"
    rows = [header, "-" * len(header)]
    for a in sorted(analyses, key=lambda x: x.recommendation):
        rows.append(
            f"{a.symbol:<7}{a.close:>9,.0f}{a.rsi:>7.1f}{a.adx:>7.1f}"
            f"{a.macd:>9.1f}  {a.recommendation}"
        )
    return "\n".join(rows)
