import math
from . import idx_rules as idx


def size_lots(equity: float, cash: float, price: float, cfg: dict) -> int:
    """Jumlah lot untuk posisi baru: porsi tetap dari equity, dibatasi cash
    (termasuk fee beli)."""
    lot = cfg["idx"]["lot_size"]
    alloc = min(equity * cfg["portfolio"]["position_fraction"], cash)
    per_lot = price * lot * (1 + cfg["costs"]["buy_fee"])
    return max(0, math.floor(alloc / per_lot))


def stop_price(entry: float, cfg: dict):
    pct = cfg["portfolio"].get("stop_loss_pct", 0)
    return idx.round_to_tick(entry * (1 - pct), "up") if pct else None
