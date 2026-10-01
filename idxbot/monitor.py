"""Bot monitoring saham IDX: polling harga saat jam bursa, alert berbasis aturan,
ringkasan harian. Tidak mengirim order apa pun.

Catatan jujur soal data: sumber Yahoo tidak resmi dan bisa tertunda; libur bursa tidak
dikenali (bot hanya melaporkan data basi). Untuk keputusan dengan uang asli, cek harga
di aplikasi broker."""
import sqlite3
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import idx_rules as idx, notify
from .data import _clean, _synthetic
from .strategy import get_signal_fn

WIB = timezone(timedelta(hours=7))
UA = {"User-Agent": "Mozilla/5.0 (idxbot-monitor)"}
RULE_TYPES = {
    "price_above", "price_below", "pct_move", "volume_spike", "near_limit",
    # --- aturan baru (terinspirasi pola alert umum) ---
    "gap_up", "gap_down",           # gap harga open vs close kemarin
    "consecutive_up", "consecutive_down",  # N hari berturut naik/turun
    "rsi_oversold", "rsi_overbought",      # RSI menembus batas
    "macd_cross_up", "macd_cross_down",    # MACD line cross signal
    "bb_breakout",                          # close di luar Bollinger Band
}


# ---------------------------------------------------------------- jadwal bursa
def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def sessions_for(now: datetime, cfg: dict):
    if now.weekday() >= 5:
        return []
    key = "fri" if now.weekday() == 4 else "mon_thu"
    return [(_hm(a), _hm(b)) for a, b in cfg["monitor"]["sessions"][key]]


def _minutes(now): return now.hour * 60 + now.minute


def in_session(now, cfg) -> bool:
    return any(a <= _minutes(now) <= b for a, b in sessions_for(now, cfg))


def after_close(now, cfg) -> bool:
    ss = sessions_for(now, cfg)
    return bool(ss) and _minutes(now) > ss[-1][1]


def session_fraction(now, cfg) -> float:
    """Porsi sesi hari ini yang sudah berjalan (jeda siang tidak dihitung)."""
    ss = sessions_for(now, cfg)
    total = sum(b - a for a, b in ss)
    if not total:
        return 1.0
    m = _minutes(now)
    done = sum(max(0, min(m, b) - a) for a, b in ss)
    return max(0.0, min(1.0, done / total))


# ------------------------------------------------------------------ data quote
@dataclass
class Quote:
    symbol: str
    price: float
    prev_close: float
    volume: float
    avg_volume: float
    ts: datetime
    bars: pd.DataFrame = field(repr=False, default=None)

    @property
    def pct(self) -> float:
        return (self.price / self.prev_close - 1) * 100 if self.prev_close else 0.0

    def vol_ratio(self, frac: float):
        if not self.avg_volume:
            return None
        return self.volume / (self.avg_volume * max(frac, 0.15))  # lantai 15%: hindari noise pagi


def _yahoo_quote(sym: str) -> Quote:
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.JK",
                     params={"interval": "1d", "range": "3mo"}, headers=UA, timeout=15)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    idxs = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(WIB).tz_localize(None)
    df = _clean(pd.DataFrame({"Open": q["open"], "High": q["high"], "Low": q["low"],
                              "Close": q["close"], "Volume": q["volume"]}, index=idxs))
    meta = res["meta"]
    ts = datetime.fromtimestamp(meta["regularMarketTime"], WIB)
    price = float(meta.get("regularMarketPrice") or df["Close"].iloc[-1])
    if df.index[-1].date() == ts.date() and len(df) > 21:   # bar hari ini sudah ada
        prev, vol = float(df["Close"].iloc[-2]), float(df["Volume"].iloc[-1])
        avg = float(df["Volume"].iloc[-21:-1].mean())
    else:                                                   # belum ada bar hari ini
        prev, vol = float(df["Close"].iloc[-1]), 0.0
        avg = float(df["Volume"].iloc[-20:].mean())
    return Quote(sym, price, prev, vol, avg, ts, df)


def _synthetic_quote(sym: str, now: datetime) -> Quote:
    df = _synthetic(sym, "2024-01-01", n=300)
    hist, prev = df.iloc[:-1], float(df["Close"].iloc[-2])
    rng = np.random.default_rng(zlib.crc32(f"{sym}{now:%Y%m%d%H%M}".encode()))
    price = idx.round_to_tick(prev * (1 + rng.normal(0, 0.03)))
    avg = float(hist["Volume"].iloc[-20:].mean())
    return Quote(sym, price, prev, avg * rng.uniform(0.2, 2.0), avg, now, hist)


def fetch_quotes(symbols, provider: str, now: datetime):
    out, failed = {}, []
    for s in symbols:
        try:
            out[s] = _synthetic_quote(s, now) if provider == "synthetic" else _yahoo_quote(s)
        except Exception as e:
            failed.append(s)
            print(f"[monitor] gagal {s}: {e}")
        if provider != "synthetic":
            time.sleep(0.3)  # sopan ke sumber data
    return out, failed


# ----------------------------------------------------------------------- aturan
def validate(cfg: dict):
    m = cfg["monitor"]
    rules = list(m.get("default_rules") or [])
    for v in (m.get("watchlist") or {}).values():
        rules += v or []
    for r in rules:
        if r.get("type") not in RULE_TYPES or "value" not in r:
            raise ValueError(f"aturan tidak valid: {r} (tipe: {sorted(RULE_TYPES)})")


def _calc_rsi(series, period=14):
    """Hitung RSI dari series Close. Mengembalikan Series."""
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - 100 / (1 + rs)


def _calc_macd(series, fast=12, slow=26, signal=9):
    """Hitung MACD line dan signal line."""
    ema_f = series.ewm(span=fast, adjust=False).mean()
    ema_s = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_f - ema_s
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def _calc_bb(series, period=20, std_dev=2.0):
    """Hitung Bollinger Bands."""
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    return sma + std_dev * std, sma - std_dev * std


def evaluate(q: Quote, rule: dict, frac: float, cfg: dict):
    t, v = rule["type"], float(rule["value"])
    if t == "price_above" and q.price >= v:
        return f"harga di atas {v:,.0f}"
    if t == "price_below" and q.price <= v:
        return f"harga di bawah {v:,.0f}"
    if t == "pct_move" and abs(q.pct) >= v:
        return f"bergerak {q.pct:+.1f}% vs close kemarin"
    if t == "volume_spike":
        r = q.vol_ratio(frac)
        if r is not None and r >= v:
            return f"volume {r:.1f}x rata-rata (proyeksi sesi)"
    if t == "near_limit" and q.prev_close:
        arb, ara = idx.limits(q.prev_close, cfg["idx"]["ara_pct"], cfg["idx"]["arb_pct"])
        if q.price >= ara * (1 - v / 100):
            return f"dekat ARA ({ara:,.0f})"
        if q.price <= arb * (1 + v / 100):
            return f"dekat ARB ({arb:,.0f})"

    # --- Aturan baru yang membutuhkan data historis (bars) ---
    bars = q.bars

    if t == "gap_up" and q.prev_close:
        gap_pct = (q.price / q.prev_close - 1) * 100
        if gap_pct >= v:
            return f"gap up {gap_pct:.1f}% (batas {v:.1f}%)"
    if t == "gap_down" and q.prev_close:
        gap_pct = (1 - q.price / q.prev_close) * 100
        if gap_pct >= v:
            return f"gap down {gap_pct:.1f}% (batas {v:.1f}%)"

    if t == "consecutive_up" and bars is not None and len(bars) >= int(v) + 1:
        n = int(v)
        changes = bars["Close"].pct_change().iloc[-n:]
        if (changes > 0).all():
            return f"{n} hari berturut naik"
    if t == "consecutive_down" and bars is not None and len(bars) >= int(v) + 1:
        n = int(v)
        changes = bars["Close"].pct_change().iloc[-n:]
        if (changes < 0).all():
            return f"{n} hari berturut turun"

    if t == "rsi_oversold" and bars is not None and len(bars) > 14:
        rsi = _calc_rsi(bars["Close"])
        if pd.notna(rsi.iloc[-1]) and rsi.iloc[-1] <= v:
            return f"RSI {rsi.iloc[-1]:.0f} (oversold <= {v:.0f})"
    if t == "rsi_overbought" and bars is not None and len(bars) > 14:
        rsi = _calc_rsi(bars["Close"])
        if pd.notna(rsi.iloc[-1]) and rsi.iloc[-1] >= v:
            return f"RSI {rsi.iloc[-1]:.0f} (overbought >= {v:.0f})"

    if t == "macd_cross_up" and bars is not None and len(bars) > 30:
        ml, sl = _calc_macd(bars["Close"])
        if len(ml) >= 2 and ml.iloc[-1] > sl.iloc[-1] and ml.iloc[-2] <= sl.iloc[-2]:
            return "MACD golden cross (line naik di atas signal)"
    if t == "macd_cross_down" and bars is not None and len(bars) > 30:
        ml, sl = _calc_macd(bars["Close"])
        if len(ml) >= 2 and ml.iloc[-1] < sl.iloc[-1] and ml.iloc[-2] >= sl.iloc[-2]:
            return "MACD death cross (line turun di bawah signal)"

    if t == "bb_breakout" and bars is not None and len(bars) > 20:
        upper, lower = _calc_bb(bars["Close"])
        last_close = bars["Close"].iloc[-1]
        if pd.notna(upper.iloc[-1]) and last_close > upper.iloc[-1]:
            return f"breakout di atas Bollinger Band atas ({upper.iloc[-1]:,.0f})"
        if pd.notna(lower.iloc[-1]) and last_close < lower.iloc[-1]:
            return f"breakdown di bawah Bollinger Band bawah ({lower.iloc[-1]:,.0f})"

    return None


class State:
    """Dedupe alert (cooldown) dan flag harian, disimpan di SQLite."""
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript("CREATE TABLE IF NOT EXISTS sent(k TEXT PRIMARY KEY, ts REAL);"
                              "CREATE TABLE IF NOT EXISTS flags(k TEXT PRIMARY KEY);")

    def due(self, key, cooldown_min, now_ts) -> bool:
        row = self.db.execute("SELECT ts FROM sent WHERE k=?", (key,)).fetchone()
        return row is None or now_ts - row[0] >= cooldown_min * 60

    def mark(self, key, now_ts):
        self.db.execute("INSERT OR REPLACE INTO sent VALUES(?,?)", (key, now_ts))
        self.db.commit()

    def flag(self, key) -> bool:
        return self.db.execute("SELECT 1 FROM flags WHERE k=?", (key,)).fetchone() is not None

    def set_flag(self, key):
        self.db.execute("INSERT OR IGNORE INTO flags VALUES(?)", (key,))
        self.db.commit()


def run_cycle(cfg, quotes: dict, failed: list, now: datetime, state: State):
    m = cfg["monitor"]
    frac = session_fraction(now, cfg)
    lines, today = [], str(now.date())
    stale = [s for s, q in quotes.items()
             if q.ts.date() != now.date() or now - q.ts > timedelta(minutes=m["stale_minutes"])]
    if stale and not state.flag(f"stale:{today}"):
        state.set_flag(f"stale:{today}")
        lines.append(f"PERINGATAN data basi/belum ada hari ini: {', '.join(stale)} "
                     f"(libur bursa, delay, atau sumber bermasalah?)")
    if failed and len(failed) >= max(1, len(quotes) + len(failed)) / 2 and not state.flag(f"fail:{today}"):
        state.set_flag(f"fail:{today}")
        lines.append(f"PERINGATAN sumber data gagal untuk: {', '.join(failed)}")
    for s, q in quotes.items():
        if s in stale:      # jangan alert dari data basi
            continue
        rules = list(m.get("default_rules") or []) + list((m["watchlist"].get(s) or []))
        for r in rules:
            why = evaluate(q, r, frac, cfg)
            key = f"{s}|{r['type']}:{r['value']}"
            if why and state.due(key, m["cooldown_minutes"], now.timestamp()):
                state.mark(key, now.timestamp())
                lines.append(f"[{now:%H:%M} WIB] {s} {q.price:,.0f} ({q.pct:+.1f}%) - {why}")
    return lines


def board(quotes: dict, frac: float) -> str:
    rows = [f"{'SAHAM':<7}{'HARGA':>9}{'%':>8}{'VOL x':>8}  DATA"]
    for s, q in quotes.items():
        r = q.vol_ratio(frac)
        rows.append(f"{s:<7}{q.price:>9,.0f}{q.pct:>+7.1f}%{(f'{r:.1f}' if r else '-'):>8}  {q.ts:%d %b %H:%M}")
    return "\n".join(rows)


def digest(cfg, quotes: dict, now: datetime) -> str:
    sig_fn = get_signal_fn(cfg)
    lines = [f"== Ringkasan watchlist {now:%d %b %Y} (data terakhir yang tersedia) =="]
    for s, q in quotes.items():
        sig = sig_fn(q.bars)
        state = "LONG" if sig.iloc[-1] == 1 else "flat"
        flip = " (BARU berubah)" if len(sig) > 1 and sig.iloc[-1] != sig.iloc[-2] else ""
        r = q.vol_ratio(1.0)
        lines.append(f"{s:<6}{q.price:>8,.0f} {q.pct:>+6.1f}% | vol {f'{r:.1f}x' if r else '-'} | "
                     f"strategi {cfg['strategy']['name']}: {state}{flip}")
    return "\n".join(lines)


# ------------------------------------------------------------------- loop utama
def watch(cfg: dict, provider=None, once=False, force_open=False, send_digest=False):
    validate(cfg)
    m = cfg["monitor"]
    provider = provider or m["provider"]
    state = State(m["db_path"])
    symbols = list(m["watchlist"])
    print(f"Monitoring {len(symbols)} saham ({provider}). Ctrl+C untuk berhenti.")
    try:
        while True:
            now = datetime.now(WIB)
            open_now = force_open or in_session(now, cfg)
            want_digest = send_digest or (m.get("daily_digest") and after_close(now, cfg)
                                          and not state.flag(f"digest:{now.date()}"))
            if open_now or want_digest or once:
                quotes, failed = fetch_quotes(symbols, provider, now)
                if quotes:
                    frac = session_fraction(now, cfg) if in_session(now, cfg) else 1.0
                    if once:
                        print(board(quotes, frac))
                    if open_now:
                        alerts = run_cycle(cfg, quotes, failed, now, state)
                        if alerts:
                            notify.send("\n".join(alerts), cfg)
                    if want_digest:
                        notify.send(digest(cfg, quotes, now), cfg)
                        state.set_flag(f"digest:{now.date()}")
            if once:
                break
            time.sleep(m["poll_seconds"] if open_now else 60)
    except KeyboardInterrupt:
        print("\nberhenti.")
