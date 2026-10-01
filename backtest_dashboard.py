import pandas as pd
import numpy as np
from datetime import datetime
import logging
from engine import (
    UNIVERSE, get_market_data, calculate_indicators,
    penetration_engine, risk_check
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backtester")

def run_backtest():
    logger.info("Mulai mengunduh data historis 3 tahun untuk backtest...")
    
    historical_data = {}
    for sym in UNIVERSE:
        try:
            df = get_market_data(sym, period="3y")
            df = calculate_indicators(df)
            historical_data[sym] = df
        except Exception as e:
            logger.error(f"Gagal mengunduh {sym}: {e}")
            
    if not historical_data:
        logger.error("Tidak ada data untuk dibacktest.")
        return

    # Gabungkan semua index tanggal yang unik
    all_dates = pd.to_datetime([])
    for df in historical_data.values():
        all_dates = all_dates.union(df.index)
    all_dates = all_dates.sort_values()

    capital = 100_000_000.0
    cash = capital
    positions = {} # symbol -> {shares, entry, stop, tp, cost}
    trade_history = []
    equity_curve = []

    logger.info(f"Memulai simulasi dari {all_dates[0].date()} hingga {all_dates[-1].date()}")
    
    for current_date in all_dates:
        daily_equity = cash
        
        # 1. CEK EXIT POSISI (STOP LOSS / TAKE PROFIT)
        symbols_to_sell = []
        for sym, pos in positions.items():
            df = historical_data.get(sym)
            if df is None or current_date not in df.index:
                # Harga hari ini ditambahkan ke ekuitas berdasarkan harga terakhir yg diketahui
                daily_equity += pos['cost']
                continue
                
            today_data = df.loc[current_date]
            current_price = today_data['close']
            daily_equity += current_price * pos['shares']
            
            # Cek Stop Loss & Take Profit
            if current_price <= pos['stop']:
                symbols_to_sell.append((sym, "STOP LOSS", current_price))
            elif current_price >= pos['tp']:
                symbols_to_sell.append((sym, "TAKE PROFIT", current_price))

        # Eksekusi Sell
        for sym, reason, price in symbols_to_sell:
            pos = positions[sym]
            gross_value = price * pos['shares']
            sell_fee = gross_value * 0.0025
            net_receive = gross_value - sell_fee
            
            pnl = net_receive - pos['cost']
            cash += net_receive
            daily_equity += pnl # Koreksi dari estimasi sebelum jual
            
            trade_history.append({
                'date': current_date,
                'symbol': sym,
                'type': 'SELL',
                'reason': reason,
                'price': price,
                'pnl': pnl
            })
            del positions[sym]
            # logger.info(f"[{current_date.date()}] SELL {sym} @ {price:,.0f} | PnL: {pnl:,.0f}")

        # 2. CARI ENTRY BARU JIKA ADA CASH
        for sym in UNIVERSE:
            if sym in positions:
                continue
                
            df = historical_data.get(sym)
            if df is None or current_date not in df.index:
                continue
                
            # Simulasi dataframe sampai hari ini untuk Penetration Engine
            # (Agar tidak melihat masa depan)
            df_up_to_today = df.loc[:current_date]
            if len(df_up_to_today) < 20: # Butuh cukup baris untuk indikator
                continue
                
            penetration = penetration_engine(df_up_to_today)
            
            if penetration["signal"] == "ENTRY CANDIDATE":
                risk = risk_check(df_up_to_today, capital=100_000_000) # Asumsi risk dihitung dari modal awal statis
                
                if risk["approved"]:
                    shares = int(risk['lots'] * 100)
                    entry_price = float(risk['entry'])
                    gross_cost = shares * entry_price
                    buy_fee = gross_cost * 0.0015
                    total_cost = gross_cost + buy_fee
                    
                    if cash >= total_cost:
                        cash -= total_cost
                        
                        sl = float(risk['stop_loss'])
                        tp = entry_price + ((entry_price - sl) * 2) # TP = 1:2
                        
                        positions[sym] = {
                            'shares': shares,
                            'entry': entry_price,
                            'stop': sl,
                            'tp': tp,
                            'cost': total_cost
                        }
                        
                        trade_history.append({
                            'date': current_date,
                            'symbol': sym,
                            'type': 'BUY',
                            'reason': "ENTRY CANDIDATE",
                            'price': entry_price,
                            'pnl': 0
                        })
                        # logger.info(f"[{current_date.date()}] BUY {sym} @ {entry_price:,.0f}")
                        
        equity_curve.append({
            'date': current_date,
            'equity': daily_equity,
            'cash': cash
        })

    # --- HASIL BACKTEST ---
    trades_df = pd.DataFrame(trade_history)
    equity_df = pd.DataFrame(equity_curve)
    
    final_equity = equity_df.iloc[-1]['equity']
    total_return = ((final_equity - capital) / capital) * 100
    
    win_trades = len(trades_df[(trades_df['type'] == 'SELL') & (trades_df['pnl'] > 0)])
    total_closed_trades = len(trades_df[trades_df['type'] == 'SELL'])
    win_rate = (win_trades / total_closed_trades * 100) if total_closed_trades > 0 else 0
    
    logger.info("\n" + "="*50)
    logger.info("📊 HASIL BACKTEST: PENETRATION ENGINE (DASHBOARD)")
    logger.info("="*50)
    logger.info(f"Modal Awal   : Rp {capital:,.0f}")
    logger.info(f"Modal Akhir  : Rp {final_equity:,.0f}")
    logger.info(f"Total Return : {total_return:.2f}%")
    logger.info(f"Total Trade  : {total_closed_trades} (Selesai)")
    logger.info(f"Win Rate     : {win_rate:.1f}%")
    
    if not trades_df.empty:
        sell_trades = trades_df[trades_df['type'] == 'SELL']
        if not sell_trades.empty:
            avg_pnl = sell_trades['pnl'].mean()
            logger.info(f"Rata-Rata PnL: Rp {avg_pnl:,.0f} per trade")
            
    logger.info("="*50)
    
if __name__ == "__main__":
    run_backtest()
