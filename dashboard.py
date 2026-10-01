"""
IDXBot Trading Terminal — TradingView-style Layout
Layout: Watchlist LEFT | Chart CENTER | Execution RIGHT | Tabs BOTTOM
"""
import os, sqlite3, hashlib
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from engine import (
    get_market_data, calculate_indicators, signal_engine,
    risk_check, INITIAL_CAPITAL, UNIVERSE
)

# ─────────────────────────────────────────
# PAGE CONFIG (must be first)
# ─────────────────────────────────────────
st.set_page_config(
    page_title="IDXBot Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────
# GLOBAL CSS — dark terminal skin
# ─────────────────────────────────────────
st.markdown("""
<style>
/* Base */
.stApp { background:#131722 !important; color:#D1D4DC !important; }
section[data-testid="stSidebar"] { background:#1E222D !important; }
.block-container { padding:0 !important; max-width:100% !important; }
div[data-testid="stVerticalBlock"] { gap:0 !important; }

/* Hide default decorations */
#MainMenu, footer, header { visibility:hidden; }

/* Compact metric */
[data-testid="metric-container"] {
    background:#1E222D; border-radius:4px;
    padding:6px 10px; border:1px solid #2A2E39;
}
[data-testid="metric-container"] label { font-size:11px !important; color:#787b86 !important; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { font-size:15px !important; }

/* Watchlist */
.wl-item { display:flex; justify-content:space-between; align-items:center;
           padding:7px 10px; border-bottom:1px solid #2A2E39;
           cursor:pointer; font-size:13px; }
.wl-item:hover { background:#2A2E39; border-radius:4px; }
.wl-sym { font-weight:600; color:#D1D4DC; }
.wl-price { color:#D1D4DC; }
.wl-up { color:#26a69a; font-size:12px; }
.wl-dn { color:#ef5350; font-size:12px; }
.wl-active { background:#1a3a5c !important; border-radius:4px; border-left:3px solid #2962FF; }

/* Signal card */
.sig-card { background:#1E222D; border:1px solid #2A2E39;
            border-radius:6px; padding:12px; font-size:12px; }
.sig-ok  { color:#26a69a; font-weight:700; }
.sig-bad { color:#ef5350; font-weight:700; }
.sig-row { display:flex; justify-content:space-between;
           padding:3px 0; border-bottom:1px solid #2A2E39; }

/* BUY / SELL override */
div[data-testid="stButton"] > button.buy-btn {
    background:#26a69a !important; color:#fff !important;
    font-weight:700 !important; border-radius:4px !important; }
div[data-testid="stButton"] > button.sell-btn {
    background:#ef5350 !important; color:#fff !important;
    font-weight:700 !important; border-radius:4px !important; }

/* Bottom tabs */
div[data-testid="stTabs"] button { font-size:13px !important; }

/* Chat */
.chat-u { background:#2A2E39; padding:7px 10px; border-radius:6px; margin:3px 0; font-size:12px; }
.chat-b { background:#1E2844; padding:7px 10px; border-radius:6px; margin:3px 0; font-size:12px; }

div.pos-card {
    background:#1E222D; border:1px solid #2A2E39;
    border-radius:6px; padding:10px; margin:4px 0; font-size:12px;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────
def _hash(p): return hashlib.sha256(p.encode()).hexdigest()

def show_login():
    _, mid, _ = st.columns([1,1.5,1])
    with mid:
        st.markdown("## 📈 IDXBot Trading Terminal")
        st.markdown("*Paper Trading Mode*")
        os.makedirs("data", exist_ok=True)
        with sqlite3.connect("data/paper.db") as c:
            c.execute("CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, pw TEXT)")
            c.execute("INSERT OR IGNORE INTO users VALUES(?,?)", ("deathknight666", _hash("Xnunxer123*")))
            c.commit()
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Masuk →", use_container_width=True):
                with sqlite3.connect("data/paper.db") as c:
                    row = c.execute("SELECT pw FROM users WHERE username=?", (u,)).fetchone()
                if row and row[0] == _hash(p):
                    st.session_state.update({"logged_in":True, "username":u})
                    st.rerun()
                else:
                    st.error("Username/password salah")

if not st.session_state.get("logged_in"):
    show_login(); st.stop()

# ─────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────
DB = "data/paper.db"

def db_init():
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect(DB) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS positions(
            symbol TEXT PRIMARY KEY, shares INT,
            entry REAL, stop REAL, tp REAL, entry_date TEXT, cost REAL);
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, symbol TEXT, side TEXT, lots INT,
            price REAL, status TEXT, reason TEXT, pnl REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v REAL);
        """)
        if not c.execute("SELECT 1 FROM kv WHERE k='cash'").fetchone():
            c.execute("INSERT INTO kv VALUES('cash',?)", (INITIAL_CAPITAL,))
        c.commit()

def get_cash():
    db_init()
    with sqlite3.connect(DB) as c:
        return float(c.execute("SELECT v FROM kv WHERE k='cash'").fetchone()[0])

def get_positions():
    db_init()
    with sqlite3.connect(DB) as c:
        return pd.read_sql("SELECT * FROM positions", c)

def get_orders_df():
    db_init()
    with sqlite3.connect(DB) as c:
        return pd.read_sql("SELECT * FROM orders ORDER BY id DESC LIMIT 50", c)

def paper_buy(symbol, lots, price, sl, tp):
    db_init()
    shares = int(lots) * 100
    cost   = shares * price * 1.0015
    now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB) as c:
        cash = float(c.execute("SELECT v FROM kv WHERE k='cash'").fetchone()[0])
        n_pos = c.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        invested = c.execute("SELECT COALESCE(SUM(cost),0) FROM positions").fetchone()[0]
        if cash < cost:      return False, "❌ Saldo tidak cukup"
        if n_pos >= 5:       return False, "❌ Maks 5 posisi aktif"
        if (invested+cost) > (cash+invested)*0.6: return False, "❌ Maks exposure 60%"
        c.execute("UPDATE kv SET v=v-? WHERE k='cash'", (cost,))
        c.execute("INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?,?,?)",
                  (symbol, shares, price, sl, tp, now, cost))
        c.execute("INSERT INTO orders(ts,symbol,side,lots,price,status,reason,pnl) VALUES(?,?,?,?,?,?,?,?)",
                  (now, symbol, "BUY", lots, price, "FILLED", "MANUAL", 0))
        c.commit()
    return True, f"✅ BUY {lots} lot {symbol} @ Rp{price:,.0f}"

def paper_sell(symbol, price, reason="MANUAL"):
    db_init()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB) as c:
        pos = c.execute("SELECT shares,cost FROM positions WHERE symbol=?", (symbol,)).fetchone()
        if not pos: return False, "❌ Tidak ada posisi"
        shares, cost = pos
        lots = shares // 100
        net  = shares * price * 0.9975
        pnl  = net - cost
        c.execute("UPDATE kv SET v=v+? WHERE k='cash'", (net,))
        c.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        c.execute("INSERT INTO orders(ts,symbol,side,lots,price,status,reason,pnl) VALUES(?,?,?,?,?,?,?,?)",
                  (now, symbol, "SELL", lots, price, "FILLED", reason, pnl))
        c.commit()
    sign = "+" if pnl >= 0 else "-"
    return True, f"✅ SELL {symbol} @ Rp{price:,.0f} | PnL {sign}Rp{abs(pnl):,.0f}"

db_init()

# ─────────────────────────────────────────
# DATA CACHE
# ─────────────────────────────────────────
@st.cache_data(ttl=60)
def load_chart(symbol, period="1y"):
    df = get_market_data(symbol, period=period)
    return calculate_indicators(df)

@st.cache_data(ttl=60)
def load_price(symbol):
    """Return (last_price, change_pct) quickly via recent data."""
    try:
        df = get_market_data(symbol, period="5d")
        last  = float(df['close'].iloc[-1])
        prev  = float(df['close'].iloc[-2])
        return last, (last-prev)/prev*100
    except:
        return 0.0, 0.0

# ─────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────
WATCHLIST = [s.replace(".JK","") for s in UNIVERSE[:15]]
if "sym" not in st.session_state:
    st.session_state["sym"] = "BBCA"
if "period" not in st.session_state:
    st.session_state["period"] = "1y"
if "chat" not in st.session_state:
    st.session_state["chat"] = []
if "confirm_buy" not in st.session_state:
    st.session_state["confirm_buy"] = False

selected = st.session_state["sym"]
symbol   = selected + ".JK"

# ─────────────────────────────────────────
# TOP BAR
# ─────────────────────────────────────────
positions = get_positions()
cash      = get_cash()
invested  = float(positions['cost'].sum()) if not positions.empty else 0
equity    = cash + invested

# Load chart data early (used in top bar price)
try:
    df = load_chart(symbol, st.session_state["period"])
    last_price = float(df['close'].iloc[-1])
    prev_price = float(df['close'].iloc[-2])
    chg_pct    = (last_price - prev_price) / prev_price * 100
    chg_color  = "#26a69a" if chg_pct >= 0 else "#ef5350"
    chg_sign   = "▲" if chg_pct >= 0 else "▼"
    data_ok    = True
except Exception as e:
    df, last_price, chg_pct, chg_color, chg_sign = None, 0, 0, "#787b86", "─"
    data_ok = False

t1,t2,t3,t4,t5,t6,t7,t8 = st.columns([1.2,1.5,0.8,0.8,0.8,0.8,0.8,0.8])
t1.markdown(f"<b style='font-size:16px'>📈 IDXBot</b> &nbsp;"
            f"<span style='color:#26a69a;font-size:11px'>● PAPER</span>",
            unsafe_allow_html=True)
t2.markdown(f"<span style='font-size:20px;font-weight:700'>{selected} &nbsp;"
            f"<span style='color:{chg_color}'>{last_price:,.0f} {chg_sign}{abs(chg_pct):.2f}%</span></span>",
            unsafe_allow_html=True)
t3.metric("Equity",    f"Rp{equity/1e6:.1f}M")
t4.metric("Cash",      f"Rp{cash/1e6:.1f}M")
t5.metric("Invested",  f"Rp{invested/1e6:.1f}M")
t6.metric("Positions", f"{len(positions)}/5")

period_opts = {"1m":"1mo","3m":"3mo","6m":"6mo","1y":"1y","3y":"3y"}
chosen = t7.selectbox("", list(period_opts.keys()), index=3, label_visibility="collapsed")
if period_opts[chosen] != st.session_state["period"]:
    st.session_state["period"] = period_opts[chosen]
    st.rerun()

if t8.button("🚪 Logout"):
    st.session_state["logged_in"] = False
    st.rerun()

# Flash messages
if "flash" in st.session_state:
    msg = st.session_state.pop("flash")
    (st.success if msg.startswith("✅") else st.error)(msg)

st.markdown("<hr style='margin:4px 0; border-color:#2A2E39'>", unsafe_allow_html=True)

# ─────────────────────────────────────────
# MAIN LAYOUT: LEFT | CENTER | RIGHT
# ─────────────────────────────────────────
left, center, right = st.columns([1, 4, 1.4], gap="small")

# ══════════════════════════
# LEFT — Watchlist
# ══════════════════════════
with left:
    st.markdown("<div style='padding:8px 4px;font-size:11px;color:#787b86;font-weight:700;"
                "border-bottom:1px solid #2A2E39'>WATCHLIST</div>", unsafe_allow_html=True)
    
    for sym in WATCHLIST:
        price, pct = load_price(sym + ".JK")
        is_active = sym == selected
        pct_color = "#26a69a" if pct >= 0 else "#ef5350"
        pct_sign  = "+" if pct >= 0 else ""
        active_style = "background:#1a3a5c; border-left:3px solid #2962FF; border-radius:4px;" if is_active else ""
        
        # Check bot signal for this symbol
        signal_badge = ""
        try:
            df_wl = load_chart(sym + ".JK", "3mo")
            r_wl = risk_check(df_wl, capital=equity)
            if r_wl.get('approved'):
                signal_badge = "<span style='color:#26a69a;font-size:9px'>● BUY</span>"
        except:
            pass
        
        st.markdown(f"""
<div class="wl-item" style="{active_style}">
  <div>
    <span class="wl-sym">{sym}</span>
    {signal_badge}
  </div>
  <div style="text-align:right">
    <div class="wl-price">{price:,.0f}</div>
    <div style="color:{pct_color};font-size:11px">{pct_sign}{pct:.2f}%</div>
  </div>
</div>""", unsafe_allow_html=True)
        
        if st.button(sym, key=f"wl_{sym}", use_container_width=True,
                     help=f"Switch to {sym}"):
            st.session_state["sym"] = sym
            st.rerun()

    st.markdown("<div style='padding:8px 4px;font-size:11px;color:#787b86;font-weight:700;"
                "border-top:1px solid #2A2E39;margin-top:8px'>BOT SCAN</div>", unsafe_allow_html=True)
    buy_count = wait_count = 0
    for sym in WATCHLIST:
        try:
            df_scan = load_chart(sym + ".JK", "3mo")
            r = risk_check(df_scan, capital=equity)
            if r.get('approved'): buy_count += 1
            else: wait_count += 1
        except:
            wait_count += 1
    st.markdown(f"""
<div style="padding:8px;font-size:12px">
  🟢 BUY &nbsp;&nbsp;&nbsp; <b>{buy_count}</b><br/>
  🟡 WAIT &nbsp; <b>{wait_count}</b>
</div>""", unsafe_allow_html=True)

# ══════════════════════════
# CENTER — Chart
# ══════════════════════════
with center:
    if not data_ok:
        st.error(f"Gagal memuat data {symbol}")
    else:
        # Compute signal & risk
        try:
            sig  = signal_engine(df)
        except:
            sig  = {}
        risk = risk_check(df, capital=equity)
        
        latest    = df.iloc[-1]
        entry_px  = float(latest['close'])
        sl_px     = float(risk.get('stop_loss', entry_px * 0.95))
        tp_px     = float(risk.get('take_profit', entry_px * 1.05))
        rsi2_val  = float(df['rsi_2'].iloc[-1]) if 'rsi_2' in df.columns else float(df['rsi'].iloc[-1])
        ma200_val = float(df['ma200'].iloc[-1]) if 'ma200' in df.columns else 0
        vol_ratio = float(df['volume_ratio'].iloc[-1]) if 'volume_ratio' in df.columns else 1.0
        
        # ── CHART ──
        fig = make_subplots(
            rows=3, cols=1, shared_xaxes=True,
            vertical_spacing=0.01,
            row_heights=[0.65, 0.15, 0.20],
            subplot_titles=("", "", "RSI(2)")
        )
        
        # Candlestick
        fig.add_trace(go.Candlestick(
            x=df.index, open=df['open'], high=df['high'],
            low=df['low'],  close=df['close'],
            name="",
            increasing_line_color='#26a69a', decreasing_line_color='#ef5350',
            increasing_fillcolor='#26a69a',  decreasing_fillcolor='#ef5350',
        ), row=1, col=1)
        
        # MAs
        fig.add_trace(go.Scatter(x=df.index, y=df['ma20'],  name='MA20',
                                 line=dict(color='#2962FF', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['ma50'],  name='MA50',
                                 line=dict(color='#FF6D00', width=1.5)), row=1, col=1)
        if 'ma200' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['ma200'], name='MA200',
                                     line=dict(color='#9c27b0', width=1, dash='dot')), row=1, col=1)
        
        # Bollinger Bands
        if 'bb_upper' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['bb_upper'], name='BB',
                                     line=dict(color='rgba(120,120,120,0.4)', width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['bb_lower'], name='',
                                     line=dict(color='rgba(120,120,120,0.4)', width=1),
                                     fill='tonexty', fillcolor='rgba(120,120,120,0.05)',
                                     showlegend=False), row=1, col=1)
        
        # SL / TP horizontal lines (last 60 bars)
        recent_dates = df.index[-60:]
        if risk.get('approved'):
            fig.add_trace(go.Scatter(
                x=[recent_dates[0], recent_dates[-1]], y=[tp_px, tp_px],
                mode='lines', name='TP', line=dict(color='#26a69a', width=1.5, dash='dash')
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=[recent_dates[0], recent_dates[-1]], y=[sl_px, sl_px],
                mode='lines', name='SL', line=dict(color='#ef5350', width=1.5, dash='dash')
            ), row=1, col=1)
            # Entry annotation
            fig.add_annotation(
                x=recent_dates[-1], y=entry_px,
                text=f"🟢 BUY {entry_px:,.0f}", showarrow=False,
                font=dict(color='#26a69a', size=11), bgcolor='#1a3a2a',
                bordercolor='#26a69a', borderwidth=1, xanchor='right'
            )
            fig.add_annotation(
                x=recent_dates[-1], y=tp_px,
                text=f"TP {tp_px:,.0f}", showarrow=False,
                font=dict(color='#26a69a', size=10), bgcolor='#1a3a2a',
                bordercolor='#26a69a', borderwidth=1, xanchor='right'
            )
            fig.add_annotation(
                x=recent_dates[-1], y=sl_px,
                text=f"SL {sl_px:,.0f}", showarrow=False,
                font=dict(color='#ef5350', size=10), bgcolor='#3a1a1a',
                bordercolor='#ef5350', borderwidth=1, xanchor='right'
            )
        
        # Active position marker
        if not positions.empty and symbol in positions['symbol'].values:
            pos_row = positions[positions['symbol'] == symbol].iloc[0]
            entry_val = float(pos_row['entry'])
            fig.add_hline(y=entry_val, line_color='#FFD700', line_dash='dot',
                          line_width=1.5, row=1, col=1,
                          annotation_text=f"📍 Position {entry_val:,.0f}",
                          annotation_font_color='#FFD700')
        
        # Volume
        colors = ['#26a69a' if c >= o else '#ef5350'
                  for c, o in zip(df['close'], df['open'])]
        fig.add_trace(go.Bar(x=df.index, y=df['volume'],
                             marker_color=colors, opacity=0.6, name='Vol',
                             showlegend=False), row=2, col=1)
        
        # RSI(2)
        rsi_col = 'rsi_2' if 'rsi_2' in df.columns else 'rsi'
        fig.add_trace(go.Scatter(x=df.index, y=df[rsi_col], name='RSI(2)',
                                 line=dict(color='#FF6D00', width=1.5),
                                 showlegend=False), row=3, col=1)
        fig.add_hline(y=5,  line_color='#26a69a', line_dash='dash', line_width=1, row=3, col=1)
        fig.add_hline(y=80, line_color='#ef5350', line_dash='dash', line_width=1, row=3, col=1)
        
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='#131722', plot_bgcolor='#131722',
            height=520,
            xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', y=1.01, x=0, font=dict(size=10)),
            margin=dict(l=0, r=0, t=5, b=0),
            xaxis3=dict(gridcolor='#2A2E39'),
            yaxis=dict(gridcolor='#2A2E39', side='right'),
            yaxis2=dict(gridcolor='#2A2E39', side='right'),
            yaxis3=dict(gridcolor='#2A2E39', side='right', range=[0, 100]),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ══════════════════════════
# RIGHT — Order / Bot Panel
# ══════════════════════════
with right:
    st.markdown(f"""
<div style='background:#1E222D;border:1px solid #2A2E39;border-radius:6px;padding:12px;margin-bottom:8px'>
  <div style='font-size:18px;font-weight:700'>{selected}.JK</div>
  <div style='font-size:22px;color:{chg_color};font-weight:700'>
    Rp{last_price:,.0f}
    <span style='font-size:14px'>{chg_sign}{abs(chg_pct):.2f}%</span>
  </div>
</div>""", unsafe_allow_html=True)

    # Buy/Sell buttons
    b1, b2 = st.columns(2)
    do_buy  = b1.button("🟢 BUY",  use_container_width=True, key="main_buy")
    do_sell = b2.button("🔴 SELL", use_container_width=True, key="main_sell")
    
    if data_ok:
        risk = risk_check(df, capital=equity)
        sl_px   = float(risk.get('stop_loss',   last_price * 0.95))
        tp_px   = float(risk.get('take_profit', last_price * 1.05))
        lots_rc = int(risk.get('lots', 0))
    else:
        risk = {}; sl_px = 0; tp_px = 0; lots_rc = 0
    
    # Lot override
    lots_input = st.number_input("Quantity (lot)", min_value=1,
                                  value=max(1, lots_rc), step=1)
    
    c1, c2 = st.columns(2)
    sl_input = c1.number_input("Stop Loss", value=int(sl_px), step=50)
    tp_input = c2.number_input("Take Profit", value=int(tp_px), step=50)
    
    risk_rp = lots_input * 100 * (last_price - sl_input) if sl_input else 0
    st.markdown(f"<div style='font-size:11px;color:#787b86;margin:4px 0'>"
                f"Est. Risk: <b style='color:#ef5350'>Rp{risk_rp:,.0f}</b></div>",
                unsafe_allow_html=True)
    
    if do_buy:
        ok, msg = paper_buy(symbol, lots_input, last_price, sl_input, tp_input)
        st.session_state["flash"] = msg
        if ok: st.cache_data.clear()
        st.rerun()
    
    if do_sell:
        if symbol in positions['symbol'].values:
            ok, msg = paper_sell(symbol, last_price)
            st.session_state["flash"] = msg
            if ok: st.cache_data.clear()
            st.rerun()
        else:
            st.session_state["flash"] = "❌ Tidak ada posisi untuk dijual"
            st.rerun()
    
    st.markdown("<hr style='border-color:#2A2E39;margin:8px 0'>", unsafe_allow_html=True)
    
    # ── BOT ANALYSIS ──
    if data_ok:
        try:
            sig      = signal_engine(df)
            score    = sig.get('total_score', 0)
            regime   = sig.get('regime', 'UNKNOWN')
            strategy = sig.get('strategy', 'Multi-Strategy')
            breakdown = sig.get('score_breakdown', {})
            approved = risk.get('approved', False)
        except Exception as e:
            score = 0; regime = "UNKNOWN"; strategy = "N/A"
            breakdown = {}; approved = False
        
        sig_color = "#26a69a" if approved else "#ef5350"
        sig_label = "🟢 BUY" if approved else "🔴 WAIT"
        
        # Score bar
        bar_w  = max(0, min(100, score))
        bar_c  = "#26a69a" if score >= 65 else "#FF6D00" if score >= 50 else "#ef5350"
        
        # Build breakdown rows
        bd_labels = {
            "regime": "Market Regime", "liquidity": "Liquidity",
            "rsi_2": "RSI-2 Connors", "trend": "Trend Following",
            "breakout": "Breakout", "mean_reversion": "Bollinger Rev.",
            "volume": "Volume Intel", "support_proximity": "Near Support",
        }
        bd_html = ""
        for k, label in bd_labels.items():
            v = breakdown.get(k, 0)
            if v == 0:
                continue
            max_v = {"regime":15,"liquidity":8,"rsi_2":25,"trend":20,
                     "breakout":20,"mean_reversion":20,"volume":15,"support_proximity":7}.get(k,10)
            pct = max(0, min(100, int(v / max_v * 100)))
            color = "#26a69a" if v > 0 else "#ef5350"
            bd_html += f"""
<div style="display:flex;align-items:center;gap:6px;padding:2px 0;">
  <span style="width:90px;font-size:10px;color:#787b86">{label}</span>
  <div style="flex:1;background:#2A2E39;border-radius:2px;height:6px">
    <div style="width:{pct}%;background:{color};height:6px;border-radius:2px"></div>
  </div>
  <span style="width:24px;font-size:10px;color:{color};font-weight:700">{v:+.0f}</span>
</div>"""
        
        st.markdown(f"""
<div class="sig-card">
  <div style="font-size:12px;font-weight:700;color:#787b86;margin-bottom:4px">🤖 BOT ANALYSIS</div>
  <div style="font-size:18px;font-weight:700;color:{sig_color}">{sig_label}</div>
  <div style="font-size:11px;color:#787b86;margin-bottom:6px">{strategy}</div>
  
  <div style="display:flex;justify-content:space-between;margin-bottom:4px">
    <span style="font-size:11px;color:#787b86">Score</span>
    <span style="font-size:14px;font-weight:700;color:{bar_c}">{score}/100</span>
  </div>
  <div style="background:#2A2E39;border-radius:4px;height:8px;margin-bottom:8px">
    <div style="width:{bar_w}%;background:{bar_c};height:8px;border-radius:4px"></div>
  </div>
  
  <div style="font-size:10px;color:#787b86;font-weight:700;margin-bottom:4px">SCORE BREAKDOWN</div>
  {bd_html}
  
  <div style="font-size:10px;color:#787b86;font-weight:700;margin-top:8px;margin-bottom:4px">TRADE PLAN</div>
  <div class="sig-row"><span>Regime</span><b>{regime}</b></div>
  <div class="sig-row"><span>Entry</span><b>Rp{last_price:,.0f}</b></div>
  <div class="sig-row"><span>Stop Loss</span><b style="color:#ef5350">Rp{sl_px:,.0f}</b></div>
  <div class="sig-row"><span>Take Profit</span><b style="color:#26a69a">Rp{tp_px:,.0f}</b></div>
  <div class="sig-row"><span>Lots</span><b>{lots_rc} lot</b></div>
  <div style="font-size:10px;color:#787b86;margin-top:4px">{risk.get("reason","")}</div>
</div>""", unsafe_allow_html=True)
    
    st.markdown("<hr style='border-color:#2A2E39;margin:8px 0'>", unsafe_allow_html=True)
    
    # ── AI CHATBOT ──
    st.markdown("<div style='font-size:12px;font-weight:700;margin-bottom:4px'>🤖 AI Assistant</div>",
                unsafe_allow_html=True)
    
    chat_inp = st.text_input("", placeholder="Tanya: 'Kenapa BBCA BUY?'",
                             label_visibility="collapsed", key="chat_inp")
    if chat_inp:
        q = chat_inp.lower()
        try:
            if any(s in chat_inp.upper() for s in WATCHLIST):
                ask_sym = next(s for s in WATCHLIST if s in chat_inp.upper())
                df_ask  = load_chart(ask_sym + ".JK", "3mo")
                r_ask   = risk_check(df_ask, capital=equity)
                rsi_v   = float(df_ask['rsi_2'].iloc[-1]) if 'rsi_2' in df_ask.columns else 0
                vr_v    = float(df_ask['volume_ratio'].iloc[-1]) if 'volume_ratio' in df_ask.columns else 1.0
                reply   = (f"**{ask_sym}** — {'🟢 SINYAL BUY' if r_ask.get('approved') else '🔴 WAIT'}\n"
                           f"RSI(2): {rsi_v:.1f} | Volume: {vr_v:.1f}x\n"
                           f"Entry: Rp{r_ask.get('entry',0):,.0f} | "
                           f"SL: Rp{r_ask.get('stop_loss',0):,.0f} | "
                           f"TP: Rp{r_ask.get('take_profit',0):,.0f}\n"
                           f"{r_ask.get('reason','')}")
            elif "posisi" in q or "portfolio" in q:
                if positions.empty:
                    reply = f"Tidak ada posisi. Kas: Rp{cash:,.0f}"
                else:
                    lines = [f"{r['symbol']}: {int(r['shares'])//100} lot @ Rp{r['entry']:,.0f}"
                             for _, r in positions.iterrows()]
                    reply = "Posisi aktif:\n" + "\n".join(lines)
            elif "scan" in q or "sinyal" in q:
                buys = [s for s in WATCHLIST[:8]
                        if risk_check(load_chart(s+".JK","3mo"), capital=equity).get('approved')]
                reply = f"Sinyal BUY: {', '.join(buys) if buys else 'Tidak ada saat ini'}"
            else:
                reply = ("Saya bisa menjawab:\n"
                         "• 'Kenapa BBCA dapat BUY?'\n"
                         "• 'Cek posisi saya'\n"
                         "• 'Ada sinyal apa hari ini?'")
        except Exception as e:
            reply = f"Error: {e}"
        
        st.session_state["chat"].append(("u", chat_inp))
        st.session_state["chat"].append(("b", reply))
    
    for role, msg in st.session_state["chat"][-6:]:
        cls = "chat-u" if role == "u" else "chat-b"
        icon = "👤" if role == "u" else "🤖"
        st.markdown(f'<div class="{cls}">{icon} {msg}</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────
# BOTTOM TABS — Positions | Orders | Signals | Health
# ─────────────────────────────────────────
st.markdown("<hr style='border-color:#2A2E39;margin:4px 0'>", unsafe_allow_html=True)

tab_pos, tab_ord, tab_sig, tab_health = st.tabs(
    ["💼 Positions", "📋 Orders", "📡 Signals", "🛠 System Health"]
)

with tab_pos:
    if positions.empty:
        st.info("Tidak ada posisi aktif.")
    else:
        cols = st.columns(len(positions))
        for i, (_, row) in enumerate(positions.iterrows()):
            with cols[i]:
                try:
                    cur_df = load_chart(row['symbol'], '1mo')
                    cur_px = float(cur_df.iloc[-1]['close'])
                    pnl    = (cur_px * int(row['shares']) * 0.9975) - float(row['cost'])
                    pnl_c  = "#26a69a" if pnl >= 0 else "#ef5350"
                    pnl_s  = f"+Rp{pnl:,.0f}" if pnl >= 0 else f"-Rp{abs(pnl):,.0f}"
                except:
                    cur_px, pnl, pnl_c, pnl_s = row['entry'], 0, "#787b86", "N/A"
                
                st.markdown(f"""
<div class="pos-card">
  <b style="font-size:15px">{row['symbol']}</b> &nbsp;
  <span style="color:#787b86">BUY · {int(row['shares'])//100} lot</span><br/>
  Entry: <b>Rp{row['entry']:,.0f}</b> → Now: <b>Rp{cur_px:,.0f}</b><br/>
  SL: <span style="color:#ef5350">Rp{row['stop']:,.0f}</span> &nbsp;
  TP: <span style="color:#26a69a">Rp{row.get('tp', row['stop']*1.1):,.0f}</span><br/>
  P&L: <b style="color:{pnl_c};font-size:15px">{pnl_s}</b>
</div>""", unsafe_allow_html=True)
                if st.button(f"🔴 Close {row['symbol']}", key=f"close_{row['symbol']}",
                             use_container_width=True):
                    ok, msg = paper_sell(row['symbol'], cur_px, "CLOSE POSITION")
                    st.session_state["flash"] = msg
                    if ok: st.cache_data.clear()
                    st.rerun()

with tab_ord:
    orders = get_orders_df()
    if orders.empty:
        st.info("Belum ada order.")
    else:
        def style_side(val):
            return "color:#26a69a;font-weight:700" if val == "BUY" else "color:#ef5350;font-weight:700"
        def style_pnl(val):
            try:
                return "color:#26a69a" if float(val) >= 0 else "color:#ef5350"
            except:
                return ""
        st.dataframe(
            orders[['ts','symbol','side','lots','price','status','reason','pnl']].style
                .applymap(style_side, subset=['side'])
                .applymap(style_pnl,  subset=['pnl'])
                .format({'price':'{:,.0f}', 'pnl':'{:,.0f}'}),
            use_container_width=True, height=200
        )

with tab_sig:
    st.markdown("**🤖 Bot Scan Results** (Top 15 universe)")
    rows = []
    for sym in WATCHLIST:
        try:
            df_s = load_chart(sym+".JK","3mo")
            r_s  = risk_check(df_s, capital=equity)
            rsi_s = float(df_s['rsi_2'].iloc[-1]) if 'rsi_2' in df_s.columns else float(df_s['rsi'].iloc[-1])
            vr_s  = float(df_s['volume_ratio'].iloc[-1]) if 'volume_ratio' in df_s.columns else 1.0
            rows.append({
                "Symbol": sym, "Last": float(df_s['close'].iloc[-1]),
                "Signal": "🟢 BUY" if r_s.get('approved') else "🔴 WAIT",
                "RSI(2)": round(rsi_s, 1),
                "Vol Ratio": round(vr_s, 2),
                "Lots": r_s.get('lots', 0),
                "Reason": r_s.get('reason','')
            })
        except:
            rows.append({"Symbol": sym, "Signal": "⚠️ ERROR",
                         "Last":0, "RSI(2)":0, "Vol Ratio":0, "Lots":0, "Reason":""})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=300)

with tab_health:
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Data Feed", "🟢 Yahoo Finance")
    h2.metric("Paper DB",  "🟢 SQLite Connected")
    h3.metric("Strategy",  "🟢 RSI-2 + Multi")
    h4.metric("Last Scan", datetime.now().strftime("%H:%M:%S"))
    
    st.markdown(f"""
**Bot Activity Log**
```
{datetime.now().strftime('%H:%M:%S')} SYSTEM_READY
{datetime.now().strftime('%H:%M:%S')} DATA_ENGINE: Yahoo Finance connected
{datetime.now().strftime('%H:%M:%S')} STRATEGY_ENGINE: RSI-2 + Trend + Breakout + BB + Volume
{datetime.now().strftime('%H:%M:%S')} RISK_ENGINE: Max 5 pos / 60% exposure
{datetime.now().strftime('%H:%M:%S')} PAPER_DB: {len(positions)} positions / {len(get_orders_df())} orders
{datetime.now().strftime('%H:%M:%S')} MODE: PAPER TRADING ✅
```""")
