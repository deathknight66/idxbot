import time
import logging
import sqlite3
import traceback
from datetime import datetime
from notifier import send_telegram_message

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

# Import logika inti dari dashboard
from dashboard import (
    get_market_data, calculate_indicators,
    penetration_engine, risk_check, INITIAL_CAPITAL
)

# Suppress Streamlit thread context warnings when running in background daemon
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | DAEMON | %(levelname)s | %(message)s"
)
logger = logging.getLogger("bot_daemon")

DB_PATH = "data/paper.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
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

def run_cycle():
    logger.info("Memulai siklus scanning market...")
    
    with sqlite3.connect(DB_PATH) as conn:
        # Cek open positions
        import pandas as pd
        pos_df = pd.read_sql("SELECT * FROM positions", conn)
        active_symbols = pos_df["symbol"].tolist() if not pos_df.empty else []
        
    # ========================================================
    # 1. AUTO-SELL LOGIC (Pantau Stop Loss & Take Profit)
    # ========================================================
    if not pos_df.empty:
        logger.info(f"Memantau {len(pos_df)} posisi aktif untuk Exit...")
        for _, pos in pos_df.iterrows():
            symbol = pos['symbol']
            entry = pos['entry']
            stop_loss = pos['stop']
            shares = pos['shares']
            
            # Hitung take profit dinamis (Risk:Reward = 1:2)
            risk_amount = entry - stop_loss
            take_profit = entry + (risk_amount * 2)
            
            try:
                df = get_market_data(symbol, period="1mo")
                current_price = float(df.iloc[-1]['close'])
                
                # Cek Kondisi Exit
                reason = None
                if current_price <= stop_loss:
                    reason = "STOP LOSS HIT"
                elif current_price >= take_profit:
                    reason = "TAKE PROFIT HIT"
                    
                if reason:
                    gross_value = current_price * shares
                    sell_fee = gross_value * 0.0025
                    net_receive = gross_value - sell_fee
                    
                    cost = float(pos['cost'])
                    pnl = float(net_receive - cost)
                    lots = int(shares // 100)
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute(
                            "INSERT INTO orders (signal_date, symbol, side, lots, ref_price, status, reason, pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (now, symbol, "SELL", lots, current_price, "FILLED", reason, pnl)
                        )
                        conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
                        conn.execute("UPDATE kv SET v = v + ? WHERE k='cash'", (net_receive,))
                    logger.warning(f"[{symbol}] AUTO-SELL DIEKSEKUSI: {reason}. Terjual @ Rp {current_price:,.0f} | Net PnL: Rp {pnl:,.0f}")
                    
                    msg = f"📉 *AUTO-SELL: {symbol}*\nReason: {reason}\nPrice: Rp {current_price:,.0f}\nPnL: Rp {pnl:,.0f}"
                    send_telegram_message(msg)
                else:
                    logger.info(f"[{symbol}] Hold. Current: {current_price:,.0f} | SL: {stop_loss:,.0f} | TP: {take_profit:,.0f}")
            except Exception as e:
                logger.error(f"[{symbol}] Error pantau posisi: {e}")

    # ========================================================
    # 2. AUTO-BUY LOGIC (Scan Sinyal Baru)
    # ========================================================
    logger.info("Mencari kandidat sinyal Entry baru...")
    for symbol in UNIVERSE:
        if symbol in active_symbols:
            continue # Sudah punya barangnya, lewati
            
        try:
            df = get_market_data(symbol, period="3y")
            df = calculate_indicators(df)
            penetration = penetration_engine(df)
            
            if penetration["signal"] == "ENTRY CANDIDATE":
                logger.info(f"[{symbol}] Sinyal ENTRY terdeteksi! (Score: {penetration['entry_score']})")
                
                risk = risk_check(df, capital=INITIAL_CAPITAL)
                
                if risk["approved"]:
                    # Cek kas
                    with sqlite3.connect(DB_PATH) as conn:
                        cash_row = conn.execute("SELECT v FROM kv WHERE k='cash'").fetchone()
                        available_cash = float(cash_row[0]) if cash_row else INITIAL_CAPITAL
                    
                    shares = int(risk['lots'] * 100)
                    lots = int(risk['lots'])
                    entry_price = float(risk['entry'])
                    stop_loss_price = float(risk['stop_loss'])
                    
                    gross_cost = shares * entry_price
                    buy_fee = gross_cost * 0.0015
                    total_cost = float(gross_cost + buy_fee)
                    
                    if available_cash < total_cost:
                        logger.warning(f"[{symbol}] AUTO-BUY BATAL: Kas tidak cukup! Butuh Rp{total_cost:,.0f}, Saldo Rp{available_cash:,.0f}")
                        continue
                    
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute(
                            "INSERT INTO orders (signal_date, symbol, side, lots, ref_price, status, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (now, symbol, "BUY", lots, entry_price, "FILLED", "ENTRY CANDIDATE")
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO positions (symbol, shares, entry, stop, entry_date, cost) VALUES (?, ?, ?, ?, ?, ?)",
                            (symbol, shares, entry_price, stop_loss_price, now, total_cost)
                        )
                        conn.execute("UPDATE kv SET v = v - ? WHERE k='cash'", (total_cost,))
                    logger.info(f"[{symbol}] AUTO-BUY DIEKSEKUSI: {lots} lot @ Rp {entry_price:,.0f} | Biaya+Fee: Rp {total_cost:,.0f}")
                    
                    msg = f"🚀 *AUTO-BUY: {symbol}*\nLots: {lots}\nEntry: Rp {entry_price:,.0f}\nStop Loss: Rp {stop_loss_price:,.0f}"
                    send_telegram_message(msg)
                    
                    # Update active_symbols agar tidak dibeli lagi di iterasi yang sama
                    active_symbols.append(symbol)
                else:
                    logger.warning(f"[{symbol}] Sinyal ditolak oleh Risk Engine: {risk['reason']}")
                    
        except Exception as e:
            logger.error(f"[{symbol}] Error saat scanning: {e}")

    logger.info("Siklus selesai. Menunggu interval berikutnya...")

if __name__ == "__main__":
    init_db()
    logger.info("Bot Daemon (Background Engine) diaktifkan.")
    logger.info("Bot akan berjalan terus-menerus (24/7) mencari sinyal.")
    
    while True:
        run_cycle()
        # Sleep selama 15 menit sebelum scan berikutnya (sesuaikan dengan kebutuhan VPS)
        time.sleep(15 * 60)
