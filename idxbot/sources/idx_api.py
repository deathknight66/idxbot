"""Adapter data resmi IDX via GOAPI.IO dan endpoint publik IDX.

Ditulis dari nol — BUKAN salinan dari repo MCP manapun.
Endpoint GOAPI.IO gratis tapi terbatas; data delay 3-10 menit.
Untuk data real-time berbayar, lihat idx.co.id/data-services.

Penggunaan:
    from idxbot.sources.idx_api import IDXClient
    client = IDXClient(api_key="...")          # GOAPI key (opsional)
    profile = client.company_profile("BBCA")
    prices  = client.stock_prices(["BBCA", "BBRI"])
    top     = client.top_gainers()
"""
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
import pandas as pd

WIB = timezone(timedelta(hours=7))
UA = {"User-Agent": "Mozilla/5.0 (idxbot/0.2)"}


# ---------------------------------------------------------------------------
# GOAPI.IO adapter (free tier, API key required)
# ---------------------------------------------------------------------------
GOAPI_BASE = "https://api.goapi.io/stock/idx"


def _goapi_headers(api_key: str) -> dict:
    return {"Authorization": api_key, **UA}


class GOAPIError(Exception):
    pass


def _goapi_get(path: str, api_key: str, params: dict | None = None) -> dict:
    url = f"{GOAPI_BASE}{path}"
    r = requests.get(url, headers=_goapi_headers(api_key), params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "error":
        raise GOAPIError(data.get("message", "unknown error"))
    return data.get("data", data)


# ---------------------------------------------------------------------------
# IDX public website JSON endpoints (tidak resmi, bisa berubah)
# ---------------------------------------------------------------------------
IDX_BASE = "https://www.idx.co.id/primary/ListedCompany"
IDX_STOCK = "https://www.idx.co.id/primary/StockData"


def _idx_get(url: str, params: dict | None = None) -> dict:
    """Request ke endpoint publik IDX. Bisa diblokir atau berubah kapan saja."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.idx.co.id/id/data-pasar/data-saham/daftar-saham/",
        "Accept": "application/json",
    }
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class CompanyProfile:
    symbol: str
    name: str
    listing_date: str = ""
    sector: str = ""
    sub_sector: str = ""
    board: str = ""                # utama / pengembangan
    shares_outstanding: int = 0
    market_cap: float = 0.0
    last_price: float = 0.0
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class StockPrice:
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    prev_close: float = 0.0
    change_pct: float = 0.0
    date: str = ""
    raw: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Client utama
# ---------------------------------------------------------------------------
class IDXClient:
    """Klien untuk mengambil data IDX dari GOAPI.IO atau endpoint publik IDX.

    Jika api_key diberikan, pakai GOAPI.IO (lebih stabil).
    Jika tidak, coba endpoint publik IDX (tidak dijamin bekerja).
    """

    def __init__(self, api_key: str | None = None, delay: float = 1.0):
        self.api_key = api_key or os.getenv("GOAPI_API_KEY", "")
        self.delay = delay  # jeda antar-request (sopan ke server)
        self._last_req = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_req
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_req = time.time()

    # ---- Company list ----
    def company_list(self) -> list[dict]:
        """Daftar semua emiten terdaftar di IDX."""
        self._throttle()
        if self.api_key:
            return _goapi_get("/companies", self.api_key)
        return _idx_get(f"{IDX_BASE}/GetCompanyProfiles", {"length": 9999})

    # ---- Company profile ----
    def company_profile(self, symbol: str) -> CompanyProfile:
        """Profil emiten: nama, sektor, market cap, dll."""
        self._throttle()
        if self.api_key:
            raw = _goapi_get(f"/{symbol}/profile", self.api_key)
        else:
            raw = _idx_get(f"{IDX_BASE}/GetCompanyProfile",
                           {"KodeEmiten": symbol})
        return CompanyProfile(
            symbol=symbol,
            name=raw.get("name") or raw.get("CompanyName", ""),
            listing_date=raw.get("listing_date") or raw.get("ListingDate", ""),
            sector=raw.get("sector") or raw.get("Sektor", ""),
            sub_sector=raw.get("sub_sector") or raw.get("SubSektor", ""),
            board=raw.get("board") or raw.get("Board", ""),
            shares_outstanding=int(raw.get("shares_outstanding")
                                   or raw.get("ListedShares", 0)),
            market_cap=float(raw.get("market_cap")
                             or raw.get("MarketCap", 0)),
            last_price=float(raw.get("last_price")
                             or raw.get("LastPrice", 0)),
            raw=raw,
        )

    # ---- Stock prices (snapshot) ----
    def stock_prices(self, symbols: list[str]) -> list[StockPrice]:
        """Harga terkini (delay 3-10 menit via GOAPI, atau dari IDX)."""
        self._throttle()
        results = []
        if self.api_key:
            codes = ",".join(symbols)
            data = _goapi_get("/prices", self.api_key, {"symbols": codes})
            items = data if isinstance(data, list) else data.get("results", [data])
            for item in items:
                results.append(StockPrice(
                    symbol=item.get("symbol", ""),
                    open=float(item.get("open", 0)),
                    high=float(item.get("high", 0)),
                    low=float(item.get("low", 0)),
                    close=float(item.get("close") or item.get("last", 0)),
                    volume=int(item.get("volume", 0)),
                    prev_close=float(item.get("previous", 0)),
                    change_pct=float(item.get("percent", 0)),
                    date=item.get("date", ""),
                    raw=item,
                ))
        else:
            for sym in symbols:
                self._throttle()
                try:
                    raw = _idx_get(f"{IDX_STOCK}/GetStockData",
                                   {"code": sym, "length": 1})
                    items = raw if isinstance(raw, list) else [raw]
                    for item in items:
                        results.append(StockPrice(
                            symbol=sym,
                            open=float(item.get("OpenPrice", 0)),
                            high=float(item.get("High", 0)),
                            low=float(item.get("Low", 0)),
                            close=float(item.get("Close")
                                        or item.get("Last", 0)),
                            volume=int(item.get("Volume", 0)),
                            prev_close=float(item.get("Previous", 0)),
                            change_pct=float(item.get("Change", 0)),
                            date=item.get("Date", ""),
                            raw=item,
                        ))
                except Exception as e:
                    print(f"[idx_api] gagal fetch {sym}: {e}")
        return results

    # ---- Top movers ----
    def top_gainers(self, n: int = 10) -> list[dict]:
        self._throttle()
        if self.api_key:
            return _goapi_get("/top_gainer", self.api_key)
        return []  # endpoint publik tidak tersedia

    def top_losers(self, n: int = 10) -> list[dict]:
        self._throttle()
        if self.api_key:
            return _goapi_get("/top_loser", self.api_key)
        return []

    def trending(self, by: str = "volume") -> list[dict]:
        self._throttle()
        if self.api_key:
            return _goapi_get("/trending", self.api_key, {"by": by})
        return []

    # ---- Index data ----
    def indices(self) -> list[dict]:
        """Daftar indeks (IHSG, LQ45, dll)."""
        self._throttle()
        if self.api_key:
            return _goapi_get("/indices", self.api_key)
        return []

    def index_members(self, index_symbol: str = "LQ45") -> list[str]:
        """Anggota indeks tertentu."""
        self._throttle()
        if self.api_key:
            data = _goapi_get(f"/index/{index_symbol}/items", self.api_key)
            return [d.get("symbol", d.get("code", "")) for d in data
                    if isinstance(d, dict)]
        return []


# ---------------------------------------------------------------------------
# Provider function untuk integrasi ke data.py
# ---------------------------------------------------------------------------
def fetch_ohlcv_idx(symbol: str, api_key: str | None = None) -> Optional[pd.DataFrame]:
    """Fetch harga snapshot saat ini dari IDX API. Mengembalikan satu baris OHLCV
    atau None jika gagal. Untuk data historis, tetap gunakan yfinance."""
    client = IDXClient(api_key=api_key)
    prices = client.stock_prices([symbol])
    if not prices:
        return None
    rows = []
    for p in prices:
        rows.append({
            "Date": pd.Timestamp(p.date or datetime.now(WIB).strftime("%Y-%m-%d")),
            "Open": p.open, "High": p.high, "Low": p.low,
            "Close": p.close, "Volume": p.volume,
        })
    df = pd.DataFrame(rows)
    df.set_index("Date", inplace=True)
    df.index = pd.to_datetime(df.index)
    return df
