"""Strategi = fungsi (df OHLCV, **params) -> Series 0/1: posisi yang DIINGINKAN
pada penutupan hari t (hanya pakai data sampai t). Eksekusi terjadi di
open t+1, jadi tidak ada look-ahead."""
import pandas as pd


def sma_cross(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    f = df["Close"].rolling(fast).mean()
    s = df["Close"].rolling(slow).mean()
    return (f > s).astype(int).where(s.notna(), 0)


def breakout(df: pd.DataFrame, entry: int = 20, exit: int = 10) -> pd.Series:
    """Donchian: masuk saat close tembus high N hari, keluar saat tembus low M hari."""
    hi = df["Close"].rolling(entry).max().shift(1)
    lo = df["Close"].rolling(exit).min().shift(1)
    state, out = 0, []
    for c, h, l in zip(df["Close"], hi, lo):
        if state == 0 and pd.notna(h) and c > h:
            state = 1
        elif state == 1 and pd.notna(l) and c < l:
            state = 0
        out.append(state)
    return pd.Series(out, index=df.index)


def rsi_strategy(df: pd.DataFrame, period: int = 14,
                  oversold: float = 30.0, overbought: float = 70.0) -> pd.Series:
    """RSI mean-reversion: masuk saat oversold, keluar saat overbought."""
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - 100 / (1 + rs)
    state, out = 0, []
    for r in rsi:
        if state == 0 and pd.notna(r) and r <= oversold:
            state = 1
        elif state == 1 and pd.notna(r) and r >= overbought:
            state = 0
        out.append(state)
    return pd.Series(out, index=df.index)


def macd_cross(df: pd.DataFrame, fast: int = 12, slow: int = 26,
               signal: int = 9) -> pd.Series:
    """MACD: masuk saat MACD line naik di atas signal line."""
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return (macd_line > signal_line).astype(int).where(signal_line.notna(), 0)


def bollinger(df: pd.DataFrame, period: int = 20,
              std_dev: float = 2.0) -> pd.Series:
    """Bollinger Band mean-reversion: masuk di bawah lower band, keluar di atas upper."""
    sma = df["Close"].rolling(period).mean()
    std = df["Close"].rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    state, out = 0, []
    for c, u, l in zip(df["Close"], upper, lower):
        if state == 0 and pd.notna(l) and c <= l:
            state = 1
        elif state == 1 and pd.notna(u) and c >= u:
            state = 0
        out.append(state)
    return pd.Series(out, index=df.index)


def combo(df: pd.DataFrame, rsi_period: int = 14, rsi_threshold: float = 40.0,
          macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9,
          sma_period: int = 50) -> pd.Series:
    """Kombinasi RSI + MACD + SMA: masuk hanya jika 3 sinyal sepakat.
    - RSI di atas threshold (bukan di zona lemah)
    - MACD line di atas signal line
    - Close di atas SMA
    """
    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - 100 / (1 + rs)
    rsi_ok = (rsi >= rsi_threshold) & (rsi <= 80)
    # MACD
    ema_f = df["Close"].ewm(span=macd_fast, adjust=False).mean()
    ema_s = df["Close"].ewm(span=macd_slow, adjust=False).mean()
    macd_ok = (ema_f - ema_s) > (ema_f - ema_s).ewm(span=macd_signal, adjust=False).mean()
    # SMA
    sma = df["Close"].rolling(sma_period).mean()
    sma_ok = df["Close"] > sma
    # Gabungan
    return (rsi_ok & macd_ok & sma_ok).astype(int).where(sma.notna(), 0)


STRATEGIES = {
    "sma_cross": sma_cross,
    "breakout": breakout,
    "rsi": rsi_strategy,
    "macd_cross": macd_cross,
    "bollinger": bollinger,
    "combo": combo,
}


def get_signal_fn(cfg: dict):
    s = cfg["strategy"]
    fn = STRATEGIES[s["name"]]
    params = s.get("params", {}) or {}
    return lambda df: fn(df, **params)
