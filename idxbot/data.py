from pathlib import Path
import zlib
import numpy as np
import pandas as pd

COLS = ["Open", "High", "Low", "Close", "Volume"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[COLS].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "Date"
    df = df[~df.index.duplicated()].sort_index()
    # buang hari tanpa transaksi / data rusak
    df = df.dropna()
    df = df[(df["Volume"] > 0) & (df["Close"] > 0)]
    return df


def _yfinance(symbol, start, cache_dir):
    import yfinance as yf
    cache = Path(cache_dir) / f"{symbol}.csv"
    cache.parent.mkdir(parents=True, exist_ok=True)
    df = yf.download(f"{symbol}.JK", start=start, auto_adjust=False,
                     progress=False)
    if df is None or df.empty:
        if cache.exists():  # fallback ke cache kalau jaringan/Yahoo bermasalah
            return _clean(pd.read_csv(cache, index_col=0, parse_dates=True))
        raise RuntimeError(f"Tidak ada data untuk {symbol}")
    df = _clean(df)
    df.to_csv(cache)
    return df


def _csv(symbol, csv_dir):
    p = Path(csv_dir) / f"{symbol}.csv"
    return _clean(pd.read_csv(p, index_col=0, parse_dates=True))


def _synthetic(symbol, start, n=1500):
    """Data acak (GBM) -- HANYA untuk tes pipeline, bukan untuk riset."""
    rng = np.random.default_rng(zlib.crc32(symbol.encode()))
    idx = pd.bdate_range(start=start, periods=n)
    ret = rng.normal(0.0003, 0.018, n)
    close = 3000 * np.exp(np.cumsum(ret))
    close = np.round(close / 5) * 5
    open_ = np.roll(close, 1) * (1 + rng.normal(0, 0.004, n))
    open_[0] = close[0]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    vol = rng.integers(1_000_000, 50_000_000, n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low,
                         "Close": close, "Volume": vol}, index=idx)


def load_universe(cfg: dict, provider: str | None = None) -> dict:
    d = cfg["data"]
    provider = provider or d["provider"]
    out = {}
    for sym in cfg["universe"]:
        try:
            if provider == "yfinance":
                df = _yfinance(sym, d["start"], d["cache_dir"])
            elif provider == "csv":
                df = _csv(sym, d["csv_dir"])
            elif provider == "synthetic":
                df = _synthetic(sym, d["start"])
            else:
                raise ValueError(provider)
            out[sym] = df
        except Exception as e:  # satu saham gagal jangan matikan semuanya
            print(f"[data] skip {sym}: {e}")
    if not out:
        raise RuntimeError("Tidak ada data yang berhasil dimuat")
    return out
