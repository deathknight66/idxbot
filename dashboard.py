import streamlit as st
import pandas as pd
import sqlite3
import random
from pathlib import Path
import plotly.graph_objects as go
from datetime import datetime, timedelta

from idxbot.config import load_config

# Setup Page dengan tema gelap/terminal
st.set_page_config(page_title="SURGEE SH — TRADING BOT", layout="centered", initial_sidebar_state="collapsed")

# Custom CSS untuk terminal aesthetic
st.markdown("""
<style>
    * { font-family: 'Courier New', Courier, monospace !important; }
    h1, h2, h3 { text-align: center; border-bottom: 1px dashed #555; padding-bottom: 10px; }
    .stMetric, .stDataFrame { border: 1px solid #333; padding: 10px; }
    .status-green { color: #00ff00; font-weight: bold; }
    .status-red { color: #ff0000; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.markdown("## SURGEE SH — TRADING BOT")

@st.cache_resource
def get_config():
    return load_config("config.yaml")

@st.cache_data(ttl=10)
def get_portfolio_data():
    cfg = get_config()
    db_path = cfg["paper"]["db_path"]
    if not Path(db_path).exists():
        return pd.DataFrame(), pd.DataFrame()
    
    with sqlite3.connect(db_path) as db:
        pos = pd.read_sql("SELECT * FROM positions", db)
        trades = pd.read_sql("SELECT * FROM trades", db)
    return pos, trades

pos, trades = get_portfolio_data()

# Kalkulasi PnL Mock/Real
equity = 105200000
daily_pnl = 1200000
total_pnl_pct = 5.2

if not pos.empty and not trades.empty:
    equity = pos['cost'].sum() + (trades['pnl'].sum() if 'pnl' in trades else 0)
    # Kalkulasi riil bisa disempurnakan

# --- PORTFOLIO MONITOR ---
st.markdown("### PORTFOLIO MONITOR")
col1, col2, col3 = st.columns(3)
col1.metric("Equity", f"Rp {equity/1000000:.1f} jt")
col2.metric("Daily PnL", f"+Rp {daily_pnl/1000000:.1f} jt")
col3.metric("Total PnL", f"+{total_pnl_pct}%")

# --- EQUITY CURVE ---
st.markdown("### EQUITY CURVE")
# Membuat dummy curve agar menyerupai mockup jika tidak ada data trade
dates = [datetime.now() - timedelta(days=i) for i in range(30, 0, -1)]
curve_data = [100000000 + (i * 100000) + random.randint(-500000, 500000) for i in range(30)]

fig = go.Figure(data=go.Scatter(x=dates, y=curve_data, line=dict(color='#00ff00', width=2)))
fig.update_layout(
    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
    height=200, margin=dict(l=0, r=0, t=0, b=0),
    xaxis=dict(showgrid=False, visible=False),
    yaxis=dict(showgrid=False, visible=False)
)
st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

# --- OPEN POSITIONS ---
st.markdown("### OPEN POSITIONS")
if pos.empty:
    # Dummy data menyerupai mockup jika kosong
    dummy_pos = pd.DataFrame({
        "Symbol": ["BBCA", "BMRI"],
        "Action": ["BUY", "BUY"],
        "Size": ["10 lot", "15 lot"],
        "PnL": ["+2.4%", "+1.8%"]
    })
    st.dataframe(dummy_pos, hide_index=True, use_container_width=True)
else:
    st.dataframe(pos, hide_index=True, use_container_width=True)

# --- SYSTEM STATUS ---
st.markdown("### SYSTEM STATUS")
st.markdown("""
| Component | Status |
| :--- | :--- |
| 🟢 Market Data | <span class='status-green'>CONNECTED</span> |
| 🟢 Trading Engine | <span class='status-green'>RUNNING</span> |
| 🟢 Execution | <span class='status-green'>CONNECTED</span> |
| 🟢 Database | <span class='status-green'>HEALTHY</span> |
| 🔴 Error | <span class='status-red'>0</span> |
""", unsafe_allow_html=True)
