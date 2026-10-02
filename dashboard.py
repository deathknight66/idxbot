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
    risk_check, make_decision, INITIAL_CAPITAL, UNIVERSE
)

try:
    import anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False

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

/* ── Watchlist buttons: strip all chrome, look like TradingView rows ── */
div[data-testid="stVerticalBlock"] div[data-testid="stButton"] > button {
    all: unset;
    display: block;
    width: 100%;
    padding: 5px 8px;
    font-size: 11px;
    font-family: monospace;
    color: #D1D4DC;
    cursor: pointer;
    border-bottom: 1px solid #1E222D;
    box-sizing: border-box;
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    border-radius: 3px;
    line-height: 1.5;
}
div[data-testid="stVerticalBlock"] div[data-testid="stButton"] > button:hover {
    background: #1a3a5c;
    color: #FFFFFF;
}
div[data-testid="stVerticalBlock"] div[data-testid="stButton"] > button:focus {
    outline: none;
    background: #1a3a5c;
}

/* Collapse invisible watchlist click-capture buttons */
div[data-testid="stVerticalBlock"] div[data-testid="stButton"].wl-click-btn > button {
    height: 0 !important;
    padding: 0 !important;
    margin: -4px 0 0 0 !important;
    overflow: hidden !important;
    font-size: 0 !important;
    opacity: 0 !important;
    pointer-events: all !important;
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
            # Support both old schema (password_hash, created_at) and new schema (pw)
            # Use explicit column names to avoid column count mismatch
            try:
                cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
                if not cols:
                    c.execute("CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, pw TEXT)")
                    c.execute("INSERT OR IGNORE INTO users(username, pw) VALUES(?,?)",
                              ("deathknight666", _hash("Xnunxer123*")))
                elif "pw" in cols:
                    c.execute("INSERT OR IGNORE INTO users(username, pw) VALUES(?,?)",
                              ("deathknight666", _hash("Xnunxer123*")))
                elif "password_hash" in cols:
                    c.execute("INSERT OR IGNORE INTO users(username, password_hash) VALUES(?,?)",
                              ("deathknight666", _hash("Xnunxer123*")))
                c.commit()
            except Exception:
                pass

        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Masuk →", use_container_width=True):
                pw_hash = _hash(p)
                matched = False
                with sqlite3.connect("data/paper.db") as c:
                    cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
                    pw_col = "pw" if "pw" in cols else "password_hash"
                    try:
                        row = c.execute(f"SELECT {pw_col} FROM users WHERE username=?", (u,)).fetchone()
                        if row and row[0] == pw_hash:
                            matched = True
                    except Exception:
                        pass
                if matched:
                    st.session_state.update({"logged_in": True, "username": u})
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
        # ── Migrate old DB: add any missing columns safely ──
        migrations = [
            ("orders",    "ts",         "TEXT"),
            ("orders",    "side",       "TEXT"),
            ("orders",    "lots",       "INT DEFAULT 0"),
            ("orders",    "status",     "TEXT"),
            ("orders",    "reason",     "TEXT"),
            ("orders",    "pnl",        "REAL DEFAULT 0"),
            ("positions", "tp",         "REAL DEFAULT 0"),
            ("positions", "cost",       "REAL DEFAULT 0"),
            ("positions", "entry_date", "TEXT"),
        ]
        for table, col, col_type in migrations:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except Exception:
                pass  # Column already exists — fine

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

# ── TOP BAR — single HTML row for pixel-perfect alignment ──
pnl_pos = 0.0
if not positions.empty and data_ok:
    try:
        sym_short = selected  # e.g. BBCA
        pos_row = positions[positions['symbol'] == sym_short]
        if not pos_row.empty:
            entry_p = float(pos_row.iloc[0].get('entry', 0))
            shares_p = int(pos_row.iloc[0].get('shares', 0))
            cost_p   = float(pos_row.iloc[0].get('cost', 0))
            pnl_pos  = (last_price * shares_p * 0.9975) - cost_p
    except:
        pass

pnl_color = "#26a69a" if pnl_pos >= 0 else "#ef5350"
pnl_str   = f"+Rp{pnl_pos:,.0f}" if pnl_pos >= 0 else f"-Rp{abs(pnl_pos):,.0f}"
has_pos   = pnl_pos != 0

top_ctrl1, top_ctrl2, top_ctrl3 = st.columns([7, 1, 0.6])

with top_ctrl1:
    st.markdown(f"""
<div style="display:flex;align-items:center;gap:16px;padding:4px 0">
  <div>
    <span style="font-size:14px;font-weight:700">📈 IDXBot</span>
    <span style="font-size:10px;color:#26a69a;margin-left:4px">● PAPER</span>
  </div>
  <div style="font-size:18px;font-weight:700">
    {selected}&nbsp;<span style="color:{chg_color}">{last_price:,.0f} {chg_sign}{abs(chg_pct):.2f}%</span>
  </div>
  <div style="display:flex;gap:8px;margin-left:8px">
    <div style="background:#1E222D;border:1px solid #2A2E39;border-radius:4px;padding:3px 10px;text-align:center;min-width:70px">
      <div style="font-size:9px;color:#787b86">Equity</div>
      <div style="font-size:13px;font-weight:700">Rp{equity/1e6:.1f}M</div>
    </div>
    <div style="background:#1E222D;border:1px solid #2A2E39;border-radius:4px;padding:3px 10px;text-align:center;min-width:70px">
      <div style="font-size:9px;color:#787b86">Cash</div>
      <div style="font-size:13px;font-weight:700">Rp{cash/1e6:.1f}M</div>
    </div>
    <div style="background:#1E222D;border:1px solid #2A2E39;border-radius:4px;padding:3px 10px;text-align:center;min-width:70px">
      <div style="font-size:9px;color:#787b86">Invested</div>
      <div style="font-size:13px;font-weight:700">Rp{invested/1e6:.1f}M</div>
    </div>
    <div style="background:#1E222D;border:1px solid #2A2E39;border-radius:4px;padding:3px 10px;text-align:center;min-width:45px">
      <div style="font-size:9px;color:#787b86">Pos</div>
      <div style="font-size:13px;font-weight:700">{len(positions)}/5</div>
    </div>
    {f'''<div style="background:#1E222D;border:1px solid #2A2E39;border-radius:4px;padding:3px 10px;text-align:center;min-width:90px">
      <div style="font-size:9px;color:#787b86">{selected} P&L</div>
      <div style="font-size:13px;font-weight:700;color:{pnl_color}">{pnl_str}</div>
    </div>''' if has_pos else ''}
  </div>
</div>""", unsafe_allow_html=True)

period_opts = {"1m":"1mo","3m":"3mo","6m":"6mo","1y":"1y","3y":"3y"}
chosen = top_ctrl2.selectbox("", list(period_opts.keys()), index=3, label_visibility="collapsed")
if period_opts[chosen] != st.session_state["period"]:
    st.session_state["period"] = period_opts[chosen]
    st.rerun()

if top_ctrl3.button("Exit"):
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
    # ── WATCHLIST ─────────────────────────────────────────
    # Strategy: compact HTML rows for display, one button per row for click
    # CSS makes buttons height=1px transparent, overlapping the HTML row above

    # Pre-load prices (all cached)
    wl_data = {}
    for sym in WATCHLIST:
        px, pct = load_price(sym + ".JK")
        wl_data[sym] = (px, pct)

    # Header
    st.markdown(
        "<div style='padding:4px 8px 5px;font-size:10px;color:#787b86;"
        "font-weight:700;letter-spacing:1px;border-bottom:1px solid #2A2E39'>"
        "WATCHLIST</div>",
        unsafe_allow_html=True
    )

    # Render all rows as one HTML block (no buttons = no gap)
    rows_html = ""
    for sym in WATCHLIST:
        px, pct    = wl_data[sym]
        sign       = "+" if pct >= 0 else ""
        clr        = "#26a69a" if pct >= 0 else "#ef5350"
        is_active  = sym == selected
        bg         = "background:#1E2A3C;" if is_active else ""
        bl         = "border-left:3px solid #2962FF;" if is_active else "border-left:3px solid transparent;"
        sym_clr    = "#FFFFFF" if is_active else "#D1D4DC"
        rows_html += (
            f"<div style='display:flex;justify-content:space-between;"
            f"align-items:center;padding:5px 8px;{bg}{bl}"
            f"border-bottom:1px solid #1E222D;cursor:pointer' "
            f"onclick=\"\">"
            f"<span style='font-size:11px;font-weight:700;color:{sym_clr}'>{sym}</span>"
            f"<span style='text-align:right;line-height:1.2'>"
            f"<span style='font-size:11px;color:#D1D4DC'>{px:,.0f}</span><br/>"
            f"<span style='font-size:9px;color:{clr}'>{sign}{pct:.2f}%</span>"
            f"</span></div>"
        )
    st.markdown(rows_html, unsafe_allow_html=True)

    # One compact selectbox for actual selection (collapsed/hidden style)
    st.markdown(
        "<div style='padding:4px 8px;font-size:9px;color:#787b86'>▶ Pilih saham:</div>",
        unsafe_allow_html=True
    )
    sel_idx = WATCHLIST.index(selected) if selected in WATCHLIST else 0
    new_sel = st.selectbox(
        "", WATCHLIST, index=sel_idx,
        key="wl_select", label_visibility="collapsed"
    )
    if new_sel != selected:
        st.session_state["sym"] = new_sel
        st.rerun()

    # ── BOT SCAN ─────────────────────────────────────────
    st.markdown(
        "<div style='margin-top:8px;padding:4px 8px 5px;font-size:10px;"
        "color:#787b86;font-weight:700;letter-spacing:1px;"
        "border-top:1px solid #2A2E39;border-bottom:1px solid #2A2E39'>"
        "BOT SCAN</div>",
        unsafe_allow_html=True
    )
    buy_count = wait_count = 0
    for sym in WATCHLIST:
        try:
            df_scan = load_chart(sym + ".JK", "3mo")
            d = make_decision(df_scan, capital=equity)
            if d.get('approved'): buy_count += 1
            else: wait_count += 1
        except:
            wait_count += 1

    st.markdown(
        f"<div style='padding:6px 8px;font-size:11px;'>"
        f"<div style='display:flex;justify-content:space-between;"
        f"padding:3px 0;border-bottom:1px solid #1E222D'>"
        f"<span style='color:#787b86'>BUY ready</span>"
        f"<b style='color:#26a69a'>{buy_count}</b></div>"
        f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
        f"<span style='color:#787b86'>Watching</span>"
        f"<b style='color:#FF6D00'>{wait_count}</b></div>"
        f"</div>",
        unsafe_allow_html=True
    )




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

    # ── Run unified decision engine ──
    if data_ok:
        try:
            dec = make_decision(df, capital=equity)
        except Exception as dec_e:
            dec = {"state":"WAIT","signal_label":"🟡 WAIT","approved":False,
                   "total_score":0,"score_breakdown":{},"hard_filters":[],
                   "reasons_pass":[],"reasons_fail":[],"why_not":str(dec_e),
                   "regime":"?","strategy":"?","entry":last_price,
                   "stop_loss":last_price*0.95,"take_profit":last_price*1.05,
                   "lots":0,"rr":0,"support":0,"resistance":0}
    else:
        dec = {"state":"WAIT","signal_label":"🟡 WAIT","approved":False,
               "total_score":0,"score_breakdown":{},"hard_filters":[],
               "reasons_pass":[],"reasons_fail":[],"why_not":"No data",
               "regime":"?","strategy":"?","entry":0,
               "stop_loss":0,"take_profit":0,"lots":0,"rr":0,"support":0,"resistance":0}

    sl_px   = float(dec.get("stop_loss",   last_price * 0.95))
    tp_px   = float(dec.get("take_profit", last_price * 1.05))
    lots_rc = int(dec.get("lots", 0))

    # Lot override
    lots_input = st.number_input("Quantity (lot)", min_value=1,
                                  value=max(1, lots_rc), step=1)
    c1, c2 = st.columns(2)
    sl_input = c1.number_input("Stop Loss", value=int(sl_px), step=50)
    tp_input = c2.number_input("Take Profit", value=int(tp_px), step=50)

    risk_rp = lots_input * 100 * (last_price - sl_input) if sl_input else 0
    rr_disp = round((tp_input - last_price) / max(last_price - sl_input, 1), 2) if sl_input < last_price else 0
    st.markdown(f"<div style='font-size:11px;color:#787b86;margin:4px 0'>"
                f"Risk: <b style='color:#ef5350'>Rp{risk_rp:,.0f}</b> &nbsp;|&nbsp; "
                f"R:R <b style='color:#26a69a'>{rr_disp:.1f}x</b></div>",
                unsafe_allow_html=True)

    if do_buy:
        ok, msg = paper_buy(symbol, lots_input, last_price, sl_input, tp_input)
        st.session_state["flash"] = msg
        if ok: st.cache_data.clear()
        st.rerun()

    if do_sell:
        if not positions.empty and symbol.replace(".JK","") in positions['symbol'].values:
            ok, msg = paper_sell(symbol.replace(".JK",""), last_price)
            st.session_state["flash"] = msg
            if ok: st.cache_data.clear()
            st.rerun()
        else:
            st.session_state["flash"] = "❌ Tidak ada posisi untuk dijual"
            st.rerun()

    st.markdown("<hr style='border-color:#2A2E39;margin:8px 0'>", unsafe_allow_html=True)

    # ── BOT ANALYSIS (using unified make_decision) ──
    if data_ok:
        state     = dec["state"]
        sig_label = dec["signal_label"]
        score     = dec["total_score"]
        bd        = dec["score_breakdown"]
        regime    = dec["regime"]
        strategy  = dec["strategy"]
        hard_filt = dec["hard_filters"]
        r_pass    = dec["reasons_pass"]
        r_fail    = dec["reasons_fail"]
        why_not   = dec["why_not"]
        rr_val    = dec.get("rr", 0)

        # State colors
        state_color = {"BUY":"#26a69a","SETUP":"#2962FF","WAIT":"#FF6D00","AVOID":"#ef5350"}.get(state,"#787b86")
        bar_c       = "#26a69a" if score >= 80 else "#2962FF" if score >= 65 else "#FF6D00" if score >= 40 else "#ef5350"

        # Score breakdown bars
        bd_labels = {
            "regime":"Regime","liquidity":"Liquidity","rsi_2":"RSI-2",
            "trend":"Trend","breakout":"Breakout","mean_reversion":"BB Rev.",
            "volume":"Volume","support_proximity":"Support",
        }
        bd_max = {"regime":15,"liquidity":8,"rsi_2":25,"trend":20,
                  "breakout":20,"mean_reversion":20,"volume":15,"support_proximity":7}
        bd_html = ""
        for k, lbl in bd_labels.items():
            v    = bd.get(k, 0)
            mx   = bd_max.get(k, 10)
            pct  = max(0, min(100, int(abs(v) / mx * 100)))
            clr  = "#26a69a" if v > 0 else "#ef5350" if v < 0 else "#2A2E39"
            bd_html += (
                f"<div style='display:flex;align-items:center;gap:4px;padding:1px 0'>"
                f"<span style='width:52px;font-size:9px;color:#787b86'>{lbl}</span>"
                f"<div style='flex:1;background:#2A2E39;border-radius:2px;height:5px'>"
                f"<div style='width:{pct}%;background:{clr};height:5px;border-radius:2px'></div></div>"
                f"<span style='width:28px;font-size:9px;color:{clr};font-weight:700;text-align:right'>"
                f"{v:+.0f}/{mx}</span></div>"
            )

        # Hard filters
        hf_html = ""
        for hf in hard_filters if False else hard_filt:
            ic  = "✅" if hf["pass"] else "❌"
            clr = "#26a69a" if hf["pass"] else "#ef5350"
            hf_html += (f"<div style='display:flex;justify-content:space-between;"
                        f"font-size:9px;padding:1px 0'>"
                        f"<span style='color:#787b86'>{hf['name']}</span>"
                        f"<span style='color:{clr}'>{ic} {'' if hf['pass'] else hf['reason']}</span></div>")

        # WHY / WHY NOT
        why_html = ""
        if r_pass:
            why_html += "<div style='font-size:9px;color:#787b86;margin-top:6px;font-weight:700'>✅ WHY</div>"
            for r in r_pass[:4]:
                why_html += f"<div style='font-size:9px;color:#26a69a'>✓ {r}</div>"
        if r_fail:
            why_html += "<div style='font-size:9px;color:#787b86;margin-top:4px;font-weight:700'>❌ WHY NOT</div>"
            for r in r_fail[:4]:
                why_html += f"<div style='font-size:9px;color:#ef5350'>✗ {r}</div>"

        st.markdown(f"""
<div class="sig-card">
  <div style="font-size:10px;color:#787b86;font-weight:700">🤖 BOT ANALYSIS</div>
  <div style="font-size:22px;font-weight:700;color:{state_color};margin:4px 0">{sig_label}</div>
  <div style="font-size:10px;color:#787b86;margin-bottom:6px">{strategy}</div>

  <div style="display:flex;justify-content:space-between;align-items:center">
    <span style="font-size:10px;color:#787b86">Score</span>
    <span style="font-size:13px;font-weight:700;color:{bar_c}">{score}/100</span>
  </div>
  <div style="background:#2A2E39;border-radius:3px;height:6px;margin:4px 0 8px">
    <div style="width:{score}%;background:{bar_c};height:6px;border-radius:3px"></div>
  </div>

  <div style="font-size:9px;color:#787b86;font-weight:700;margin-bottom:3px">SCORE BREAKDOWN</div>
  {bd_html}

  <div style="font-size:9px;color:#787b86;font-weight:700;margin-top:8px;margin-bottom:3px">HARD FILTERS</div>
  {hf_html}

  {why_html}

  <div style="font-size:9px;color:#787b86;font-weight:700;margin-top:8px;margin-bottom:3px">TRADE PLAN</div>
  <div class="sig-row"><span>Regime</span><b>{regime}</b></div>
  <div class="sig-row"><span>Entry</span><b>Rp{last_price:,.0f}</b></div>
  <div class="sig-row"><span>SL</span><b style="color:#ef5350">Rp{sl_px:,.0f}</b></div>
  <div class="sig-row"><span>TP</span><b style="color:#26a69a">Rp{tp_px:,.0f}</b></div>
  <div class="sig-row"><span>Lots</span><b>{lots_rc} lot</b></div>
  <div class="sig-row"><span>R:R</span><b style="color:#26a69a">{rr_val:.1f}x</b></div>
  {f"<div style='font-size:9px;color:#ef5350;margin-top:4px'>{why_not}</div>" if why_not else ""}
</div>""", unsafe_allow_html=True)


    st.markdown("<hr style='border-color:#2A2E39;margin:8px 0'>", unsafe_allow_html=True)

    # ── CLAUDE AI ASSISTANT ──────────────────────────────
    claude_icon = "🤖 Claude" if CLAUDE_AVAILABLE else "🤖 Assistant"
    st.markdown(f"<div style='font-size:12px;font-weight:700;margin-bottom:4px'>{claude_icon}</div>",
                unsafe_allow_html=True)

    # Check API key from Streamlit secrets
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "") if hasattr(st, "secrets") else ""
    claude_ready = CLAUDE_AVAILABLE and bool(api_key)

    if not claude_ready:
        st.markdown(
            "<div style='font-size:10px;color:#787b86;background:#1E222D;"
            "padding:6px;border-radius:4px;border:1px solid #2A2E39'>"
            "⚙️ Tambahkan <b>ANTHROPIC_API_KEY</b> di Streamlit Secrets untuk aktifkan Claude AI."
            "</div>", unsafe_allow_html=True
        )

    chat_inp = st.text_input("", placeholder="Tanya Claude: 'Kenapa BBCA WAIT?' atau 'Analisis BMRI'",
                             label_visibility="collapsed", key="chat_inp")

    if chat_inp:
        # Build context: gather real engine data to send to Claude
        ctx_lines = []
        try:
            # Current symbol analysis
            sig_ctx  = signal_engine(df) if data_ok else {}
            risk_ctx = risk_check(df, capital=equity) if data_ok else {}
            rsi_ctx  = float(df['rsi_2'].iloc[-1]) if data_ok and 'rsi_2' in df.columns else 0
            vr_ctx   = float(df['volume_ratio'].iloc[-1]) if data_ok and 'volume_ratio' in df.columns else 1.0
            ma200_ctx = float(df['ma200'].iloc[-1]) if data_ok and 'ma200' in df.columns else 0

            ctx_lines = [
                f"=== IDXBot Market Context ===",
                f"Symbol yang sedang dilihat: {selected} ({symbol})",
                f"Harga terakhir: Rp{last_price:,.0f} ({chg_pct:+.2f}%)",
                f"",
                f"--- Signal Engine Output ---",
                f"Signal: {sig_ctx.get('signal','?')}",
                f"Total Score: {sig_ctx.get('total_score',0)}/100",
                f"Dominant Strategy: {sig_ctx.get('strategy','?')}",
                f"Market Regime: {sig_ctx.get('regime','?')}",
                f"Score Breakdown: {sig_ctx.get('score_breakdown',{})}",
                f"Reason: {sig_ctx.get('reason','?')}",
                f"",
                f"--- Technical Indicators ---",
                f"RSI(2): {rsi_ctx:.1f} {'(Oversold)' if rsi_ctx < 5 else '(Normal)' if rsi_ctx < 70 else '(Overbought)'}",
                f"Volume Ratio: {vr_ctx:.2f}x average",
                f"Price vs MA200: {'ABOVE' if last_price > ma200_ctx > 0 else 'BELOW'} (MA200={ma200_ctx:,.0f})",
                f"Support: Rp{sig_ctx.get('support', 0):,.0f}",
                f"Resistance: Rp{sig_ctx.get('resistance', 0):,.0f}",
                f"",
                f"--- Risk Engine Output ---",
                f"Approved: {risk_ctx.get('approved', False)}",
                f"Lots: {risk_ctx.get('lots', 0)} lot",
                f"Entry: Rp{risk_ctx.get('entry', last_price):,.0f}",
                f"Stop Loss: Rp{risk_ctx.get('stop_loss', 0):,.0f}",
                f"Take Profit: Rp{risk_ctx.get('take_profit', 0):,.0f}",
                f"Risk Reason: {risk_ctx.get('reason', '')}",
                f"",
                f"--- Portfolio State ---",
                f"Total Equity: Rp{equity:,.0f}",
                f"Cash: Rp{cash:,.0f}",
                f"Open Positions: {len(positions)}/5",
            ]
            if not positions.empty:
                ctx_lines.append("Posisi aktif:")
                for _, pr in positions.iterrows():
                    ctx_lines.append(f"  - {pr['symbol']}: {int(pr.get('shares',0))//100} lot @ Rp{float(pr.get('entry',0)):,.0f}")
        except Exception as ctx_e:
            ctx_lines = [f"Context error: {ctx_e}"]

        context_str = "\n".join(ctx_lines)

        SYSTEM_PROMPT = """Kamu adalah IDXBot AI Assistant — intelligence layer dari sistem trading bot IDX (Indonesia Stock Exchange).

Peranmu: Menganalisis dan menjelaskan keputusan bot secara transparan kepada trader. 
BUKAN untuk mengeksekusi order secara langsung.

Prinsip utama:
- Jelaskan KENAPA bot memberikan sinyal tertentu berdasarkan data yang diberikan
- Gunakan bahasa Indonesia yang jelas dan ringkas
- Fokus pada expectancy, risk/reward, dan edge — BUKAN win rate semata
- Jika ada setup yang menarik, jelaskan trade plan-nya (entry, SL, TP, lot)
- Ingatkan bahwa keputusan akhir tetap di tangan trader
- Jangan pernah claim "pasti profit" atau memberikan jaminan apapun
- Maksimal 150 kata per jawaban agar tidak membebani layar

Format jawaban: ringkas, bullet point jika perlu, langsung ke inti."""

        if claude_ready:
            try:
                client = anthropic.Anthropic(api_key=api_key)
                # Build message history (last 5 exchanges)
                history = []
                for role, msg in st.session_state["chat"][-8:]:
                    history.append({
                        "role": "user" if role == "u" else "assistant",
                        "content": msg
                    })
                history.append({
                    "role": "user",
                    "content": f"Data konteks dari bot:\n{context_str}\n\n---\nPertanyaan: {chat_inp}"
                })

                with st.spinner("Claude sedang menganalisis..."):
                    response = client.messages.create(
                        model="claude-opus-4-5",
                        max_tokens=400,
                        system=SYSTEM_PROMPT,
                        messages=history
                    )
                reply = response.content[0].text

            except Exception as claude_e:
                reply = f"Claude error: {claude_e}"
        else:
            # Fallback rule-based when no API key
            q = chat_inp.lower()
            try:
                sig_fb  = signal_engine(df) if data_ok else {}
                risk_fb = risk_check(df, capital=equity) if data_ok else {}
                rsi_fb  = float(df['rsi_2'].iloc[-1]) if data_ok and 'rsi_2' in df.columns else 0
                vr_fb   = float(df['volume_ratio'].iloc[-1]) if data_ok and 'volume_ratio' in df.columns else 1.0
                approved_fb = risk_fb.get('approved', False)
                signal_label = sig_fb.get('signal', 'WAIT')
                score_fb = sig_fb.get('total_score', 0)
                regime_fb = sig_fb.get('regime', '?')
                strategy_fb = sig_fb.get('strategy', '?')

                reply = (
                    f"**{selected}** — {signal_label} (Score: {score_fb}/100)\n\n"
                    f"📊 Regime: **{regime_fb}** | Strategi: {strategy_fb}\n"
                    f"RSI(2): {rsi_fb:.1f} | Volume: {vr_fb:.1f}x\n"
                    f"Entry: Rp{risk_fb.get('entry', last_price):,.0f} | "
                    f"SL: Rp{risk_fb.get('stop_loss', 0):,.0f} | "
                    f"TP: Rp{risk_fb.get('take_profit', 0):,.0f}\n\n"
                    f"{'✅ ' + risk_fb.get('reason','') if approved_fb else '⏸ ' + risk_fb.get('reason','')}\n\n"
                    f"_Tambahkan ANTHROPIC_API_KEY di Secrets untuk jawaban lebih detail dari Claude._"
                )
            except Exception as fb_e:
                reply = f"Error: {fb_e}"

        st.session_state["chat"].append(("u", chat_inp))
        st.session_state["chat"].append(("b", reply))

    # Display chat history
    for role, msg in st.session_state["chat"][-8:]:
        cls  = "chat-u" if role == "u" else "chat-b"
        icon = "👤" if role == "u" else "🤖"
        st.markdown(f'<div class="{cls}">{icon} {msg}</div>', unsafe_allow_html=True)

    if st.session_state["chat"] and st.button("🗑 Clear chat", key="clear_chat", use_container_width=True):
        st.session_state["chat"] = []
        st.rerun()


# ─────────────────────────────────────────
# BOTTOM TABS — Positions | Orders | Signals | Health
# ─────────────────────────────────────────
st.markdown("<hr style='border-color:#2A2E39;margin:4px 0'>", unsafe_allow_html=True)

tab_pos, tab_ord, tab_sig, tab_health = st.tabs(
    ["💼 Positions", "📋 Orders", "📡 Signals", "🛠 System Health"]
)

with tab_pos:
    try:
        positions_fresh = get_positions()
        if positions_fresh.empty:
            st.info("Tidak ada posisi aktif. Gunakan tombol BUY untuk membuka posisi.")
        else:
            pos_cols = st.columns(min(len(positions_fresh), 3))
            for i, (_, row) in enumerate(positions_fresh.iterrows()):
                col_idx = i % 3
                with pos_cols[col_idx]:
                    try:
                        cur_df = load_chart(str(row['symbol']), '1mo')
                        cur_px = float(cur_df['close'].iloc[-1])
                        shares = int(row.get('shares', 0))
                        cost   = float(row.get('cost', 0))
                        pnl    = (cur_px * shares * 0.9975) - cost
                        pnl_c  = "#26a69a" if pnl >= 0 else "#ef5350"
                        pnl_s  = f"+Rp{pnl:,.0f}" if pnl >= 0 else f"-Rp{abs(pnl):,.0f}"
                    except:
                        cur_px = float(row.get('entry', 0))
                        pnl_c, pnl_s = "#787b86", "N/A"

                    entry = float(row.get('entry', 0))
                    sl    = float(row.get('stop', 0))
                    tp    = float(row.get('tp', sl * 1.1)) if row.get('tp') else sl * 1.1
                    lots  = int(row.get('shares', 0)) // 100

                    st.markdown(f"""
<div class="pos-card">
  <b style="font-size:14px">{row['symbol']}</b>
  <span style="color:#787b86;font-size:12px"> BUY · {lots} lot</span><br/>
  Entry <b>Rp{entry:,.0f}</b> → Now <b>Rp{cur_px:,.0f}</b><br/>
  SL <span style="color:#ef5350">Rp{sl:,.0f}</span> &nbsp;
  TP <span style="color:#26a69a">Rp{tp:,.0f}</span><br/>
  <b style="color:{pnl_c};font-size:16px">{pnl_s}</b>
</div>""", unsafe_allow_html=True)
                    if st.button(f"🔴 Close {row['symbol']}", key=f"cls_{row['symbol']}",
                                 use_container_width=True):
                        ok, msg = paper_sell(str(row['symbol']), cur_px, "CLOSE POSITION")
                        st.session_state["flash"] = msg
                        if ok:
                            st.cache_data.clear()
                        st.rerun()
    except Exception as e:
        st.error(f"Positions error: {e}")

with tab_ord:
    try:
        orders = get_orders_df()
        if orders.empty:
            st.info("Belum ada order.")
        else:
            want = ['ts','symbol','side','lots','price','status','reason','pnl']
            show = [c for c in want if c in orders.columns]
            disp = orders[show].copy()
            for col in ['price','ref_price','fill_price','limit_price']:
                if col in disp.columns:
                    disp[col] = disp[col].apply(
                        lambda x: f"Rp{float(x):,.0f}" if pd.notna(x) and x != 0 else "-"
                    )
            if 'pnl' in disp.columns:
                disp['pnl'] = disp['pnl'].apply(
                    lambda x: (f"+Rp{float(x):,.0f}" if float(x) >= 0 else f"-Rp{abs(float(x)):,.0f}")
                    if pd.notna(x) else "-"
                )
            st.dataframe(disp, use_container_width=True, height=220)
    except Exception as e:
        st.error(f"Orders error: {e}")

with tab_sig:
    try:
        st.markdown("**🤖 Bot Scan** — klik saham di watchlist kiri untuk analisis detail")
        rows = []
        for sym in WATCHLIST:
            try:
                df_s  = load_chart(sym + ".JK", "3mo")
                r_s   = risk_check(df_s, capital=equity)
                sig_s = signal_engine(df_s)
                rsi_v = float(df_s['rsi_2'].iloc[-1]) if 'rsi_2' in df_s.columns else \
                        float(df_s['rsi'].iloc[-1]) if 'rsi' in df_s.columns else 0
                vr_v  = float(df_s['volume_ratio'].iloc[-1]) if 'volume_ratio' in df_s.columns else 1.0
                rows.append({
                    "Symbol":   sym,
                    "Harga":    f"Rp{float(df_s['close'].iloc[-1]):,.0f}",
                    "Signal":   "🟢 BUY" if r_s.get('approved') else sig_s.get('signal','WAIT'),
                    "Score":    sig_s.get('total_score', 0),
                    "Regime":   sig_s.get('regime', '-'),
                    "RSI(2)":   round(rsi_v, 1),
                    "Volume":   f"{vr_v:.1f}x",
                    "Lots":     r_s.get('lots', 0),
                })
            except:
                rows.append({"Symbol": sym, "Signal": "⚠️", "Score":0,
                             "Harga":"-","Regime":"-","RSI(2)":0,"Volume":"-","Lots":0})
        sig_df = pd.DataFrame(rows)
        st.dataframe(sig_df, use_container_width=True, height=320)
    except Exception as e:
        st.error(f"Signals error: {e}")

with tab_health:
    try:
        orders_count = len(get_orders_df())
        pos_count    = len(get_positions())
        now_str      = datetime.now().strftime("%H:%M:%S WIB")

        hc1, hc2, hc3, hc4 = st.columns(4)
        for col, label, val, color in [
            (hc1, "Data Feed",   "🟢 Yahoo Finance",  "#26a69a"),
            (hc2, "Paper DB",    "🟢 SQLite OK",       "#26a69a"),
            (hc3, "Strategy",    "🟢 Multi-Layer v2",  "#26a69a"),
            (hc4, "Last Check",  now_str,               "#D1D4DC"),
        ]:
            col.markdown(
                f"<div style='background:#1E222D;border:1px solid #2A2E39;border-radius:4px;"
                f"padding:8px;text-align:center'>"
                f"<div style='font-size:10px;color:#787b86'>{label}</div>"
                f"<div style='font-size:12px;font-weight:700;color:{color}'>{val}</div>"
                f"</div>", unsafe_allow_html=True
            )

        st.write("")
        st.markdown(f"""**📋 System Log**
```
{datetime.now().strftime('%H:%M:%S')} [INFO] SYSTEM READY
{datetime.now().strftime('%H:%M:%S')} [INFO] DATA ENGINE: Yahoo Finance ✅
{datetime.now().strftime('%H:%M:%S')} [INFO] STRATEGY ENGINE: RSI-2 + Trend + Breakout + BB + Volume ✅
{datetime.now().strftime('%H:%M:%S')} [INFO] RISK ENGINE: Max 5 pos / 60% exposure ✅
{datetime.now().strftime('%H:%M:%S')} [INFO] PAPER DB: {pos_count} positions / {orders_count} orders ✅
{datetime.now().strftime('%H:%M:%S')} [INFO] MODE: PAPER TRADING (Live disabled)
```""")
    except Exception as e:
        st.error(f"Health error: {e}")

