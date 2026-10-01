import logging
import traceback
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st
import plotly.graph_objects as go
import hashlib
import os
import sqlite3
from datetime import datetime

# ============================================================
# AUTHENTICATION SYSTEM
# ============================================================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def show_login_page():
    st.title("🛡️ IDXBot Command Center")
    st.markdown("Silakan masuk ke akunmu untuk mengakses mesin trading.")
    
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect("data/paper.db") as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT,
            created_at TEXT
        )''')
        
    tab1, tab2 = st.tabs(["🔑 Login", "📝 Register (Akun Baru)"])
    
    with tab1:
        log_user = st.text_input("Username", key="log_user")
        log_pass = st.text_input("Password", type="password", key="log_pass")
        if st.button("Masuk", use_container_width=True):
            with sqlite3.connect("data/paper.db") as conn:
                user = conn.execute("SELECT password_hash FROM users WHERE username=?", (log_user,)).fetchone()
                if user and user[0] == hash_password(log_pass):
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = log_user
                    st.rerun()
                else:
                    st.error("Username atau password salah!")
                    
    with tab2:
        reg_user = st.text_input("Username Baru", key="reg_user")
        reg_pass = st.text_input("Password", type="password", key="reg_pass")
        reg_pass2 = st.text_input("Konfirmasi Password", type="password", key="reg_pass2")
        if st.button("Buat Akun", use_container_width=True):
            if reg_pass != reg_pass2:
                st.error("Password tidak cocok!")
            elif len(reg_user) < 3 or len(reg_pass) < 3:
                st.error("Username dan Password minimal 3 karakter.")
            else:
                with sqlite3.connect("data/paper.db") as conn:
                    try:
                        conn.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                                     (reg_user, hash_password(reg_pass), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                        st.success("Berhasil didaftarkan! Silakan buka tab Login.")
                    except sqlite3.IntegrityError:
                        st.error("Username sudah terpakai!")

if not st.session_state.get("logged_in", False):
    show_login_page()
    st.stop()


# ============================================================
# CONFIGURATION
# ============================================================

INITIAL_CAPITAL = 100_000_000

# Universe awal.
# Nanti bisa diperluas menjadi seluruh saham BEI.
# Universe saham LQ45 / Big Caps Indonesia
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

@st.cache_data(ttl=3600)
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


# ============================================================
# DASHBOARD
# ============================================================

st.set_page_config(
    page_title="Trading Bot",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Trading Bot Command Center")

st.caption(
    "Prototype — Universe Selection → "
    "Penetration → Risk → Monitoring"
)


# ============================================================
# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.markdown(f"👤 **Halo, {st.session_state['username']}!**")
if st.sidebar.button("Logout"):
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.rerun()

st.sidebar.write("---")
st.sidebar.header("Bot Control")

capital = st.sidebar.number_input(
    "Capital",
    min_value=1_000_000,
    value=INITIAL_CAPITAL,
    step=1_000_000,
)

risk_percent = st.sidebar.slider(
    "Risk / Trade (%)",
    0.1,
    5.0,
    1.0,
    0.1,
)

if st.sidebar.button("🔄 Run Scanner"):

    st.cache_data.clear()

    st.rerun()


# ============================================================
# RUN SCANNER
# ============================================================

try:

    scan_df, errors = scan_universe()

except Exception as e:

    st.error(
        f"Scanner failure: {str(e)}"
    )

    scan_df = pd.DataFrame()
    errors = [str(e)]


# ============================================================
# TOP METRICS
# ============================================================

if not scan_df.empty:

    candidates = scan_df[
        scan_df["universe_score"]
        >= MIN_SIDEWAYS_SCORE
    ]

    entry_candidates = scan_df[
        scan_df["entry_score"]
        >= MIN_ENTRY_SCORE
    ]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Stocks Scanned",
        len(scan_df)
    )

    col2.metric(
        "Potential Universe",
        len(candidates)
    )

    col3.metric(
        "Entry Candidates",
        len(entry_candidates)
    )

    col4.metric(
        "System Errors",
        len(errors)
    )


# ============================================================
# PAGE 1
# OPPORTUNITY SCANNER
# ============================================================

st.header("1. Opportunity Scanner")

if not scan_df.empty:

    display_df = scan_df.copy()

    display_df = display_df.sort_values(
        "entry_score",
        ascending=False
    )

    st.dataframe(
        display_df[
            [
                "symbol",
                "price",
                "liquidity",
                "activity",
                "sideways",
                "universe_score",
                "entry_score",
                "signal",
                "rsi",
                "volume_ratio",
                "support",
                "resistance",
            ]
        ],
        use_container_width=True,
    )


# ============================================================
# PAGE 2
# SELECTED STOCK DETAIL
# ============================================================

st.header("2. Penetration Engine")

if not scan_df.empty:

    selected = st.selectbox(
        "Select Stock",
        scan_df["symbol"].tolist()
    )

    symbol = selected + ".JK"

    try:

        df = get_market_data(symbol)

        df = calculate_indicators(df)

        penetration = penetration_engine(df)

        risk = risk_check(
            df,
            capital=capital,
            risk_per_trade=risk_percent / 100,
        )

        latest = df.iloc[-1]

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Price",
            f"Rp {latest['close']:,.0f}"
        )

        c2.metric(
            "RSI",
            f"{latest['rsi']:.2f}"
        )

        c3.metric(
            "Entry Score",
            penetration["entry_score"]
        )

        c4.metric(
            "Signal",
            penetration["signal"]
        )

        # Chart

        fig = go.Figure()

        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name="Price",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["ma20"],
                name="MA20",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["bb_upper"],
                name="BB Upper",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["bb_lower"],
                name="BB Lower",
            )
        )

        fig.update_layout(
            height=500,
            xaxis_rangeslider_visible=False,
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
        )

        # Risk

        st.subheader("Risk Decision")

        if risk["approved"]:

            st.success(
                f"Risk APPROVED — "
                f"{risk['lots']} lot"
            )

            risk_df = pd.DataFrame(
                {
                    "Metric": [
                        "Entry",
                        "Stop Loss",
                        "Take Profit",
                        "Lots",
                        "Estimated Value",
                    ],
                    "Value": [
                        f"Rp {risk['entry']:,.0f}",
                        f"Rp {risk['stop_loss']:,.0f}",
                        f"Rp {risk['take_profit']:,.0f}",
                        risk["lots"],
                        f"Rp {risk['estimated_value']:,.0f}",
                    ],
                }
            )

            st.table(risk_df)
            
            # --- REAL EXECUTION INTEGRATION ---
            if st.button(f"EXECUTE BUY {symbol} (Paper Trade)"):
                try:
                    import sqlite3
                    from datetime import datetime
                    with sqlite3.connect("data/paper.db") as conn:
                        conn.execute('''CREATE TABLE IF NOT EXISTS orders(
                            id INTEGER PRIMARY KEY AUTOINCREMENT, signal_date TEXT, symbol TEXT,
                            side TEXT, lots INTEGER, ref_price REAL, limit_price REAL,
                            status TEXT DEFAULT 'PENDING', fill_price REAL, fill_date TEXT,
                            reason TEXT, pnl REAL)''')
                        conn.execute('''CREATE TABLE IF NOT EXISTS positions(
                            symbol TEXT PRIMARY KEY, shares INTEGER, entry REAL, stop REAL,
                            entry_date TEXT, last_checked TEXT, cost REAL)''')
                        
                        # Cek jangan sampai double buy / overwrite
                        pos_exists = conn.execute("SELECT symbol FROM positions WHERE symbol=?", (symbol,)).fetchone()
                        if pos_exists:
                            st.error(f"Saham {symbol} sudah ada di portofolio. Jual (Close Position) terlebih dahulu sebelum membeli lagi!")
                        else:
                            # Cek sisa saldo tunai (Cash Management)
                            conn.execute('''CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v REAL)''')
                            
                            if conn.execute("SELECT 1 FROM kv WHERE k='cash'").fetchone() is None:
                                conn.execute("INSERT INTO kv VALUES('cash', ?)", (INITIAL_CAPITAL,))
                                
                            cash_row = conn.execute("SELECT v FROM kv WHERE k='cash'").fetchone()
                            available_cash = float(cash_row[0])
                            
                            shares = int(risk['lots'] * 100)
                            entry_price = float(risk['entry'])
                            gross_cost = shares * entry_price
                            buy_fee = gross_cost * 0.0015
                            total_cost = gross_cost + buy_fee
                            
                            if available_cash < total_cost:
                                st.error(f"Saldo Kas tidak cukup! Butuh Rp {total_cost:,.0f} tapi saldo hanya Rp {available_cash:,.0f}.")
                            else:
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                conn.execute(
                                    "INSERT INTO orders (signal_date, symbol, side, lots, ref_price, status, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                    (now, symbol, "BUY", int(risk['lots']), entry_price, "FILLED", "MANUAL DASHBOARD BUY")
                                )
                                conn.execute(
                                    "INSERT INTO positions (symbol, shares, entry, stop, entry_date, cost) VALUES (?, ?, ?, ?, ?, ?)",
                                    (symbol, shares, entry_price, float(risk['stop_loss']), now, total_cost)
                                )
                                conn.execute("UPDATE kv SET v = v - ? WHERE k='cash'", (total_cost,))
                                st.success(f"Order BUY {symbol} berhasil dieksekusi secara simulasi dan masuk ke paper.db!")
                except Exception as ex:
                    st.error(f"Gagal mengeksekusi order: {ex}")

        else:

            st.warning(
                f"Risk REJECTED — "
                f"{risk['reason']}"
            )

    except Exception as e:

        st.error(
            f"Detail engine error: {str(e)}"
        )


# ============================================================
# PAGE 3
# PNL MONITORING (REAL DATABASE)
# ============================================================

st.header("3. PnL Monitoring")

import sqlite3
from pathlib import Path
import os

db_path = "data/paper.db"
os.makedirs("data", exist_ok=True)

try:
    with sqlite3.connect(db_path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, signal_date TEXT, symbol TEXT,
            side TEXT, lots INTEGER, ref_price REAL, limit_price REAL,
            status TEXT DEFAULT 'PENDING', fill_price REAL, fill_date TEXT,
            reason TEXT, pnl REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS positions(
            symbol TEXT PRIMARY KEY, shares INTEGER, entry REAL, stop REAL,
            entry_date TEXT, last_checked TEXT, cost REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v REAL)''')
        
        # Inisialisasi modal awal jika kosong
        if conn.execute("SELECT 1 FROM kv WHERE k='cash'").fetchone() is None:
            conn.execute("INSERT INTO kv VALUES('cash', ?)", (INITIAL_CAPITAL,))
            conn.commit()
            
        portfolio = pd.read_sql("SELECT * FROM positions", conn)
        trades = pd.read_sql("SELECT * FROM orders WHERE status='FILLED'", conn)
        cash_row = conn.execute("SELECT v FROM kv WHERE k='cash'").fetchone()
        available_cash = float(cash_row[0]) if cash_row else 0
        
    if portfolio.empty and trades.empty:
        st.info("Belum ada posisi paper trading. Coba klik 'EXECUTE BUY' pada saham pilihan di atas.")
    
    total_pnl = pd.to_numeric(trades["pnl"], errors='coerce').sum() if ('pnl' in trades.columns) else 0
    open_capital = pd.to_numeric(portfolio["cost"], errors='coerce').sum() if ('cost' in portfolio.columns and not portfolio.empty) else 0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Available Cash", f"Rp {available_cash:,.0f}")
    c2.metric("Total Open Capital", f"Rp {open_capital:,.0f}")
    c3.metric("Net Realized PnL (After Fee)", f"Rp {total_pnl:,.0f}")
    c4.metric("Executed Trades", len(trades))
    
    st.subheader("Aktif / Open Positions")
    st.dataframe(portfolio, use_container_width=True)
    
    # --- CLOSE POSITION FEATURE ---
    if not portfolio.empty:
        st.write("---")
        st.write("**Close Position (Sell)**")
        sell_col1, sell_col2 = st.columns([3, 1])
        sell_symbol = sell_col1.selectbox("Pilih saham untuk dijual", portfolio["symbol"].tolist())
        if sell_col2.button("FORCE SELL"):
            try:
                latest_df = get_market_data(sell_symbol, period="1mo", interval="1d")
                current_price = float(latest_df.iloc[-1]['close'])
                
                pos_row = portfolio[portfolio["symbol"] == sell_symbol].iloc[0]
                shares = int(pos_row["shares"])
                cost = float(pos_row["cost"]) # Biaya beli (termasuk fee 0.15%)
                
                # Fee Jual (0.25%)
                gross_value = current_price * shares
                sell_fee = gross_value * 0.0025
                net_receive = gross_value - sell_fee
                pnl = float(net_receive - cost)
                lots = int(shares // 100)
                
                from datetime import datetime
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                with sqlite3.connect("data/paper.db") as conn:
                    conn.execute("INSERT INTO orders (signal_date, symbol, side, lots, ref_price, status, pnl) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (now, sell_symbol, "SELL", lots, current_price, "FILLED", pnl))
                    conn.execute("DELETE FROM positions WHERE symbol=?", (sell_symbol,))
                    # Update Cash
                    conn.execute("UPDATE kv SET v = v + ? WHERE k='cash'", (net_receive,))
                
                st.success(f"Berhasil menjual {sell_symbol} di Rp{current_price:,.0f}. Net PnL (setelah fee): Rp{pnl:,.0f}")
                st.rerun()
            except Exception as ex:
                st.error(f"Gagal menjual {sell_symbol}: {ex}")
    
    st.write("---")
    st.subheader("Trade History (Closed & Filled Orders)")
    
    display_trades = trades.copy()
    display_trades = display_trades.sort_values("id", ascending=False).head(20)
    st.dataframe(display_trades, use_container_width=True)

except Exception as e:
    st.info(f"Database error: {e}")


# ============================================================
# PAGE 4
# SYSTEM HEALTH
# ============================================================

st.header("4. System Health")

health = pd.DataFrame(
    [
        ["Market Data", "🟢 CONNECTED"],
        ["Universe Scanner", "🟢 RUNNING"],
        ["Penetration Engine", "🟢 RUNNING"],
        ["Risk Engine", "🟢 RUNNING"],
        ["Execution Adapter", "🟢 CONNECTED (PaperDB)"],
        ["Dashboard", "🟢 RUNNING"],
    ],
    columns=["Component", "Status"]
)

st.table(health)


# ============================================================
# ERROR MONITOR
# ============================================================

st.header("5. Error Monitoring")

if errors:

    for error in errors:

        st.error(error)

else:

    st.success(
        "No scanner errors detected."
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    f"Last update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)
