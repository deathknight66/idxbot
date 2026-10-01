"""Screener gabungan: TradingView TA + IDX API + sinyal internal idxbot.

Menyediakan satu antarmuka untuk screening saham IDX dari berbagai sumber.
Tidak bergantung pada kode MCP manapun — semua ditulis dari nol.

Penggunaan:
    from idxbot.screener import Screener
    sc = Screener(cfg)
    sc.full_scan()           # scan semua watchlist
    sc.opportunities()       # cari peluang (oversold + sinyal BUY)
"""
from dataclasses import dataclass, field
from typing import Optional

from .strategy import get_signal_fn

try:
    from .sources.tradingview import TVScreener, TVAnalysis, format_scan_table
    HAS_TV = True
except ImportError:
    HAS_TV = False

try:
    from .sources.idx_api import IDXClient, CompanyProfile, StockPrice
    HAS_IDX = True
except ImportError:
    HAS_IDX = False


@dataclass
class StockOpportunity:
    symbol: str
    close: float = 0.0
    # TradingView
    tv_recommendation: str = ""
    rsi: float = 0.0
    macd: float = 0.0
    adx: float = 0.0
    # Internal signal
    internal_signal: int = 0          # 0=flat, 1=long
    signal_changed: bool = False
    # IDX info
    sector: str = ""
    market_cap: float = 0.0
    # Skor gabungan (heuristik sederhana)
    score: float = 0.0


class Screener:
    """Screener gabungan untuk saham IDX."""

    def __init__(self, cfg: dict, data: dict | None = None):
        self.cfg = cfg
        self.data = data or {}
        self.symbols = list(cfg.get("universe", []))
        # Tambah watchlist monitor kalau ada
        watchlist = cfg.get("monitor", {}).get("watchlist", {})
        for s in watchlist:
            if s not in self.symbols:
                self.symbols.append(s)

        self.tv: Optional[TVScreener] = None
        self.idx: Optional[IDXClient] = None

        if HAS_TV:
            try:
                self.tv = TVScreener(exchange="IDX")
            except ImportError:
                pass

        if HAS_IDX:
            api_key = cfg.get("sources", {}).get("goapi_key", "")
            self.idx = IDXClient(api_key=api_key)

    def tv_scan(self, symbols: list[str] | None = None,
                interval: str = "1d") -> list:
        """Scan TradingView TA untuk daftar saham."""
        if not self.tv:
            print("[screener] tradingview_ta tidak tersedia")
            return []
        syms = symbols or self.symbols
        return self.tv.scan_signals(syms, interval)

    def idx_prices(self, symbols: list[str] | None = None) -> list:
        """Harga terkini dari IDX API."""
        if not self.idx:
            print("[screener] IDX API client tidak tersedia (butuh GOAPI key)")
            return []
        syms = symbols or self.symbols
        return self.idx.stock_prices(syms)

    def idx_profiles(self, symbols: list[str] | None = None) -> list:
        """Profil emiten dari IDX API."""
        if not self.idx:
            return []
        syms = symbols or self.symbols
        profiles = []
        for s in syms:
            try:
                profiles.append(self.idx.company_profile(s))
            except Exception as e:
                print(f"[screener] profil {s}: {e}")
        return profiles

    def internal_signals(self, data: dict | None = None) -> dict:
        """Hitung sinyal dari strategi internal idxbot."""
        data = data or self.data
        if not data:
            return {}
        sig_fn = get_signal_fn(self.cfg)
        signals = {}
        for sym, df in data.items():
            sig = sig_fn(df)
            current = int(sig.iloc[-1])
            prev = int(sig.iloc[-2]) if len(sig) > 1 else current
            signals[sym] = {
                "signal": current,
                "changed": current != prev,
                "close": float(df["Close"].iloc[-1]),
            }
        return signals

    def full_scan(self, data: dict | None = None,
                  interval: str = "1d") -> list[StockOpportunity]:
        """Scan lengkap: gabungan TradingView + internal signal + IDX data."""
        data = data or self.data
        results = []

        # 1) Internal signals
        int_sig = self.internal_signals(data)

        # 2) TradingView analysis
        tv_map = {}
        if self.tv:
            for a in self.tv_scan(interval=interval):
                tv_map[a.symbol] = a

        # 3) IDX profiles (opsional)
        idx_map = {}
        if self.idx:
            try:
                for p in self.idx_profiles():
                    idx_map[p.symbol] = p
            except Exception:
                pass

        # 4) Gabungkan
        all_syms = set(self.symbols) | set(int_sig.keys()) | set(tv_map.keys())
        for sym in sorted(all_syms):
            opp = StockOpportunity(symbol=sym)

            # Internal
            if sym in int_sig:
                opp.internal_signal = int_sig[sym]["signal"]
                opp.signal_changed = int_sig[sym]["changed"]
                opp.close = int_sig[sym]["close"]

            # TradingView
            if sym in tv_map:
                tv = tv_map[sym]
                opp.tv_recommendation = tv.recommendation
                opp.rsi = tv.rsi
                opp.macd = tv.macd
                opp.adx = tv.adx
                if not opp.close:
                    opp.close = tv.close

            # IDX
            if sym in idx_map:
                opp.sector = idx_map[sym].sector
                opp.market_cap = idx_map[sym].market_cap

            # Skor heuristik
            opp.score = _calc_score(opp)
            results.append(opp)

        return sorted(results, key=lambda x: -x.score)

    def opportunities(self, data: dict | None = None) -> list[StockOpportunity]:
        """Filter hanya peluang menarik (skor > 0)."""
        return [o for o in self.full_scan(data) if o.score > 0]

    def format_report(self, data: dict | None = None) -> str:
        """Laporan teks lengkap."""
        scan = self.full_scan(data)
        lines = ["=" * 70,
                 " SCREENER IDX — Scan Gabungan",
                 "=" * 70,
                 f"{'SAHAM':<7}{'CLOSE':>9}{'RSI':>7}{'ADX':>7}"
                 f"{'MACD':>9}  {'TV':>12}  {'INT':>5}  {'SKOR':>5}",
                 "-" * 70]
        for o in scan:
            sig_str = "LONG" if o.internal_signal == 1 else "flat"
            chg = "*" if o.signal_changed else " "
            lines.append(
                f"{o.symbol:<7}{o.close:>9,.0f}{o.rsi:>7.1f}{o.adx:>7.1f}"
                f"{o.macd:>9.1f}  {o.tv_recommendation:>12}  "
                f"{sig_str:>4}{chg} {o.score:>5.1f}"
            )

        # Highlight peluang
        opps = [o for o in scan if o.score > 0]
        if opps:
            lines.append(f"\n{'='*70}")
            lines.append(" PELUANG (skor > 0):")
            for o in opps:
                reasons = []
                if "BUY" in o.tv_recommendation.upper():
                    reasons.append(f"TV:{o.tv_recommendation}")
                if o.internal_signal == 1:
                    reasons.append("sinyal masuk")
                if o.signal_changed:
                    reasons.append("BARU berubah")
                if 0 < o.rsi <= 30:
                    reasons.append(f"RSI oversold ({o.rsi:.0f})")
                lines.append(f"  {o.symbol}: {', '.join(reasons)}")

        return "\n".join(lines)


def _calc_score(opp: StockOpportunity) -> float:
    """Skor heuristik sederhana. Bukan rekomendasi investasi."""
    s = 0.0
    # TradingView recommendation
    rec_scores = {"STRONG_BUY": 2.0, "BUY": 1.0, "NEUTRAL": 0.0,
                  "SELL": -1.0, "STRONG_SELL": -2.0}
    s += rec_scores.get(opp.tv_recommendation, 0.0)
    # Internal signal alignment
    if opp.internal_signal == 1:
        s += 1.5
    if opp.signal_changed and opp.internal_signal == 1:
        s += 1.0  # bonus sinyal baru
    # RSI oversold bonus
    if 0 < opp.rsi <= 30:
        s += 1.0
    elif opp.rsi >= 70:
        s -= 0.5
    # ADX trend strength
    if opp.adx >= 25:
        s += 0.5  # tren kuat
    # MACD positive
    if opp.macd > 0:
        s += 0.3
    return round(s, 1)
