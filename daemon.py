import time
import logging
import sqlite3
from datetime import datetime

# Import logika inti dari dashboard
from dashboard import (
    UNIVERSE, get_market_data, calculate_indicators,
    penetration_engine, risk_check, INITIAL_CAPITAL
)

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

def run_cycle():
    logger.info("Memulai siklus scanning market...")
    
    with sqlite3.connect(DB_PATH) as conn:
        # Cek open positions
        import pandas as pd
        pos_df = pd.read_sql("SELECT * FROM positions", conn)
        active_symbols = pos_df["symbol"].tolist() if not pos_df.empty else []
    
    # SCAN & BUY LOGIC
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
                    # EXECUTE BUY
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    shares = risk['lots'] * 100
                    
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute(
                            "INSERT INTO orders (signal_date, symbol, side, lots, ref_price, status) VALUES (?, ?, ?, ?, ?, ?)",
                            (now, symbol, "BUY", risk['lots'], risk['entry'], "FILLED")
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO positions (symbol, shares, entry, stop, entry_date, cost) VALUES (?, ?, ?, ?, ?, ?)",
                            (symbol, shares, risk['entry'], risk['stop_loss'], now, risk['estimated_value'])
                        )
                    logger.info(f"[{symbol}] AUTO-BUY DIEKSEKUSI: {risk['lots']} lot @ Rp {risk['entry']:,.0f}")
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
