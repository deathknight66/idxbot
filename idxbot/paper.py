"""Paper broker berbasis SQLite: posisi, cash, dan order (PENDING -> FILLED/CANCELLED)."""
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v REAL);
CREATE TABLE IF NOT EXISTS positions(
  symbol TEXT PRIMARY KEY, shares INTEGER, entry REAL, stop REAL,
  entry_date TEXT, last_checked TEXT);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, signal_date TEXT, symbol TEXT,
  side TEXT, lots INTEGER, ref_price REAL, limit_price REAL,
  status TEXT DEFAULT 'PENDING', fill_price REAL, fill_date TEXT,
  reason TEXT, pnl REAL);
"""


class PaperBroker:
    def __init__(self, path: str, initial_cash: float):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if self.db.execute("SELECT 1 FROM kv WHERE k='cash'").fetchone() is None:
            self.db.execute("INSERT INTO kv VALUES('cash', ?)", (initial_cash,))
            self.db.commit()

    # --- state ---
    @property
    def cash(self) -> float:
        return self.db.execute("SELECT v FROM kv WHERE k='cash'").fetchone()[0]

    def _set_cash(self, v):
        self.db.execute("UPDATE kv SET v=? WHERE k='cash'", (v,))

    def positions(self) -> dict:
        return {r["symbol"]: dict(r) for r in
                self.db.execute("SELECT * FROM positions")}

    def pending(self) -> list:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM orders WHERE status='PENDING' ORDER BY id")]

    def equity(self, prices: dict) -> float:
        return self.cash + sum(p["shares"] * prices.get(s, p["entry"])
                               for s, p in self.positions().items())

    # --- orders ---
    def place(self, signal_date, symbol, side, lots, ref_price, limit_price, reason):
        self.db.execute(
            "INSERT INTO orders(signal_date,symbol,side,lots,ref_price,limit_price,reason)"
            " VALUES(?,?,?,?,?,?,?)",
            (str(signal_date), symbol, side, lots, ref_price, limit_price, reason))
        self.db.commit()

    def cancel(self, order_id, why):
        self.db.execute("UPDATE orders SET status='CANCELLED', reason=reason||' | '||? WHERE id=?",
                        (why, order_id))
        self.db.commit()

    def fill_buy(self, o, price, date, lot_size, fee, stop):
        shares = o["lots"] * lot_size
        self._set_cash(self.cash - shares * price * (1 + fee))
        self.db.execute("INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?,?)",
                        (o["symbol"], shares, price, stop, str(date), str(date)))
        self.db.execute("UPDATE orders SET status='FILLED', fill_price=?, fill_date=? WHERE id=?",
                        (price, str(date), o["id"]))
        self.db.commit()

    def fill_sell(self, symbol, price, date, fee, order_id=None, reason="signal"):
        p = self.positions()[symbol]
        gross = p["shares"] * price
        pnl = gross * (1 - fee) - p["shares"] * p["entry"]  # fee beli diabaikan di pnl paper
        self._set_cash(self.cash + gross * (1 - fee))
        self.db.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        if order_id:
            self.db.execute(
                "UPDATE orders SET status='FILLED', fill_price=?, fill_date=?, pnl=? WHERE id=?",
                (price, str(date), pnl, order_id))
        else:  # stop yang tereksekusi otomatis
            self.db.execute(
                "INSERT INTO orders(signal_date,symbol,side,lots,status,fill_price,fill_date,reason,pnl)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (str(date), symbol, "SELL", p["shares"] // 100, "FILLED", price, str(date), reason, pnl))
        self.db.commit()

    def set_checked(self, symbol, date):
        self.db.execute("UPDATE positions SET last_checked=? WHERE symbol=?", (str(date), symbol))
        self.db.commit()
