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
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma50"] = df["close"].rolling(50).mean()

    # Daily return
    df["return"] = df["close"].pct_change()

    # Volatility
    df["volatility"] = (
        df["return"]
        .rolling(20)
        .std()
        * np.sqrt(252)
    )

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


def penetration_engine(df):

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
# RISK ENGINE
# ============================================================

def risk_check(
    df,
    capital=INITIAL_CAPITAL,
    risk_per_trade=0.01,
):

    latest = df.iloc[-1]

    price = latest["close"]
    atr = latest["atr"]

    if pd.isna(atr) or price <= 0:

        return {
            "approved": False,
            "reason": "Invalid ATR/price",
            "quantity": 0,
        }

    # Stop loss berbasis ATR
    stop_distance = atr * 1.5

    if stop_distance <= 0:
        return {
            "approved": False,
            "reason": "Stop distance is zero (No volatility)",
            "quantity": 0,
        }

    risk_amount = (
        capital * risk_per_trade
    )

    quantity = int(
        risk_amount / stop_distance
    )

    # Saham Indonesia diperdagangkan dalam lot
    lots = quantity // 100

    if lots <= 0:

        return {
            "approved": False,
            "reason": "Position too small",
            "quantity": 0,
        }

    shares = lots * 100

    estimated_value = shares * price

    if estimated_value > capital:

        return {
            "approved": False,
            "reason": "Insufficient capital",
            "quantity": 0,
        }

    stop_loss = price - stop_distance

    take_profit = price + (
        stop_distance * 2
    )

    return {
        "approved": True,
        "reason": "Risk approved",
        "quantity": shares,
        "lots": lots,
        "entry": price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "estimated_value": estimated_value,
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


