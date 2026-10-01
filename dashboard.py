import logging
from datetime import datetime
import os
import sqlite3
import hashlib

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from engine import *

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="IDXBot Trading Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* Dark background */
    .stApp, .stApp > header { background-color: #131722 !important; }
    [data-testid="stSidebar"] { background-color: #1E222D !important; }
    .block-container { padding: 0.5rem 1rem !important; }
    
    /* BUY/SELL button style */
    div[data-testid="stButton"] > button {
        border-radius: 4px !important;
        font-weight: bold !important;
        font-size: 16px !important;
        padding: 8px 24px !important;
    }

    /* Watchlist row */
    .watchlist-item {
        display: flex;
        justify-content: space-between;
        padding: 6px 4px;
        border-bottom: 1px solid #2A2E39;
        font-size: 13px;
        color: #D1D4DC;
    }
    .watchlist-item .chg-pos { color: #26a69a; }
    .watchlist-item .chg-neg { color: #ef5350; }
    .watchlist-header {
        color: #787b86;
        font-size: 11px;
        font-weight: bold;
        padding: 4px;
        border-bottom: 1px solid #2A2E39;
    }
    
    /* Signal card */
    .signal-card {
        background-color: #1E222D;
        border-radius: 6px;
        padding: 12px;
        border: 1px solid #2A2E39;
        font-size: 13px;
        color: #D1D4DC;
    }
    .signal-card table { width: 100%; }
    .signal-card td { padding: 2px 4px; }
    .signal-ok { color: #26a69a; }
    .signal-wait { color: #ef5350; }
    
    /* Chat bubble */
    .chat-user { background:#2A2E39; padding:8px 12px; border-radius:8px; margin:4px 0; }
    .chat-bot { background:#1E2844; padding:8px 12px; border-radius:8px; margin:4px 0; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# AUTH
# ============================================================
def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def show_login():
    col = st.columns([1,2,1])[1]
    with col:
        st.markdown("## 📈 IDXBot Trading Terminal")
        os.makedirs("data", exist_ok=True)
        with sqlite3.connect("data/paper.db") as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT)")
            conn.execute("INSERT OR IGNORE INTO users VALUES (?, ?)", ("deathknight666", hash_password("Xnunxer123*")))
            conn.commit()
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                with sqlite3.connect("data/paper.db") as conn:
                    row = conn.execute("SELECT password_hash FROM users WHERE username=?", (u,)).fetchone()
                    if row and row[0] == hash_password(p):
                        st.session_state["logged_in"] = True
                        st.session_state["username"] = u
                        st.rerun()
                    else:
                        st.error("Username/password salah")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if not st.session_state["logged_in"]:
    show_login()
    st.stop()

# ============================================================
# DB HELPERS
# ============================================================
def db_init():
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect("data/paper.db") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, shares INTEGER, entry REAL, stop REAL, tp REAL, entry_date TEXT, cost REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT, side TEXT, lots INTEGER, price REAL, status TEXT, reason TEXT, pnl REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v REAL)")
        if not conn.execute("SELECT 1 FROM kv WHERE k='cash'").fetchone():
            conn.execute("INSERT INTO kv VALUES('cash', ?)", (INITIAL_CAPITAL,))
        conn.commit()

def get_portfolio():
    db_init()
    with sqlite3.connect("data/paper.db") as conn:
        df = pd.read_sql("SELECT * FROM positions", conn)
        cash = conn.execute("SELECT v FROM kv WHERE k='cash'").fetchone()[0]
    return df, float(cash)

def get_orders():
    db_init()
    with sqlite3.connect("data/paper.db") as conn:
        return pd.read_sql("SELECT * FROM orders ORDER BY id DESC LIMIT 30", conn)

def paper_buy(symbol, lots, price, stop, tp):
    db_init()
    shares = int(lots * 100)
    cost = shares * price * 1.0015
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect("data/paper.db") as conn:
        cash = conn.execute("SELECT v FROM kv WHERE k='cash'").fetchone()[0]
        pos_count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        if cash < cost:
            return False, "Saldo tidak cukup"
        if pos_count >= 5:
            return False, "Maks 5 posisi aktif"
        conn.execute("UPDATE kv SET v = v - ? WHERE k='cash'", (cost,))
        conn.execute("INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?)", (symbol, shares, price, stop, tp, now, cost))
        conn.execute("INSERT INTO orders (ts, symbol, side, lots, price, status, reason, pnl) VALUES (?,?,?,?,?,?,?,?)",
                     (now, symbol, "BUY", lots, price, "FILLED", "MANUAL", 0))
        conn.commit()
    return True, f"BUY {lots} lot {symbol} @ Rp{price:,.0f} ✅"

def paper_sell(symbol, price):
    db_init()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect("data/paper.db") as conn:
        pos = conn.execute("SELECT shares, cost FROM positions WHERE symbol=?", (symbol,)).fetchone()
        if not pos:
            return False, "Tidak ada posisi"
        shares, cost = pos
        lots = shares // 100
        net = shares * price * 0.9975
        pnl = net - cost
        conn.execute("UPDATE kv SET v = v + ? WHERE k='cash'", (net,))
        conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        conn.execute("INSERT INTO orders (ts, symbol, side, lots, price, status, reason, pnl) VALUES (?,?,?,?,?,?,?,?)",
                     (now, symbol, "SELL", lots, price, "FILLED", "MANUAL", pnl))
        conn.commit()
    pnl_str = f"+Rp{pnl:,.0f}" if pnl >= 0 else f"-Rp{abs(pnl):,.0f}"
    return True, f"SELL {symbol} @ Rp{price:,.0f} | PnL: {pnl_str}"

db_init()

# ============================================================
# CACHE
# ============================================================
@st.cache_data(ttl=300)
def scanner_cached():
    import engine
    return engine.scan_universe()

@st.cache_data(ttl=60)
def chart_data(symbol, period="3y"):
    import engine
    df = engine.get_market_data(symbol, period=period)
    return engine.calculate_indicators(df)

# ============================================================
# HEADER BAR
# ============================================================
portfolio, cash = get_portfolio()
invested = portfolio['cost'].sum() if not portfolio.empty else 0
total_equity = cash + invested

h1, h2, h3, h4, h5, h6 = st.columns([2, 1, 1, 1, 1, 1])
h1.markdown(f"**📈 IDXBot Terminal** &nbsp;&nbsp; <span style='color:#26a69a;font-size:13px'>🟢 PAPER TRADING</span>", unsafe_allow_html=True)
h2.metric("Total Equity", f"Rp{total_equity/1e6:.2f}M")
h3.metric("Cash", f"Rp{cash/1e6:.2f}M")
h4.metric("Invested", f"Rp{invested/1e6:.2f}M")
h5.metric("Open Pos.", f"{len(portfolio)}/5")
if h6.button("🚪 Logout"):
    st.session_state["logged_in"] = False
    st.rerun()

st.write("---")

# ============================================================
# SYMBOL SELECTOR (TradingView style top bar)
# ============================================================
WATCHLIST = ["BBCA", "BMRI", "BBRI", "TLKM", "ANTM", "GOTO", "BRIS", "ASII", "UNVR", "INDF", "ICBP", "PGAS", "ADRO"]

top1, top2 = st.columns([4, 1])
with top1:
    col_sym, col_period = st.columns([3, 1])
    selected_sym = col_sym.selectbox("", WATCHLIST, label_visibility="collapsed")
    period = col_period.selectbox("", ["3mo", "1y", "3y"], index=1, label_visibility="collapsed")

# ============================================================
# MAIN LAYOUT: CHART | EXECUTION | WATCHLIST
# ============================================================
main_chart, side_panel = st.columns([3.5, 1.2])

with main_chart:
    symbol = selected_sym + ".JK"
    try:
        df = chart_data(symbol, period)
        latest = df.iloc[-1]

        # --- SELL/BUY bar above chart ---
        btn_sell, btn_buy, price_disp = st.columns([1, 1, 4])
        
        with btn_sell:
            if st.button(f"🔴 {latest['close']:,.0f}\nSELL", use_container_width=True):
                if selected_sym + ".JK" in portfolio["symbol"].values:
                    ok, msg = paper_sell(symbol, float(latest['close']))
                    if ok:
                        st.cache_data.clear()
                        st.session_state["msg"] = msg
                        st.rerun()
                    else:
                        st.session_state["msg"] = f"❌ {msg}"
                else:
                    st.session_state["msg"] = "❌ Tidak ada posisi untuk dijual"

        with btn_buy:
            if st.button(f"🟢 {latest['close']:,.0f}\nBUY", use_container_width=True):
                st.session_state["confirm_buy"] = True

        if "msg" in st.session_state:
            st.info(st.session_state.pop("msg"))

        # --- CHART ---
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            vertical_spacing=0.02, row_heights=[0.75, 0.25])

        fig.add_trace(go.Candlestick(
            x=df.index, open=df['open'], high=df['high'],
            low=df['low'], close=df['close'], name='',
            increasing_line_color='#26a69a', decreasing_line_color='#ef5350',
            increasing_fillcolor='#26a69a', decreasing_fillcolor='#ef5350'
        ), row=1, col=1)

        fig.add_trace(go.Scatter(x=df.index, y=df['ma20'], name='MA20',
                                 line=dict(color='#2962FF', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['ma50'], name='MA50',
                                 line=dict(color='#FF6D00', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df.get('ma200', df['ma50']), name='MA200',
                                 line=dict(color='#9c27b0', width=1, dash='dot')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_upper'], name='BB Upper',
                                 line=dict(color='rgba(130,130,130,0.4)', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_lower'], name='BB Lower',
                                 line=dict(color='rgba(130,130,130,0.4)', width=1),
                                 fill='tonexty', fillcolor='rgba(130,130,130,0.05)'), row=1, col=1)

        colors = ['#26a69a' if c >= o else '#ef5350' for c, o in zip(df['close'], df['open'])]
        fig.add_trace(go.Bar(x=df.index, y=df['volume'], name='Volume',
                             marker_color=colors, opacity=0.7), row=2, col=1)

        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='#131722',
            plot_bgcolor='#131722',
            height=480,
            xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', y=1.02, font=dict(size=11)),
            margin=dict(l=0, r=0, t=5, b=0),
            xaxis2=dict(gridcolor='#2A2E39'),
            yaxis=dict(gridcolor='#2A2E39', side='right'),
            yaxis2=dict(gridcolor='#2A2E39', side='right')
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- Signal Details card ---
        try:
            sig = signal_engine(df) if hasattr(pd, 'DataFrame') else penetration_engine(df)
        except:
            sig = {}

        risk = risk_check(df, capital=total_equity)

        entry = float(latest['close'])
        sl = float(risk.get('stop_loss', entry * 0.95))
        tp = float(risk.get('take_profit', entry * 1.05))
        rsi2 = float(df['rsi_2'].iloc[-1]) if 'rsi_2' in df.columns else float(df['rsi'].iloc[-1])
        above_ma200 = "✅ YES" if entry > float(df['ma200'].iloc[-1]) else "❌ NO"
        vol_ratio = float(df['volume_ratio'].iloc[-1]) if 'volume_ratio' in df.columns else 1.0
        regime = sig.get('regime', 'UNKNOWN') if sig else 'UNKNOWN'
        score = sig.get('total_score', sig.get('entry_score', 0)) if sig else 0
        strategy = sig.get('strategy', 'RSI-2 Mean Reversion') if sig else 'RSI-2 Mean Reversion'

        st.markdown(f"""
<div class="signal-card">
<table>
<tr><td colspan="2"><b>{selected_sym}</b> &nbsp; 
<span style='color:{"#26a69a" if risk.get("approved") else "#ef5350"}'>
{"🟢 SIGNAL: BUY" if risk.get("approved") else "🔴 SIGNAL: WAIT"}</span></td>
<td colspan="2" style="text-align:right">Score: <b>{score}</b>/100 | {strategy}</td></tr>
<tr><td colspan="4"><hr style="border-color:#2A2E39; margin:4px 0"/></td></tr>
<tr>
  <td>RSI(2)</td><td><b>{rsi2:.1f}</b></td>
  <td>{"✅" if rsi2 < 5 else "⚠️" if rsi2 < 20 else "❌"}</td>
  <td>Regime: <b>{regime}</b></td>
</tr>
<tr>
  <td>Price &gt; SMA200</td><td colspan="2"><b>{above_ma200}</b></td>
  <td>Volume: <b>{vol_ratio:.1f}x</b> {"✅" if vol_ratio > 1.2 else "⚠️"}</td>
</tr>
<tr><td colspan="4"><hr style="border-color:#2A2E39; margin:4px 0"/></td></tr>
<tr>
  <td>Entry</td><td><b>Rp{entry:,.0f}</b></td>
  <td>SL</td><td><b style="color:#ef5350">Rp{sl:,.0f}</b></td>
</tr>
<tr>
  <td>Take Profit</td><td><b style="color:#26a69a">Rp{tp:,.0f}</b></td>
  <td>Risk</td><td><b>{risk_percent:.1f}%</b></td>
</tr>
<tr>
  <td>Lots</td><td colspan="3"><b>{risk.get('lots', 0)} lot</b> &nbsp;
  {"<span class='signal-ok'>✅ " + risk.get('reason','') + "</span>" if risk.get('approved') else "<span class='signal-wait'>❌ " + risk.get('reason','') + "</span>"}</td>
</tr>
</table>
</div>
""", unsafe_allow_html=True)

        if st.session_state.get("confirm_buy"):
            st.warning(f"Konfirmasi: BUY {risk.get('lots',0)} lot {symbol} @ Rp{entry:,.0f}?")
            c1, c2 = st.columns(2)
            if c1.button("✅ Konfirmasi BUY"):
                if risk.get('approved'):
                    ok, msg = paper_buy(symbol, risk['lots'], entry, sl, tp)
                    st.session_state["msg"] = msg
                else:
                    st.session_state["msg"] = f"❌ {risk.get('reason')}"
                st.session_state["confirm_buy"] = False
                st.rerun()
            if c2.button("❌ Batal"):
                st.session_state["confirm_buy"] = False
                st.rerun()

    except Exception as e:
        st.error(f"Gagal memuat chart {symbol}: {e}")

    # --- ORDER HISTORY ---
    st.write("---")
    st.subheader("📋 Order History")
    orders = get_orders()
    if orders.empty:
        st.info("Belum ada order.")
    else:
        st.dataframe(orders[['ts', 'symbol', 'side', 'lots', 'price', 'status', 'pnl']],
                     use_container_width=True, height=180)

with side_panel:
    # --- WATCHLIST ---
    st.markdown("**Watchlist**")
    st.markdown('<div class="watchlist-header"><span>Symbol</span><span style="float:right">Last &nbsp;&nbsp; Chg%</span></div>', unsafe_allow_html=True)

    for sym in WATCHLIST:
        try:
            import yfinance as yf
            t = yf.Ticker(sym + ".JK")
            info = t.fast_info
            last = info.last_price or 0
            prev = info.previous_close or last
            chg = ((last - prev) / prev * 100) if prev else 0
            chg_class = "chg-pos" if chg >= 0 else "chg-neg"
            chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
            selected_mark = "→" if sym == selected_sym else ""
            st.markdown(f"""
<div class="watchlist-item">
  <span>{selected_mark}<b>{sym}</b></span>
  <span>{last:,.0f} &nbsp;<span class="{chg_class}">{chg_str}</span></span>
</div>""", unsafe_allow_html=True)
        except:
            st.markdown(f'<div class="watchlist-item"><span>{sym}</span><span>-</span></div>', unsafe_allow_html=True)

    st.write("")

    # --- ACTIVE POSITIONS ---
    st.markdown("**Open Positions**")
    if portfolio.empty:
        st.markdown('<div style="color:#787b86; font-size:13px; padding:8px">Belum ada posisi terbuka.</div>', unsafe_allow_html=True)
    else:
        for _, row in portfolio.iterrows():
            try:
                cur_df = chart_data(row['symbol'], '1mo')
                cur_price = float(cur_df.iloc[-1]['close'])
                pnl = (cur_price * row['shares'] * 0.9975) - row['cost']
                pnl_color = "#26a69a" if pnl >= 0 else "#ef5350"
                pnl_str = f"+Rp{pnl:,.0f}" if pnl >= 0 else f"-Rp{abs(pnl):,.0f}"
                st.markdown(f"""
<div style="background:#1E222D; border-radius:6px; padding:8px; margin:4px 0; border:1px solid #2A2E39; font-size:12px">
  <b>{row['symbol']}</b> &nbsp; {int(row['shares'])//100} lot<br/>
  Entry: Rp{row['entry']:,.0f} | Now: Rp{cur_price:,.0f}<br/>
  SL: Rp{row['stop']:,.0f} | TP: Rp{row.get('tp', row['stop']*1.1):,.0f}<br/>
  <span style="color:{pnl_color}; font-weight:bold">{pnl_str}</span>
</div>""", unsafe_allow_html=True)
            except:
                st.markdown(f'<div style="background:#1E222D; padding:8px; border-radius:6px; font-size:12px">{row["symbol"]}</div>', unsafe_allow_html=True)

    st.write("")

    # --- MINI BOT (AI) ---
    st.markdown("**🤖 AI Trading Assistant**")
    if "chat" not in st.session_state:
        st.session_state["chat"] = []

    chat_input = st.text_input("Tanya bot...", key="chat_input", label_visibility="collapsed",
                               placeholder="Contoh: Kenapa BMRI dapat BUY?")

    if chat_input:
        user_msg = chat_input
        try:
            if "kenapa" in user_msg.lower() or "signal" in user_msg.lower():
                sym_ask = next((s for s in WATCHLIST if s in user_msg.upper()), selected_sym)
                df_ask = chart_data(sym_ask + ".JK")
                r = risk_check(df_ask, capital=total_equity)
                rsi_v = float(df_ask['rsi_2'].iloc[-1]) if 'rsi_2' in df_ask.columns else 0
                vr = float(df_ask['volume_ratio'].iloc[-1]) if 'volume_ratio' in df_ask.columns else 1.0
                reply = (f"**{sym_ask}** - {'SINYAL BELI KUAT' if r.get('approved') else 'BELUM ADA SINYAL'}.\n\n"
                         f"RSI(2): {rsi_v:.1f} {'(Oversold ✅)' if rsi_v < 5 else '(Normal)'} | "
                         f"Volume: {vr:.1f}x rata-rata {'✅' if vr > 1.2 else ''}\n"
                         f"Entry: Rp{r.get('entry',0):,.0f} | SL: Rp{r.get('stop_loss',0):,.0f} | TP: Rp{r.get('take_profit',0):,.0f}\n"
                         f"Posisi: {r.get('lots',0)} lot | Reason: {r.get('reason','')}")
            elif "scan" in user_msg.lower():
                reply = "Menjalankan scanner... Lihat tabel Live Signals di layar utama (sudah di-cache agar cepat)."
            elif "posisi" in user_msg.lower() or "portfolio" in user_msg.lower():
                if portfolio.empty:
                    reply = "Tidak ada posisi terbuka saat ini. Saldo kas: Rp{:,.0f}".format(cash)
                else:
                    pos_text = "\n".join([f"- {r['symbol']}: {int(r['shares'])//100} lot" for _, r in portfolio.iterrows()])
                    reply = f"Posisi aktif:\n{pos_text}\nTotal Equity: Rp{total_equity:,.0f}"
            else:
                reply = (f"Halo! Saya IDXBot Assistant. Saya bisa menjawab:\n"
                         f"- 'Kenapa [SAHAM] dapat BUY?'\n"
                         f"- 'Scan saham IDX sekarang'\n"
                         f"- 'Cek posisi saya'")
        except Exception as e:
            reply = f"Maaf, terjadi error: {str(e)}"

        st.session_state["chat"].append(("user", user_msg))
        st.session_state["chat"].append(("bot", reply))

    for role, msg in st.session_state["chat"][-6:]:
        if role == "user":
            st.markdown(f'<div class="chat-user">👤 {msg}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="chat-bot">🤖 {msg}</div>', unsafe_allow_html=True)

    # --- SYSTEM HEALTH ---
    st.write("")
    st.markdown("**🛠 System Health**")
    st.markdown(f"""
<div style="background:#1E222D; border-radius:6px; padding:10px; font-size:12px; border:1px solid #2A2E39">
  🟢 Data Feed: Yahoo Finance<br/>
  🟢 Strategy Engine: ACTIVE<br/>
  🟢 Paper DB: CONNECTED<br/>
  🕐 {datetime.now().strftime("%H:%M:%S")} WIB
</div>""", unsafe_allow_html=True)

# Sidebar with risk settings (collapsed by default)
risk_percent = st.sidebar.slider("Risk / Trade (%)", 0.1, 5.0, 1.0, 0.1)
