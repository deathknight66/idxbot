import logging
import traceback
from datetime import datetime
import numpy as np
import pandas as pd
import sqlite3
import os
import hashlib
import yfinance as yf
import streamlit as st
import plotly.graph_objects as go
from engine import *

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="IDXBot Trading Terminal",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp { background-color: #0E1117; }
    .metric-box {
        background-color: #1E222D;
        border-radius: 8px;
        padding: 15px;
        text-align: center;
        border: 1px solid #363a45;
    }
    .metric-value { font-size: 24px; font-weight: bold; color: #D1D4DC; }
    .metric-label { font-size: 14px; color: #787b86; }
    </style>
    """,
    unsafe_allow_html=True
)

# ============================================================
# AUTHENTICATION & CACHING
# ============================================================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def show_login_page():
    st.title("🛡️ IDXBot Command Center")
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect("data/paper.db") as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT, created_at TEXT)''')
        try:
            conn.execute("INSERT OR IGNORE INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                         ("deathknight666", hash_password("Xnunxer123*"), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
        except:
            pass
            
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            with sqlite3.connect("data/paper.db") as conn:
                user = conn.execute("SELECT password_hash FROM users WHERE username=?", (username,)).fetchone()
                if user and user[0] == hash_password(password):
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = username
                    st.rerun()
                else:
                    st.error("Invalid credentials")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    show_login_page()
    st.stop()

@st.cache_data(ttl=300)
def scan_universe_cached():
    import engine
    return engine.scan_universe()

@st.cache_data(ttl=60)
def get_market_data_cached(symbol, period='3y', interval='1d'):
    import engine
    return engine.get_market_data(symbol, period, interval)

def load_portfolio_local():
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect("data/paper.db") as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, shares INTEGER, entry REAL, stop REAL, entry_date TEXT, last_checked TEXT, cost REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v REAL)''')
        if not conn.execute("SELECT 1 FROM kv WHERE k='cash'").fetchone():
            conn.execute("INSERT INTO kv VALUES('cash', ?)", (INITIAL_CAPITAL,))
            conn.commit()
        portfolio = pd.read_sql("SELECT * FROM positions", conn)
        cash_row = conn.execute("SELECT v FROM kv WHERE k='cash'").fetchone()
        cash = float(cash_row[0]) if cash_row else INITIAL_CAPITAL
    return portfolio, cash

def execute_order(symbol, side, lots, price, reason):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect("data/paper.db") as conn:
        cash_row = conn.execute("SELECT v FROM kv WHERE k='cash'").fetchone()
        cash = float(cash_row[0]) if cash_row else INITIAL_CAPITAL
        shares = int(lots * 100)
        gross = shares * price
        
        if side == "BUY":
            cost = gross * 1.0015
            if cash < cost:
                raise ValueError("Insufficient cash")
                
            conn.execute("UPDATE kv SET v = v - ? WHERE k='cash'", (cost,))
            
            existing = conn.execute("SELECT shares, cost FROM positions WHERE symbol=?", (symbol,)).fetchone()
            if existing:
                new_shares = existing[0] + shares
                new_cost = existing[1] + cost
                new_entry = new_cost / (new_shares * 1.0015)
                conn.execute("UPDATE positions SET shares=?, cost=?, entry=? WHERE symbol=?", (new_shares, new_cost, new_entry, symbol))
            else:
                conn.execute("INSERT INTO positions (symbol, shares, entry, stop, entry_date, last_checked, cost) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (symbol, shares, price, price * 0.9, now, now, cost))
                             
            conn.execute("INSERT INTO orders (signal_date, symbol, side, lots, ref_price, status, fill_price, fill_date, reason, pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (now, symbol, "BUY", lots, price, "FILLED", price, now, reason, 0))
                         
        elif side == "SELL":
            existing = conn.execute("SELECT shares, cost, entry FROM positions WHERE symbol=?", (symbol,)).fetchone()
            if not existing or existing[0] < shares:
                raise ValueError("Not enough shares to sell")
                
            net = gross * 0.9975
            conn.execute("UPDATE kv SET v = v + ? WHERE k='cash'", (net,))
            
            avg_cost = (existing[1] / existing[0]) * shares
            pnl = net - avg_cost
            
            if existing[0] == shares:
                conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            else:
                rem_shares = existing[0] - shares
                rem_cost = existing[1] - avg_cost
                conn.execute("UPDATE positions SET shares=?, cost=? WHERE symbol=?", (rem_shares, rem_cost, symbol))
                
            conn.execute("INSERT INTO orders (signal_date, symbol, side, lots, ref_price, status, fill_price, fill_date, reason, pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (now, symbol, "SELL", lots, price, "FILLED", price, now, reason, pnl))
        conn.commit()

def load_trade_history_local():
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect("data/paper.db") as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, signal_date TEXT, symbol TEXT, side TEXT, lots INTEGER, ref_price REAL, limit_price REAL, status TEXT, fill_price REAL, fill_date TEXT, reason TEXT, pnl REAL)''')
        trades = pd.read_sql("SELECT * FROM orders", conn)
    return trades

# ============================================================
# SIDEBAR
# ============================================================
st.sidebar.markdown(f"👤 **Halo, {st.session_state['username']}!**")
if st.sidebar.button("Logout"):
    st.session_state["logged_in"] = False
    st.rerun()

st.sidebar.write("---")
view_mode = st.sidebar.radio("Navigasi", ["🏠 Trading Terminal", "🧪 Strategy Backtester"])
st.sidebar.write("---")
st.sidebar.header("Risk Settings")
risk_percent = st.sidebar.slider("Risk / Trade (%)", 0.1, 5.0, 1.0, 0.1)

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

if "alert_msg" in st.session_state:
    st.success(st.session_state["alert_msg"])
    del st.session_state["alert_msg"]

portfolio, cash = load_portfolio_local()
total_equity = cash + (portfolio['cost'].sum() if not portfolio.empty else 0)

# ============================================================
# MAIN VIEW: TRADING TERMINAL
# ============================================================
if view_mode == "🏠 Trading Terminal":
    st.title("🤖 IDXBOT Trading Terminal")
    
    # 1. TOP METRICS
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f'<div class="metric-box"><div class="metric-label">Total Equity</div><div class="metric-value">Rp {total_equity:,.0f}</div></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-box"><div class="metric-label">Available Cash</div><div class="metric-value">Rp {cash:,.0f}</div></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-box"><div class="metric-label">Open Positions</div><div class="metric-value">{len(portfolio)}</div></div>', unsafe_allow_html=True)
    m4.markdown(f'<div class="metric-box"><div class="metric-label">Bot Status</div><div class="metric-value" style="color:#00ff88;">🟢 ACTIVE</div></div>', unsafe_allow_html=True)
    st.write("")

    # 2. SCANNER & PORTFOLIO IN ONE ROW
    col_left, col_right = st.columns([2.5, 1])
    
    with col_left:
        st.subheader("📡 Live Signals (Scanner)")
        with st.spinner("Scanning..."):
            try:
                scan_df, errors = scan_universe_cached()
                if scan_df.empty:
                    st.error("Gagal menarik data market. Cek koneksi / Yahoo Finance rate limit.")
                else:
                    display_df = scan_df.copy().sort_values("entry_score", ascending=False)
                    def color_signal(val):
                        return 'color: #00ff88; font-weight: bold;' if val == 'ENTRY CANDIDATE' else 'color: gray'
                    st.dataframe(display_df.style.map(color_signal, subset=['signal']), height=250, use_container_width=True)
                    candidates = scan_df[scan_df['signal'] == 'ENTRY CANDIDATE']['symbol'].tolist()
                    all_symbols = scan_df['symbol'].tolist()
            except Exception as e:
                st.error(f"Scanner error: {e}")
                candidates, all_symbols = [], []

    with col_right:
        st.subheader("💼 Active Positions")
        if portfolio.empty:
            st.info("Belum ada posisi terbuka.")
        else:
            st.dataframe(portfolio[['symbol', 'shares', 'entry', 'cost']], height=250, use_container_width=True)

    st.write("---")

    # 3. CHART & EXECUTION
    st.subheader("📈 Chart & Execution Panel")
    
    chart_col, exec_col = st.columns([3, 1])
    
    options = candidates if candidates else all_symbols
    selected = st.selectbox("Pilih Saham untuk Analisis & Trading:", options if options else ["BMRI"])
    symbol = selected + ".JK"
    
    with chart_col:
        try:
            df = get_market_data_cached(symbol)
            df = calculate_indicators(df)
            
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price',
                                         increasing_line_color='#26a69a', decreasing_line_color='#ef5350'))
            fig.add_trace(go.Scatter(x=df.index, y=df['ma20'], name='MA20', line=dict(color='#2962FF', width=1.5)))
            fig.add_trace(go.Scatter(x=df.index, y=df['ma50'], name='MA50', line=dict(color='#FF6D00', width=1.5)))
            fig.update_layout(template='plotly_dark', height=450, xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Gagal memuat chart: {e}")

    with exec_col:
        st.markdown("### Eksekusi Trading")
        try:
            risk = risk_check(df, capital=total_equity, risk_per_trade=risk_percent/100.0)
            if risk['approved']:
                st.success(f"Signal OK\n{risk['lots']} lot")
                if st.button(f"🟩 BUY {symbol}", use_container_width=True):
                    execute_order(symbol, "BUY", risk['lots'], risk['entry'], "MANUAL DASHBOARD")
                    st.session_state["alert_msg"] = f"Berhasil BUY {symbol}"
                    st.rerun()
            else:
                st.warning(f"WAIT\n{risk['reason']}")
                
            st.write("---")
            st.markdown("### Cut Position")
            if not portfolio.empty and selected in portfolio['symbol'].values:
                if st.button(f"🟥 FORCE SELL {symbol}", use_container_width=True):
                    pos_row = portfolio[portfolio["symbol"] == selected].iloc[0]
                    current_price = float(df.iloc[-1]['close'])
                    execute_order(symbol, "SELL", int(pos_row["shares"])/100, current_price, "FORCE SELL")
                    st.session_state["alert_msg"] = f"Berhasil SELL {symbol}"
                    st.rerun()
            else:
                st.info("Tidak ada posisi.")
        except Exception as e:
            st.error("Engine belum siap.")

# ============================================================
# BACKTESTER VIEW
# ============================================================
elif view_mode == "🧪 Strategy Backtester":
    st.title("🧪 Historical Strategy Backtester")
    st.markdown("Uji strategi cerdas kita ke masa lalu untuk melihat apakah win rate dan profit factor-nya menguntungkan!")
    if st.button("▶️ JALANKAN BACKTEST", use_container_width=True):
        with st.spinner("Menjalankan Simulasi..."):
            try:
                res = run_historical_backtest()
                if res:
                    st.subheader("📊 Quant Performance Summary")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Win Rate", f"{res['win_rate']:.1f}%")
                    c2.metric("Total Trades", f"{res['total_trades']}")
                    c3.metric("Net Profit", f"Rp {res['net_profit']:,.0f}")
                    c4.metric("Profit Factor", f"{res['profit_factor']:.2f}")
                    
                    c5, c6, c7, c8 = st.columns(4)
                    c5.metric("Expectancy", f"{res['expectancy']:.2f}%")
                    c6.metric("Max Drawdown", f"{res['max_dd']:.2f}%")
                    c7.metric("Sharpe Ratio", f"{res['sharpe']:.2f}")
                    c8.metric("Avg Holding", f"{res['avg_holding']:.1f} Days")
                    
                    st.subheader("📈 Equity Curve")
                    eq_df = res['equity_df']
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=eq_df['date'], y=eq_df['equity'], mode='lines', name='Equity', line=dict(color='#00ff88', width=2)))
                    fig.update_layout(template='plotly_dark')
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"Backtest error: {str(e)}")
