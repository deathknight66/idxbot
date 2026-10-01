import time
import logging
import sqlite3
from datetime import datetime

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
                current_price = df.iloc[-1]['close']
                
                # Cek Kondisi Exit
                reason = None
                if current_price <= stop_loss:
                    reason = "STOP LOSS HIT"
                elif current_price >= take_profit:
                    reason = "TAKE PROFIT HIT"
                    
                if reason:
                    pnl = (current_price - entry) * shares
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute(
                            "INSERT INTO orders (signal_date, symbol, side, lots, ref_price, status, reason, pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (now, symbol, "SELL", shares // 100, current_price, "FILLED", reason, pnl)
                        )
                        conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
                    logger.warning(f"[{symbol}] AUTO-SELL DIEKSEKUSI: {reason}. Terjual @ Rp {current_price:,.0f} | PnL: Rp {pnl:,.0f}")
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
                    # EXECUTE BUY
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    shares = risk['lots'] * 100
                    
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute(
                            "INSERT INTO orders (signal_date, symbol, side, lots, ref_price, status, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (now, symbol, "BUY", risk['lots'], risk['entry'], "FILLED", "ENTRY CANDIDATE")
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO positions (symbol, shares, entry, stop, entry_date, cost) VALUES (?, ?, ?, ?, ?, ?)",
                            (symbol, shares, risk['entry'], risk['stop_loss'], now, risk['estimated_value'])
                        )
                    logger.info(f"[{symbol}] AUTO-BUY DIEKSEKUSI: {risk['lots']} lot @ Rp {risk['entry']:,.0f}")
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
