import numpy as np
import pandas as pd
import yfinance as yf
import traceback
import logging
logger = logging.getLogger('engine')

INITIAL_CAPITAL = 100_000_000
UNIVERSE = [
    # Banking
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "BRIS.JK", "ARTO.JK",
    # Mining & Energy
    "ADRO.JK", "PTBA.JK", "ITMG.JK", "UNTR.JK", "PGAS.JK", "MEDC.JK",
    "AKRA.JK", "HRUM.JK", "INDY.JK",
    # Basic Materials
    "ANTM.JK", "MDKA.JK", "INCO.JK", "TINS.JK", "BRPT.JK", "TPIA.JK", "AMMN.JK",
    # Consumer
    "ICBP.JK", "INDF.JK", "UNVR.JK", "MYOR.JK", "KLBF.JK", "AMRT.JK", "CPIN.JK",
    # Telco & Tech
    "TLKM.JK", "ISAT.JK", "EXCL.JK", "GOTO.JK", "BUKA.JK",
    # Infrastructure & Construction
    "JSMR.JK", "PTPP.JK", "ADHI.JK", "WIKA.JK", "WSKT.JK",
    # Others (Auto, Property, etc)
    "ASII.JK", "CTRA.JK", "BSDE.JK", "SMRA.JK", "PWON.JK", "SMGR.JK", "INTP.JK"
]

MIN_AVG_VALUE = 5_000_000_000
MIN_SIDEWAYS_SCORE = 60
MIN_ENTRY_SCORE = 70


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    filename="trading_bot.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("trading_bot")


# ============================================================
# MARKET DATA
# ============================================================

def get_market_data(symbol, period="3y", interval="1d"):
    """
    Mengambil market data 3 tahun terakhir dari Yahoo Finance.
    """

    try:
        df = yf.download(
            symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
        )

        if df.empty:
            raise ValueError(f"No market data for {symbol}")

        # yfinance pada beberapa versi dapat menghasilkan MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })

        required = [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        df = df[required].dropna()
        
        # ==========================================
        # REAL-TIME PATCH VIA TRADINGVIEW (0 DELAY)
        # ==========================================
        try:
            from tradingview_ta import TA_Handler, Interval
            from datetime import datetime
            
            tv_symbol = symbol.replace(".JK", "")
            handler = TA_Handler(
                symbol=tv_symbol,
                screener="indonesia",
                exchange="IDX",
                interval=Interval.INTERVAL_1_DAY
            )
            analysis = handler.get_analysis()
            inds = analysis.indicators
            
            rt_open = float(inds.get("open", df.iloc[-1]['open']))
            rt_high = float(inds.get("high", df.iloc[-1]['high']))
            rt_low = float(inds.get("low", df.iloc[-1]['low']))
            rt_close = float(inds.get("close", df.iloc[-1]['close']))
            rt_volume = float(inds.get("volume", df.iloc[-1]['volume']))
            
            if rt_close > 0:
                today_date = pd.to_datetime(datetime.now().date())
                last_dt = df.index[-1]
                
                if last_dt.date() == today_date.date():
                    # Overwrite bar hari ini dengan data real-time
                    df.loc[last_dt, "open"] = rt_open
                    df.loc[last_dt, "high"] = rt_high
                    df.loc[last_dt, "low"] = rt_low
                    df.loc[last_dt, "close"] = rt_close
                    df.loc[last_dt, "volume"] = rt_volume
                else:
                    # Append bar hari ini karena yfinance belum update harian
                    new_row = pd.DataFrame({
                        "open": [rt_open],
                        "high": [rt_high],
                        "low": [rt_low],
                        "close": [rt_close],
                        "volume": [rt_volume]
                    }, index=[today_date])
                    df = pd.concat([df, new_row])
                    
        except Exception as tv_e:
            logger.warning(f"TradingView real-time patch failed for {symbol}: {tv_e}")

        return df

    except Exception as e:
        logger.error(f"Market data error {symbol}: {e}")
        raise


# ============================================================
# INDICATORS
# ============================================================

def calculate_indicators(df):

    df = df.copy()

    # Moving averages
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma50"] = df["close"].rolling(50).mean()
    df["ma200"] = df["close"].rolling(200).mean()
    df["volume_ma20"] = df["volume"].rolling(20).mean()

    # Daily return
    df["return"] = df["close"].pct_change()

    # Volatility
    df["volatility"] = (
        df["return"]
        .rolling(20)
        .std()
        * np.sqrt(252)
    )

    # RSI 2 (Larry Connors)
    delta2 = df["close"].diff()
    # RSI 2 (Larry Connors) - Wilder's Smoothing for Max Power
    delta2 = df["close"].diff()
    gain2 = delta2.where(delta2 > 0, 0).ewm(alpha=1/2, adjust=False).mean()
    loss2 = (-delta2.where(delta2 < 0, 0)).ewm(alpha=1/2, adjust=False).mean()
    rs2 = gain2 / loss2.replace(0, float('nan'))
    df["rsi_2"] = 100 - (100 / (1 + rs2))
    df["rsi_2"] = df["rsi_2"].fillna(100) # Jika loss 0, RSI = 100
    
    # ATR
    high_low = df["high"] - df["low"]
    high_close = abs(df["high"] - df["close"].shift())
    low_close = abs(df["low"] - df["close"].shift())

    true_range = pd.concat(
        [high_low, high_close, low_close],
        axis=1
    ).max(axis=1)

    df["atr"] = true_range.rolling(14).mean()

    # RSI
    delta = df["close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    df["rsi"] = 100 - (100 / (1 + rs))

    # Volume ratio
    df["avg_volume20"] = df["volume"].rolling(20).mean()

    df["volume_ratio"] = (
        df["volume"] / df["avg_volume20"]
    )

    # Average traded value
    df["traded_value"] = (
        df["close"] * df["volume"]
    )

    df["avg_traded_value20"] = (
        df["traded_value"]
        .rolling(20)
        .mean()
    )

    # Bollinger Band
    df["bb_middle"] = df["close"].rolling(20).mean()

    df["bb_std"] = df["close"].rolling(20).std()

    df["bb_upper"] = (
        df["bb_middle"]
        + 2 * df["bb_std"]
    )

    df["bb_lower"] = (
        df["bb_middle"]
        - 2 * df["bb_std"]
    )

    df["high_20"] = df["high"].rolling(20).max()
    df["bb_width"] = (
        (df["bb_upper"] - df["bb_lower"])
        / df["bb_middle"]
    )

    return df


# ============================================================
# LAYER 1
# UNIVERSE / STOCK CURATION
# ============================================================

def liquidity_score(df):

    latest = df.iloc[-1]

    avg_value = latest["avg_traded_value20"]

    if pd.isna(avg_value):
        return 0

    # Score 0-100
    if avg_value >= 50_000_000_000:
        return 100

    if avg_value >= 25_000_000_000:
        return 90

    if avg_value >= 10_000_000_000:
        return 80

    if avg_value >= 5_000_000_000:
        return 70

    return 30


def activity_score(df):

    latest = df.iloc[-1]

    volume_ratio = latest["volume_ratio"]

    if pd.isna(volume_ratio):
        return 0

    if volume_ratio >= 2:
        return 100

    if volume_ratio >= 1.5:
        return 90

    if volume_ratio >= 1.2:
        return 80

    if volume_ratio >= 1:
        return 70

    return 40


def sideways_score(df):

    latest = df.iloc[-1]

    ma20 = latest["ma20"]
    ma50 = latest["ma50"]
    close = latest["close"]
    bb_width = latest["bb_width"]

    if any(pd.isna(x) for x in [
        ma20,
        ma50,
        close,
        bb_width,
    ]):
        return 0

    # Slope / distance MA
    ma_distance = abs(ma20 - ma50) / close

    score = 100

    # MA terlalu berjauhan → trend lebih kuat
    if ma_distance > 0.10:
        score -= 50

    elif ma_distance > 0.07:
        score -= 35

    elif ma_distance > 0.05:
        score -= 20

    elif ma_distance > 0.03:
        score -= 10

    # Bollinger terlalu lebar → volatility tinggi
    if bb_width > 0.15:
        score -= 25

    elif bb_width > 0.10:
        score -= 15

    elif bb_width > 0.07:
        score -= 5

    return max(0, min(100, score))



def detect_regime(df):
    """
    Mendeteksi Market Regime: BULL, BEAR, atau SIDEWAYS.
    """
    if len(df) < 200 or 'ma200' not in df.columns:
        return "SIDEWAYS" # Default aman
        
    last = df.iloc[-1]
    
    if pd.isna(last['ma200']):
        return "SIDEWAYS"
        
    if last['close'] > last['ma50'] and last['ma50'] > last['ma200']:
        return "BULL"
    elif last['close'] < last['ma50'] and last['ma50'] < last['ma200']:
        return "BEAR"
    else:
        return "SIDEWAYS"


def universe_score(df):

    liquidity = liquidity_score(df)
    activity = activity_score(df)
    sideways = sideways_score(df)

    score = (
        liquidity * 0.40
        + activity * 0.25
        + sideways * 0.35
    )

    return {
        "liquidity": round(liquidity, 2),
        "activity": round(activity, 2),
        "sideways": round(sideways, 2),
        "universe_score": round(score, 2),
    }


# ============================================================
# LAYER 2
# PENETRATION ENGINE
# ============================================================

def calculate_range(df):

    recent = df.tail(20)

    support = recent["low"].min()
    resistance = recent["high"].max()

    return support, resistance






def detect_support_resistance(df, lookback=40):
    """Dynamic support/resistance from price distribution."""
    recent = df.tail(lookback)
    support    = float(recent['low'].quantile(0.15))
    resistance = float(recent['high'].quantile(0.85))
    return support, resistance


def detect_anomaly(df):
    """
    Layer 1: Anomaly Detection.
    Returns (is_anomaly: bool, reason: str).
    Pause new entries when market behaves abnormally.
    """
    if len(df) < 5:
        return False, ""
    last = df.iloc[-1]
    vol_ratio = float(last.get('volume_ratio', 1.0))
    
    if vol_ratio > 4.0:
        return True, f"Volume spike {vol_ratio:.1f}x"
    
    hi = float(last['high']); lo = float(last['low']); cl = float(last['close'])
    if cl > 0 and (hi - lo) / cl > 0.10:
        return True, f"Price range spike {(hi-lo)/cl*100:.1f}%"
    
    if len(df) >= 20 and 'return' in df.columns:
        ret_std = df['return'].tail(20).std()
        last_ret = abs(float(df['return'].iloc[-1]))
        if ret_std > 0 and last_ret / ret_std > 3.5:
            return True, f"Return z-score {last_ret/ret_std:.1f}sigma"
    
    return False, ""


def _score_rsi2(last, prev, regime):
    """RSI-2 Connors Mean Reversion. Max 25."""
    score = 0; reasons = []
    rsi2  = float(last.get('rsi_2', 999))
    close = float(last['close'])
    ma200 = float(last.get('ma200', 0))
    if pd.isna(rsi2) or rsi2 == 999:
        return 0, []
    if rsi2 < 5 and close > ma200 > 0:
        score += 20; reasons.append(f"RSI(2)={rsi2:.1f} extreme oversold in uptrend")
    elif rsi2 < 10 and close > ma200 > 0:
        score += 12; reasons.append(f"RSI(2)={rsi2:.1f} oversold")
    prev_rsi2 = float(prev.get('rsi_2', rsi2))
    if score > 0 and rsi2 > prev_rsi2:
        score += 5; reasons.append("RSI(2) recovering")
    if regime == "BULL":
        score = int(score * 1.2)
    return min(score, 25), reasons


def _score_trend(last, df):
    """Trend Following: MA alignment. Max 20."""
    score = 0; reasons = []
    close = float(last['close'])
    ma20  = float(last.get('ma20', 0))
    ma50  = float(last.get('ma50', 0))
    ma200 = float(last.get('ma200', 0))
    if close > ma20 > ma50 > ma200 > 0:
        score += 20; reasons.append("Full MA alignment (20>50>200)")
    elif close > ma50 > ma200 > 0:
        score += 12; reasons.append("Partial trend alignment")
    elif close > ma200 > 0:
        score += 6;  reasons.append("Price above MA200")
    return min(score, 20), reasons


def _score_breakout(last, prev, df):
    """Breakout Momentum: New 20D high + volume. Max 20."""
    score = 0; reasons = []
    close    = float(last['close'])
    high20   = float(last.get('high_20', float(last['high'])))
    vol_ratio = float(last.get('volume_ratio', 1.0))
    if close > high20:
        score += 12; reasons.append(f"20D Breakout")
        if vol_ratio > 1.5:
            score += 8; reasons.append(f"Vol confirmed {vol_ratio:.1f}x")
        elif vol_ratio > 1.2:
            score += 4
    return min(score, 20), reasons


def _score_bollinger(last, regime):
    """Bollinger Mean Reversion: Buy near lower band. Max 20."""
    score = 0; reasons = []
    close    = float(last['close'])
    bb_lower = float(last.get('bb_lower', close))
    bb_mid   = float(last.get('bb_middle', close))
    rsi      = float(last.get('rsi', 50))
    if regime == "SIDEWAYS":
        if close <= bb_lower * 1.01 and rsi < 35:
            score += 20; reasons.append(f"BB lower touch RSI={rsi:.0f}")
        elif close <= bb_mid * 0.98 and rsi < 45:
            score += 10; reasons.append("Below BB middle")
    elif regime == "BULL" and close <= bb_lower * 1.02:
        score += 10; reasons.append("BB lower dip-buy (bull)")
    return min(score, 20), reasons


def _score_volume(last, prev):
    """Volume Intelligence: price-volume alignment. Max 15, can be negative."""
    score = 0; reasons = []
    vol_ratio  = float(last.get('volume_ratio', 1.0))
    price_up   = float(last['close']) > float(prev['close'])
    if price_up and vol_ratio > 1.5:
        score += 15; reasons.append(f"Price up + Volume {vol_ratio:.1f}x")
    elif price_up and vol_ratio > 1.2:
        score += 8;  reasons.append(f"Volume {vol_ratio:.1f}x")
    elif not price_up and vol_ratio > 2.0:
        score -= 5;  reasons.append(f"WARNING: Price down + Volume {vol_ratio:.1f}x")
    else:
        score += 3
    return score, reasons


def signal_engine(df):
    """
    IDXBot Multi-Layer Decision System v2
    ======================================
    Layer 1: Anomaly Detection
    Layer 2: No-Trade Filters (liquidity, penny, volatility)
    Layer 3: Market Regime (BULL/SIDEWAYS/BEAR)
    Layer 4: Strategy Ensemble (5 strategies)
    Layer 5: Score Aggregation + Signal Bucket

    Score buckets:
      0-49  → WAIT
      50-64 → WATCH
      65-79 → SETUP
      80+   → ENTRY CANDIDATE
    """
    _base = {
        "signal": "WAIT", "reason": "Insufficient data",
        "total_score": 0, "score_breakdown": {},
        "regime": "UNKNOWN", "strategy": "—",
        "entry_score": 0, "support": 0, "resistance": 0,
    }

    if len(df) < 60:
        return _base

    last   = df.iloc[-1]
    prev   = df.iloc[-2]
    support, resistance = detect_support_resistance(df)

    def _ret(signal, reason, score=0, regime="UNKNOWN", strategy="—", bd={}):
        return {
            "signal": signal, "reason": reason,
            "total_score": score, "score_breakdown": bd,
            "regime": regime, "strategy": strategy,
            "entry_score": score, "support": support, "resistance": resistance,
        }

    # ── Layer 1: Anomaly ────────────────────────────────────
    is_anomaly, anomaly_msg = detect_anomaly(df)
    if is_anomaly:
        return _ret("WAIT", f"ANOMALY DETECTED: {anomaly_msg}", regime="ANOMALY")

    # ── Layer 2: No-Trade Filters ───────────────────────────
    traded_val = float(last['close']) * float(last['volume'])
    if traded_val < MIN_AVG_VALUE:
        return _ret("WAIT", "Illiquid stock — skipped")
    if float(last['close']) < 100:
        return _ret("WAIT", "Penny stock (<Rp100)")
    if 'volatility' in last.index and not pd.isna(last['volatility']) and float(last['volatility']) > 1.0:
        return _ret("WAIT", "Extreme volatility >100% annual")

    # ── Layer 3: Market Regime ──────────────────────────────
    regime = detect_regime(df)
    if regime == "BEAR":
        return _ret("WAIT", "Bear market — defensive mode", regime=regime)

    # ── Layer 4: Strategy Ensemble ──────────────────────────
    bd = {}
    all_reasons = [f"Regime: {regime}"]

    bd["regime"]    = 15 if regime == "BULL" else 8
    bd["liquidity"] = 8 if traded_val > MIN_AVG_VALUE * 3 else 5

    s1, r1 = _score_rsi2(last, prev, regime)
    s2, r2 = _score_trend(last, df)
    s3, r3 = _score_breakout(last, prev, df)
    s4, r4 = _score_bollinger(last, regime)
    s5, r5 = _score_volume(last, prev)

    bd["rsi_2"]          = s1
    bd["trend"]          = s2
    bd["breakout"]       = s3
    bd["mean_reversion"] = s4
    bd["volume"]         = s5

    # Support proximity bonus
    close_px = float(last['close'])
    bd["support_proximity"] = 7 if support > 0 and abs(close_px - support) / close_px < 0.03 else 0

    all_reasons.extend([r for rs in [r1,r2,r3,r4,r5] for r in rs])

    total_score = max(0, min(100, sum(bd.values())))

    strat_scores = {
        "RSI-2 Mean Reversion":  s1,
        "Trend Following":       s2,
        "Breakout Momentum":     s3,
        "Bollinger Reversion":   s4,
        "Volume/Price Momentum": s5,
    }
    dominant = max(strat_scores, key=strat_scores.get)

    # ── Layer 5: Signal Bucket ──────────────────────────────
    if total_score >= 80:
        bucket = "ENTRY CANDIDATE"
    elif total_score >= 65:
        bucket = "SETUP"
    elif total_score >= 50:
        bucket = "WATCH"
    else:
        bucket = "WAIT"

    return {
        "signal":          bucket,
        "reason":          " | ".join(all_reasons[:5]),
        "total_score":     total_score,
        "score_breakdown": bd,
        "regime":          regime,
        "strategy":        dominant,
        "entry_score":     total_score,
        "support":         support,
        "resistance":      resistance,
    }



def penetration_engine(df):
    return signal_engine(df) # Redirect old calls

# def OLD_penetration_engine(df):

    latest = df.iloc[-1]

    price = latest["close"]
    rsi = latest["rsi"]
    volume_ratio = latest["volume_ratio"]
    atr = latest["atr"]

    support, resistance = calculate_range(df)

    if pd.isna(rsi) or pd.isna(volume_ratio):
        return {
            "entry_score": 0,
            "signal": "INSUFFICIENT DATA",
            "support": support,
            "resistance": resistance,
        }

    range_size = resistance - support

    if range_size <= 0:
        return {
            "entry_score": 0,
            "signal": "NO RANGE",
            "support": support,
            "resistance": resistance,
        }

    # Posisi harga dalam range
    range_position = (
        price - support
    ) / range_size

    score = 0

    # --------------------------------------------------------
    # A. Near support
    # --------------------------------------------------------

    if range_position <= 0.20:
        score += 30

    elif range_position <= 0.30:
        score += 20

    elif range_position <= 0.40:
        score += 10

    # --------------------------------------------------------
    # B. RSI
    # --------------------------------------------------------

    if rsi <= 35:
        score += 25

    elif rsi <= 45:
        score += 15

    elif rsi <= 55:
        score += 10

    # --------------------------------------------------------
    # C. Volume
    # --------------------------------------------------------

    if volume_ratio >= 1.5:
        score += 25

    elif volume_ratio >= 1.2:
        score += 15

    elif volume_ratio >= 1:
        score += 10

    # --------------------------------------------------------
    # D. ATR / volatility
    # --------------------------------------------------------

    if price > 0 and not pd.isna(atr):

        atr_pct = atr / price

        if 0.01 <= atr_pct <= 0.05:
            score += 20

        elif atr_pct <= 0.07:
            score += 10

    score = min(score, 100)

    # --------------------------------------------------------
    # Signal
    # --------------------------------------------------------

    if score >= 80:
        signal = "ENTRY CANDIDATE"

    elif score >= 60:
        signal = "PREPARE"

    elif score >= 40:
        signal = "WATCH"

    else:
        signal = "IGNORE"

    return {
        "entry_score": score,
        "signal": signal,
        "support": support,
        "resistance": resistance,
        "range_position": range_position,
    }


# ============================================================
# UNIFIED DECISION ENGINE
# ============================================================
# This is the SINGLE source of truth for trading decisions.
# signal_engine() + risk sizing + hard filters → one output.
# dashboard.py calls make_decision(), never risk_check() alone.

# Signal state labels
SIGNAL_AVOID  = "🔴 AVOID"     # score < 40 or hard filter failed
SIGNAL_WAIT   = "🟡 WAIT"      # score 40-64
SIGNAL_SETUP  = "🔵 SETUP"     # score 65-79
SIGNAL_BUY    = "🟢 BUY"       # score ≥ 80 + all filters pass

def risk_check(df, capital=INITIAL_CAPITAL, risk_per_trade=0.01):
    """
    Legacy wrapper — kept for backward compatibility.
    Returns minimal risk sizing info without signal validation.
    New code should call make_decision() instead.
    """
    latest = df.iloc[-1]
    price  = float(latest["close"])
    atr    = float(latest["atr"]) if not pd.isna(latest.get("atr", float('nan'))) else 0

    import sqlite3, os
    open_positions, invested_capital = 0, 0
    try:
        if os.path.exists('data/paper.db'):
            with sqlite3.connect('data/paper.db') as conn:
                rows = conn.execute("SELECT cost FROM positions").fetchall()
                open_positions   = len(rows)
                invested_capital = sum(float(r[0]) for r in rows if r[0])
    except:
        pass

    if open_positions >= 5:
        return {"approved": False, "reason": "MAX POSITIONS (5) HIT", "lots": 0}
    if invested_capital >= capital * 0.6:
        return {"approved": False, "reason": "MAX EXPOSURE (60%) HIT", "lots": 0}
    if atr <= 0 or price <= 0:
        return {"approved": False, "reason": "Invalid ATR/price", "lots": 0}

    stop_dist   = atr * 1.5
    risk_amount = capital * risk_per_trade
    lots        = max(0, int(risk_amount / stop_dist) // 100)

    if lots <= 0:
        return {"approved": False, "reason": "Position too small", "lots": 0}

    stop_loss   = price - stop_dist
    take_profit = price + stop_dist * 2
    rr          = round((take_profit - price) / (price - stop_loss), 2) if (price - stop_loss) > 0 else 0

    return {
        "approved":    True,
        "reason":      f"R:R {rr:.1f}x",
        "lots":        lots,
        "entry":       price,
        "stop_loss":   stop_loss,
        "take_profit": take_profit,
        "rr":          rr,
        "quantity":    lots * 100,
    }


def make_decision(df, capital=INITIAL_CAPITAL, risk_per_trade=0.01):
    """
    Unified Decision Pipeline — SINGLE SOURCE OF TRUTH.

    Flow:
      signal_engine() → score → hard filters → position sizing → decision

    Returns a unified dict:
      state          : AVOID / WAIT / SETUP / BUY
      signal_label   : emoji + label string
      approved       : bool (True only for BUY)
      total_score    : 0-100
      score_breakdown: dict of component scores
      hard_filters   : list of {name, pass, reason}
      regime         : BULL / SIDEWAYS / BEAR
      strategy       : dominant strategy name
      reasons_pass   : list of conditions met
      reasons_fail   : list of conditions not met
      why_not        : human-readable explanation of blockers
      entry / stop_loss / take_profit / lots / rr
      support / resistance
    """
    # ── Step 1: Run signal engine ──────────────────────────
    sig = signal_engine(df)
    score    = sig.get("total_score", 0)
    regime   = sig.get("regime", "UNKNOWN")
    strategy = sig.get("strategy", "—")
    bd       = sig.get("score_breakdown", {})
    support  = sig.get("support", 0)
    resistance = sig.get("resistance", 0)

    latest = df.iloc[-1]
    price  = float(latest["close"])
    atr    = float(latest.get("atr", 0)) if not pd.isna(latest.get("atr", float('nan'))) else 0
    rsi2   = float(latest.get("rsi_2", 50)) if not pd.isna(latest.get("rsi_2", float('nan'))) else 50
    ma200  = float(latest.get("ma200", 0)) if "ma200" in latest.index and not pd.isna(latest["ma200"]) else 0
    vol_r  = float(latest.get("volume_ratio", 1.0)) if "volume_ratio" in latest.index else 1.0

    # ── Step 2: Position sizing ────────────────────────────
    stop_dist   = atr * 1.5 if atr > 0 else price * 0.03
    risk_amount = capital * risk_per_trade
    lots        = max(0, int(risk_amount / stop_dist) // 100) if stop_dist > 0 else 0
    stop_loss   = price - stop_dist
    take_profit = price + stop_dist * 2.0
    rr          = round((take_profit - price) / max(price - stop_loss, 1), 2)

    # ── Step 3: Hard filters (must ALL pass for BUY) ───────
    import sqlite3, os
    open_pos, invested = 0, 0.0
    try:
        if os.path.exists('data/paper.db'):
            with sqlite3.connect('data/paper.db') as conn:
                rows = conn.execute("SELECT cost FROM positions").fetchall()
                open_pos  = len(rows)
                invested  = sum(float(r[0]) for r in rows if r[0])
    except:
        pass

    hard_filters = [
        {
            "name":   "Market Regime ≠ BEAR",
            "pass":   regime in ("BULL", "SIDEWAYS"),
            "reason": f"Regime = {regime}"
        },
        {
            "name":   "Signal Score ≥ 80",
            "pass":   score >= 80,
            "reason": f"Score = {score}/100"
        },
        {
            "name":   "Max Positions (5)",
            "pass":   open_pos < 5,
            "reason": f"Open = {open_pos}/5"
        },
        {
            "name":   "Max Exposure (60%)",
            "pass":   invested < capital * 0.6,
            "reason": f"Invested = {invested/capital*100:.0f}%"
        },
        {
            "name":   "Liquidity OK",
            "pass":   float(latest["close"]) * float(latest["volume"]) >= MIN_AVG_VALUE,
            "reason": "Traded value below threshold"
        },
        {
            "name":   "ATR Valid",
            "pass":   atr > 0 and lots > 0,
            "reason": "Cannot size position"
        },
        {
            "name":   "R:R ≥ 1.5x",
            "pass":   rr >= 1.5,
            "reason": f"R:R = {rr:.1f}x"
        },
    ]

    all_pass    = all(f["pass"] for f in hard_filters)
    fails       = [f for f in hard_filters if not f["pass"]]
    passes      = [f for f in hard_filters if f["pass"]]

    # Why conditions
    reasons_pass = []
    reasons_fail = []

    indicator_checks = [
        ("RSI(2) oversold",    rsi2 < 10),
        ("Price > MA200",      price > ma200 > 0),
        ("Volume confirmed",   vol_r > 1.2),
        ("Near support",       support > 0 and abs(price - support) / price < 0.03),
        ("Regime bullish",     regime == "BULL"),
        ("Score ≥ 80",         score >= 80),
        ("Positions < 5",      open_pos < 5),
        ("R:R ≥ 1.5x",         rr >= 1.5),
    ]
    for label, cond in indicator_checks:
        if cond:
            reasons_pass.append(label)
        else:
            reasons_fail.append(label)

    # ── Step 4: Determine final state ──────────────────────
    if not all_pass:
        # Which blocker is most important?
        blocker = fails[0]["reason"] if fails else "Multiple filters failed"
        if score < 40:
            state = "AVOID"
            label = SIGNAL_AVOID
        else:
            state = "WAIT"
            label = SIGNAL_WAIT
        why_not = f"Blocked by: {', '.join(f['reason'] for f in fails[:3])}"
        approved = False
    elif score >= 80:
        state    = "BUY"
        label    = SIGNAL_BUY
        why_not  = ""
        approved = True
    elif score >= 65:
        state    = "SETUP"
        label    = SIGNAL_SETUP
        why_not  = f"Score {score}/100 — needs 80+ for entry"
        approved = False
    else:
        state    = "WAIT"
        label    = SIGNAL_WAIT
        why_not  = f"Score {score}/100 — needs 80+ for entry"
        approved = False

    return {
        # Decision
        "state":         state,
        "signal_label":  label,
        "approved":      approved,
        # Scores
        "total_score":      score,
        "score_breakdown":  bd,
        # Context
        "regime":        regime,
        "strategy":      strategy,
        "support":       support,
        "resistance":    resistance,
        # Filters
        "hard_filters":  hard_filters,
        "reasons_pass":  reasons_pass,
        "reasons_fail":  reasons_fail,
        "why_not":       why_not,
        # Trade plan
        "entry":         price,
        "stop_loss":     stop_loss,
        "take_profit":   take_profit,
        "lots":          lots,
        "rr":            rr,
    }


# ============================================================
# EXECUTION ADAPTER
# ============================================================

class ExecutionAdapter:

    def __init__(self):

        self.status = "NOT_CONNECTED"

    def buy(
        self,
        symbol,
        quantity,
        price,
    ):

        """
        TEMPORARY INTERFACE.

        Jangan memasukkan username/password/PIN Stockbit
        ke sini.

        Fungsi ini sengaja belum mengirim order ke broker.
        Ketika API/interface resmi tersedia, adapter ini
        yang diganti.
        """

        logger.info(
            f"ORDER REQUEST | BUY | "
            f"{symbol} | {quantity} | {price}"
        )

        return {
            "status": "PENDING_EXECUTION_ADAPTER",
            "symbol": symbol,
            "side": "BUY",
            "quantity": quantity,
            "price": price,
        }

    def sell(
        self,
        symbol,
        quantity,
        price,
    ):

        logger.info(
            f"ORDER REQUEST | SELL | "
            f"{symbol} | {quantity} | {price}"
        )

        return {
            "status": "PENDING_EXECUTION_ADAPTER",
            "symbol": symbol,
            "side": "SELL",
            "quantity": quantity,
            "price": price,
        }


# ============================================================
# SCANNER
# ============================================================

def scan_universe():
    import concurrent.futures

    results = []
    errors = []

    def process_symbol(symbol):
        try:
            df = get_market_data(symbol)
            df = calculate_indicators(df)
            universe = universe_score(df)
            penetration = penetration_engine(df)
            latest = df.iloc[-1]

            return {
                "symbol": symbol.replace(".JK", ""),
                "price": latest["close"],
                "liquidity": universe["liquidity"],
                "activity": universe["activity"],
                "sideways": universe["sideways"],
                "universe_score": universe["universe_score"],
                "entry_score": penetration["entry_score"],
                "signal": penetration["signal"],
                "support": penetration["support"],
                "resistance": penetration["resistance"],
                "rsi": latest["rsi"],
                "volume_ratio": latest["volume_ratio"],
            }, None
        except Exception as e:
            logger.error(f"{symbol}: {traceback.format_exc()}")
            return None, f"{symbol}: {str(e)}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_symbol, sym): sym for sym in UNIVERSE}
        for future in concurrent.futures.as_completed(futures):
            res, err = future.result()
            if res:
                results.append(res)
            if err:
                errors.append(err)

    return pd.DataFrame(results), errors





def run_historical_backtest():
    import pandas as pd
    import numpy as np
    from datetime import datetime
    
    historical_data = {}
    for sym in UNIVERSE:
        try:
            df = get_market_data(sym, period='3y')
            df = calculate_indicators(df)
            historical_data[sym] = df
        except Exception as e:
            pass
            
    if not historical_data:
        return None

    all_dates = pd.to_datetime([])
    for df in historical_data.values():
        all_dates = all_dates.union(df.index)
    all_dates = all_dates.sort_values()

    capital = INITIAL_CAPITAL
    cash = capital
    positions = {}
    trade_history = []
    equity_curve = []

    for current_date in all_dates:
        daily_equity = cash
        
        symbols_to_sell = []
        for sym, pos in list(positions.items()):
            df = historical_data.get(sym)
            if df is None or current_date not in df.index:
                daily_equity += pos['cost']
                continue
                
            current_price = df.loc[current_date, 'close']
            daily_equity += current_price * pos['shares']
            
            # EXIT LOGIC (Advanced)
            ma5 = df.loc[current_date, 'ma5']
            if current_price <= pos['stop']:
                symbols_to_sell.append((sym, "STOP LOSS", current_price))
            elif current_price >= pos['tp']:
                symbols_to_sell.append((sym, "TAKE PROFIT", current_price))
            elif current_price > ma5:
                symbols_to_sell.append((sym, "DYNAMIC EXIT (MA5)", current_price))

        for sym, reason, price in symbols_to_sell:
            pos = positions[sym]
            gross_value = price * pos['shares']
            net_receive = gross_value - (gross_value * 0.0025)
            pnl = net_receive - pos['cost']
            cash += net_receive
            daily_equity += pnl
            
            holding_days = (current_date - pos['entry_date']).days
            trade_history.append({'date': current_date, 'symbol': sym, 'type': 'SELL', 'pnl': pnl, 'holding_days': holding_days, 'reason': reason})
            del positions[sym]

        for sym in UNIVERSE:
            if sym in positions:
                continue
            df = historical_data.get(sym)
            if df is None or current_date not in df.index:
                continue
                
            df_up_to_today = df.loc[:current_date]
            if len(df_up_to_today) < 20:
                continue
                
            penetration = penetration_engine(df_up_to_today)
            if penetration['signal'] == 'ENTRY CANDIDATE':
                risk = risk_check(df_up_to_today, capital=capital)
                if risk['approved']:
                    shares = int(risk['lots'] * 100)
                    entry_price = float(risk['entry'])
                    total_cost = (shares * entry_price) * 1.0015
                    
                    if cash >= total_cost:
                        cash -= total_cost
                        sl = float(risk['stop_loss'])
                        tp = entry_price + ((entry_price - sl) * 2)
                        positions[sym] = {'shares': shares, 'entry': entry_price, 'stop': sl, 'tp': tp, 'cost': total_cost, 'entry_date': current_date}
                        trade_history.append({'date': current_date, 'symbol': sym, 'type': 'BUY', 'pnl': 0, 'holding_days': 0, 'reason': 'ENTRY'})
                        
        equity_curve.append({'date': current_date, 'equity': daily_equity})

    trades_df = pd.DataFrame(trade_history)
    equity_df = pd.DataFrame(equity_curve)
    
    if trades_df.empty:
        return None
        
    final_equity = equity_df.iloc[-1]['equity']
    total_return = ((final_equity - capital) / capital) * 100
    
    sells = trades_df[trades_df['type'] == 'SELL']
    total_closed = len(sells)
    win_trades = len(sells[sells['pnl'] > 0])
    win_rate = (win_trades / total_closed * 100) if total_closed > 0 else 0
    net_profit = final_equity - capital
    
    # Advanced Metrics
    gross_profit = sells[sells['pnl'] > 0]['pnl'].sum() if total_closed > 0 else 0
    gross_loss = abs(sells[sells['pnl'] < 0]['pnl'].sum()) if total_closed > 0 else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.99 if gross_profit > 0 else 0)
    
    avg_holding = sells['holding_days'].mean() if total_closed > 0 else 0
    expectancy = (sells['pnl'].mean() / capital * 100) if total_closed > 0 else 0
    
    # Max Drawdown
    equity_df['peak'] = equity_df['equity'].cummax()
    equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak'] * 100
    max_dd = equity_df['drawdown'].min()
    
    # Sharpe Ratio (Rough approximation: daily returns)
    eq_returns = equity_df['equity'].pct_change().dropna()
    sharpe = (eq_returns.mean() / eq_returns.std() * np.sqrt(252)) if eq_returns.std() > 0 else 0
    
    return {
        'capital': capital,
        'final_equity': final_equity,
        'net_profit': net_profit,
        'total_return': total_return,
        'total_trades': total_closed,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'expectancy': expectancy,
        'max_dd': max_dd,
        'sharpe': sharpe,
        'avg_holding': avg_holding,
        'equity_df': equity_df,
        'trades_df': trades_df
    }
