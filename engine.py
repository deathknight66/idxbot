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





def signal_engine(df):
    """
    IDXBot Multi-Strategy Scoring Engine
    Menggabungkan 5 sub-strategi (RSI-2, Trend, Breakout, Mean Reversion, Volume).
    """
    if len(df) < 200:
        return {"signal": "WAIT", "reason": "Data tidak cukup (butuh 200 baris)", "entry_score": 0, "support": 0, "resistance": 0}

    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 1. NO-TRADE ENGINE
    if last['volume'] * last['close'] < MIN_AVG_VALUE:
        return {"signal": "WAIT", "reason": "No-Trade: Low Liquidity", "entry_score": 0, "support": last['bb_lower'], "resistance": last['bb_upper']}
    if last['close'] < 50:
        return {"signal": "WAIT", "reason": "No-Trade: Penny Stock", "entry_score": 0, "support": last['bb_lower'], "resistance": last['bb_upper']}
    if last['volatility'] > 1.0: # Volatilitas tahunan ekstrim (>100%)
        return {"signal": "WAIT", "reason": "No-Trade: Extreme Volatility", "entry_score": 0, "support": last['bb_lower'], "resistance": last['bb_upper']}

    # 2. MARKET REGIME ENGINE
    regime = detect_regime(df)
    if regime == "BEAR":
        # Di pasar turun, NO TRADE adalah keputusan terbaik
        return {"signal": "WAIT", "reason": "No-Trade: Bear Market (Defensive/Cash)", "entry_score": 0, "support": last['bb_lower'], "resistance": last['bb_upper']}

    # 3. STRATEGY SCORING ENGINE
    scores = {
        "trend": 0,
        "rsi_2": 0,
        "volume": 0,
        "breakout": 0,
        "mean_reversion": 0,
        "regime": 20 if regime == "BULL" else 10 if regime == "SIDEWAYS" else 0,
        "liquidity": 10 if last['volume'] * last['close'] > MIN_AVG_VALUE * 2 else 5
    }
    
    reasons = [f"Regime: {regime}"]

    # Strat 1: Connors RSI-2 (Buy oversold pullback in uptrend)
    if last['close'] > last['ma200'] and last['rsi_2'] < 10:
        scores["rsi_2"] += 25
        reasons.append("RSI-2 Pullback")
        
    # Strat 2: Trend Following (Strong momentum)
    if last['ma20'] > last['ma50'] > last['ma200'] and last['close'] > last['ma20']:
        scores["trend"] += 20
        reasons.append("Strong Trend")
        
    # Strat 3: Breakout Momentum (New Highs)
    if last['close'] > prev['high_20']:
        scores["breakout"] += 15
        reasons.append("20D Breakout")
        
    # Strat 4: Bollinger Mean Reversion (Buy at Support)
    if regime == "SIDEWAYS" and last['close'] < last['bb_lower'] and last['rsi'] < 35:
        scores["mean_reversion"] += 25
        reasons.append("BB Mean Reversion")
        
    # Strat 5: Volume Confirmation (Smart money)
    if last['volume'] > last['volume_ma20'] * 1.5:
        scores["volume"] += 15
        reasons.append("High Volume")

    total_score = sum(scores.values())
    
    if total_score >= 80:
        return {
            "signal": "ENTRY CANDIDATE", 
            "reason": " + ".join(reasons), 
            "entry_score": total_score, 
            "support": last["bb_lower"], 
            "resistance": last["bb_upper"]
        }
    else:
        return {
            "signal": "WAIT", 
            "reason": f"Score {total_score}/100. Need >= 80", 
            "entry_score": total_score, 
            "support": last["bb_lower"], 
            "resistance": last["bb_upper"]
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

    import sqlite3
    import os
    open_positions = 0
    invested_capital = 0
    try:
        if os.path.exists('data/paper.db'):
            with sqlite3.connect('data/paper.db') as conn:
                positions = conn.execute("SELECT cost FROM positions").fetchall()
                open_positions = len(positions)
                invested_capital = sum([p[0] for p in positions])
    except:
        pass

    if open_positions >= 5:
        return {"approved": False, "reason": "MAX POSITIONS (5) HIT"}
        
    if invested_capital >= (capital * 0.6):
        return {"approved": False, "reason": "MAX EXPOSURE (60%) HIT"}

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
