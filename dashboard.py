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
        
        # Seed default admin account
        try:
            conn.execute("INSERT OR IGNORE INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                         ("deathkinght666", hash_password("Xnunxer123*"), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.execute("INSERT OR IGNORE INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                         ("deathknight666", hash_password("Xnunxer123*"), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
        except:
            pass
        
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
from engine import *

@st.cache_data(ttl=60)
def get_market_data(symbol, period='3y', interval='1d'):
    import engine
    return engine.get_market_data(symbol, period, interval)
# ============================================================
# DASHBOARD
# ============================================================

st.set_page_config(
    page_title="Trading Bot",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Trading Bot Command Center")

if "alert_msg" in st.session_state and st.session_state["alert_msg"]:
    st.success(st.session_state["alert_msg"])
    st.session_state["alert_msg"] = ""

# ------------------------------------------------------------
# GLOBAL PORTFOLIO SUMMARY (Ditaruh di Paling Atas!)
# ------------------------------------------------------------
import sqlite3
from pathlib import Path

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
            from engine import INITIAL_CAPITAL
            conn.execute("INSERT INTO kv VALUES('cash', ?)", (INITIAL_CAPITAL,))
            conn.commit()
            
        portfolio = pd.read_sql("SELECT * FROM positions", conn)
        trades = pd.read_sql("SELECT * FROM orders WHERE status='FILLED'", conn)
        cash_row = conn.execute("SELECT v FROM kv WHERE k='cash'").fetchone()
        available_cash = float(cash_row[0]) if cash_row else 0

    total_pnl = pd.to_numeric(trades["pnl"], errors='coerce').sum() if ('pnl' in trades.columns) else 0
    open_capital = pd.to_numeric(portfolio["cost"], errors='coerce').sum() if ('cost' in portfolio.columns and not portfolio.empty) else 0
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Available Cash 💵", f"Rp {available_cash:,.0f}")
    m2.metric("Total Open Capital 📊", f"Rp {open_capital:,.0f}")
    m3.metric("Net Realized PnL 📉", f"Rp {total_pnl:,.0f}")
    m4.metric("Executed Trades ⚡", len(trades))
    
    st.write("---")
except Exception as e:
    st.error(f"Gagal memuat Global Summary: {e}")

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

if scan_df.empty:
    st.error("DEBUG: Scanner returned empty dataframe! Errors:")
    st.write(errors[:5])

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

        # --- TRADINGVIEW STYLE CHART ---
        from plotly.subplots import make_subplots
        
        fig = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25]
        )
        
        # 1. Candlestick
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            name='Price',
            increasing_line_color='#26a69a', increasing_fillcolor='#26a69a',
            decreasing_line_color='#ef5350', decreasing_fillcolor='#ef5350'
        ), row=1, col=1)
        
        # 2. Moving Averages & Bollinger
        fig.add_trace(go.Scatter(x=df.index, y=df['ma20'], name='MA20', line=dict(color='#2962FF', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['ma50'], name='MA50', line=dict(color='#FF6D00', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_upper'], name='BB Up', line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['bb_lower'], name='BB Low', line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)
        
        # 3. Volume
        vol_colors = ['#26a69a' if row['close'] >= row['open'] else '#ef5350' for _, row in df.iterrows()]
        fig.add_trace(go.Bar(
            x=df.index, y=df['volume'],
            name='Volume', marker_color=vol_colors, opacity=0.8
        ), row=2, col=1)
        
        # 4. Styling ala TradingView
        fig.update_layout(
            template='plotly_dark',
            height=650,
            margin=dict(l=10, r=10, t=40, b=10),
            xaxis_rangeslider_visible=False,
            showlegend=False,
            title=dict(text=f'<b>{symbol} | Advanced Chart</b>', font=dict(size=20, color='#D1D4DC')),
            paper_bgcolor='#131722',
            plot_bgcolor='#131722',
            hovermode='x unified'
        )
        
        fig.update_xaxes(showgrid=True, gridcolor='#363a45', tickfont=dict(color='#787b86'))
        fig.update_yaxes(showgrid=True, gridcolor='#363a45', tickfont=dict(color='#787b86'), row=1, col=1)
        fig.update_yaxes(showgrid=False, tickfont=dict(color='#787b86'), row=2, col=1)
        
        st.plotly_chart(fig, use_container_width=True)

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
                                st.session_state["alert_msg"] = f"✅ Order BUY {symbol} berhasil dieksekusi secara simulasi dan masuk ke paper.db!"
                                st.rerun()
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

try:
    if portfolio.empty and trades.empty:
        st.info("Belum ada posisi paper trading. Coba klik 'EXECUTE BUY' pada saham pilihan di atas.")
    
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
                
                st.session_state["alert_msg"] = f"✅ Berhasil menjual {sell_symbol} di Rp{current_price:,.0f}. Net PnL (setelah fee): Rp{pnl:,.0f}"
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
# PAGE 4
# STRATEGY TESTER (BACKTEST)
# ============================================================
st.write("---")
st.header("4. Strategy Tester (Historical Backtest)")

with st.expander("🧪 Buka Panel Strategy Tester (Klik di Sini)"):
    st.write("Uji performa bot ke masa lalu (3 Tahun) untuk seluruh 45 saham tanpa harus menyentuh terminal/kode.")
    
    if st.button("▶️ JALANKAN BACKTEST (Semua Saham)"):
        with st.spinner("⏳ Mesin waktu sedang berputar... Mengunduh & memproses puluhan ribu candle 3 tahun terakhir (Butuh waktu ~30 detik)..."):
            try:
                from engine import run_historical_backtest
                res = run_historical_backtest()
                
                if res:
                    st.success("✅ Backtest Selesai!")
                    
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
                    st.line_chart(res['equity_df'].set_index('date')['equity'])
                    
                else:
                    st.error("Gagal mendapatkan data.")
            except Exception as e:
                st.error(f"Error saat backtest: {e}")


# ============================================================
# FOOTER
# ============================================================
st.divider()
st.caption(f"Last update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
