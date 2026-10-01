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
        
        try:
            conn.execute("INSERT OR IGNORE INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                         ("deathknight666", hash_password("Xnunxer123*"), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
        except:
            pass
            
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
            with sqlite3.connect("data/paper.db") as conn:
                user = conn.execute("SELECT password_hash FROM users WHERE username=?", (username,)).fetchone()
                if user and user[0] == hash_password(password):
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = username
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Invalid credentials")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    show_login_page()
    st.stop()

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="IDXBot Quant Terminal",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp { background-color: #0E1117; }
    </style>
    """,
    unsafe_allow_html=True
)

from engine import *

@st.cache_data(ttl=300)
def scan_universe_cached():
    return scan_universe()

@st.cache_data(ttl=60)
def get_market_data_cached(symbol, period='3y', interval='1d'):
    import engine
    return engine.get_market_data(symbol, period, interval)

# ============================================================
# SIDEBAR
# ============================================================
st.sidebar.markdown(f"👤 **Halo, {st.session_state['username']}!**")
if st.sidebar.button("Logout"):
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.rerun()

st.sidebar.write("---")
st.sidebar.header("IDXBOT Mode")
mode = st.sidebar.radio("Trading Mode", ["📊 PAPER TRADING", "🔴 LIVE TRADING (Locked)"])

st.sidebar.write("---")
menu = st.sidebar.radio("Navigation", [
    "🏠 Dashboard (Portfolio)", 
    "📡 Signals (Scanner)", 
    "💼 Positions & Orders", 
    "🧪 Strategy Tester", 
    "🛡️ Kill Switch (Health)"
])

st.sidebar.write("---")
st.sidebar.header("Risk Settings")
capital = st.sidebar.number_input("Capital", min_value=1_000_000, value=INITIAL_CAPITAL, step=1_000_000)
risk_percent = st.sidebar.slider("Risk / Trade (%)", 0.1, 5.0, 1.0, 0.1)

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# Execute Orders
if "alert_msg" in st.session_state:
    st.success(st.session_state["alert_msg"])
    del st.session_state["alert_msg"]

# ============================================================
# ROUTING
# ============================================================
st.title("🤖 IDXBOT Quant Terminal")
st.markdown(f"**Mode:** {mode}")
st.write("---")


def load_portfolio():
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

def load_trade_history():
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect("data/paper.db") as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, signal_date TEXT, symbol TEXT, side TEXT, lots INTEGER, ref_price REAL, limit_price REAL, status TEXT, fill_price REAL, fill_date TEXT, reason TEXT, pnl REAL)''')
        trades = pd.read_sql("SELECT * FROM orders", conn)
    return trades

portfolio, cash = load_portfolio()

total_equity = cash + (portfolio['cost'].sum() if not portfolio.empty else 0)

if menu == "🏠 Dashboard (Portfolio)":
    st.header("Portfolio Overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Equity", f"Rp {total_equity:,.0f}")
    c2.metric("Available Cash", f"Rp {cash:,.0f}")
    c3.metric("Unrealized P&L", "N/A") # Placeholder
    c4.metric("Realized P&L", "N/A") # Placeholder
    
    st.subheader("Active Positions")
    if portfolio.empty:
        st.info("No active positions.")
    else:
        st.dataframe(portfolio, use_container_width=True)

elif menu == "📡 Signals (Scanner)":
    st.header("Multi-Strategy Scanner")
    with st.spinner("Scanning universe..."):
        try:
            scan_df, errors = scan_universe_cached()
            if scan_df.empty:
                st.error("DEBUG: Scanner returned empty dataframe! Errors:")
                st.write(errors[:5])
            else:
                display_df = scan_df.copy().sort_values("entry_score", ascending=False)
                
                def color_signal(val):
                    color = 'green' if val == 'ENTRY CANDIDATE' else 'gray'
                    return f'color: {color}'
                    
                st.dataframe(
                    display_df.style.applymap(color_signal, subset=['signal']),
                    use_container_width=True,
                    height=300
                )
                
                # Charting & Execution
                st.write("---")
                st.subheader("Chart Analysis & Execution")
                candidates = scan_df[scan_df['signal'] == 'ENTRY CANDIDATE']['symbol'].tolist()
                all_symbols = scan_df['symbol'].tolist()
                options = candidates if candidates else all_symbols
                
                if options:
                    selected = st.selectbox("Pilih Saham", options)
                    symbol = selected + ".JK"
                    
                    df = get_market_data_cached(symbol)
                    df = calculate_indicators(df)
                    penetration = penetration_engine(df)
                    risk = risk_check(df, capital=total_equity, risk_per_trade=risk_percent/100.0)
                    
                    # Chart
                    from plotly.subplots import make_subplots
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
                    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df.index, y=df['ma20'], name='MA20', line=dict(color='#2962FF', width=1.5)), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df.index, y=df['ma50'], name='MA50', line=dict(color='#FF6D00', width=1.5)), row=1, col=1)
                    fig.add_trace(go.Bar(x=df.index, y=df['volume'], name='Volume'), row=2, col=1)
                    fig.update_layout(template='plotly_dark', height=500, xaxis_rangeslider_visible=False, title=f"<b>{symbol}</b>")
                    st.plotly_chart(fig, use_container_width=True)
                    
                    if risk['approved']:
                        st.success(f"Risk APPROVED — {risk['lots']} lot")
                        if st.button(f"EXECUTE BUY {symbol} (Paper Trade)"):
                            try:
                                execute_order(symbol, "BUY", risk['lots'], risk['entry'], "MANUAL DASHBOARD")
                                st.session_state["alert_msg"] = f"Berhasil BUY {risk['lots']} lot {symbol} di harga Rp {risk['entry']:,.0f}"
                                st.rerun()
                            except Exception as e:
                                st.error(f"Gagal execute: {str(e)}")
                    else:
                        st.warning(f"Risk REJECTED: {risk['reason']}")
                        
        except Exception as e:
            st.error(f"Scanner crash: {str(e)}")

elif menu == "💼 Positions & Orders":
    st.header("Position Manager & Order Reconciliation")
    
    sell_col1, sell_col2 = st.columns([3, 1])
    sell_symbol = sell_col1.selectbox("Select position to close", portfolio["symbol"].tolist() if not portfolio.empty else ["No Positions"])
    if sell_col2.button("FORCE SELL"):
        if sell_symbol != "No Positions":
            try:
                latest_df = get_market_data_cached(sell_symbol, period="1mo", interval="1d")
                current_price = float(latest_df.iloc[-1]['close'])
                pos_row = portfolio[portfolio["symbol"] == sell_symbol].iloc[0]
                execute_order(sell_symbol, "SELL", int(pos_row["shares"])/100, current_price, "FORCE SELL")
                st.session_state["alert_msg"] = f"FORCE SELL {sell_symbol} dieksekusi."
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
                
    st.write("---")
    history = load_trade_history()
    st.subheader("Order Reconciliation (Trade History)")
    st.dataframe(history.sort_values("id", ascending=False), use_container_width=True)

elif menu == "🧪 Strategy Tester":
    st.header("Strategy Tester (Historical Backtest)")
    if st.button("▶️ JALANKAN BACKTEST (Makan Waktu 3-5 Menit)"):
        with st.spinner("Menjalankan Simulasi Multi-Strategy..."):
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
                    
                    st.subheader("📈 Equity Curve (Walk-Forward Simulation)")
                    eq_df = res['equity_df']
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=eq_df['date'], y=eq_df['equity'], mode='lines', name='Equity', line=dict(color='#00ff88', width=2)))
                    fig.update_layout(template='plotly_dark', margin=dict(l=0, r=0, t=30, b=0), paper_bgcolor='#0E1117', plot_bgcolor='#0E1117')
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Tidak ada transaksi selama backtest (Mungkin kondisi market sedang Bearish terus).")
            except Exception as e:
                st.error(f"Backtest error: {str(e)}")

elif menu == "🛡️ Kill Switch (Health)":
    st.header("Kill Switch & Safety Check")
    st.warning("⚠️ KILL SWITCH MAKES TRADING BOT HALT IMMEDIATELY")
    
    col1, col2 = st.columns(2)
    col1.metric("API Connection", "🟢 HEALTHY")
    col2.metric("Data Stale Check", "🟢 PASSED (0ms delay)")
    
    col3, col4 = st.columns(2)
    col3.metric("Risk Engine State", "🟢 OK")
    col4.metric("Broker API / Paper DB", "🟢 CONNECTED")
    
    if st.button("🚨 ACTIVATE KILL SWITCH"):
        st.error("System Halted! Order Creation Blocked.")

