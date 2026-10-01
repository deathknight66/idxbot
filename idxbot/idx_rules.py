"""Aturan pasar IDX (papan reguler). Verifikasi ke ketentuan BEI terkini
sebelum dipakai uang asli -- angka bisa berubah."""
import math


def tick_size(price: float) -> int:
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2000:
        return 5
    if price < 5000:
        return 10
    return 25


def round_to_tick(price: float, mode: str = "nearest") -> float:
    t = tick_size(price)
    q = price / t
    q = {"up": math.ceil, "down": math.floor, "nearest": round}[mode](q)
    return float(q * t)


def buy_price(ref_price: float, slippage_bps: float) -> float:
    """Harga beli realistis: naik sedikit karena slippage, dibulatkan ke atas."""
    return round_to_tick(ref_price * (1 + slippage_bps / 1e4), "up")


def sell_price(ref_price: float, slippage_bps: float) -> float:
    return round_to_tick(ref_price * (1 - slippage_bps / 1e4), "down")


def limits(prev_close: float, ara_pct: float, arb_pct: float):
    """Batas ARA/ARB sederhana dari penutupan sebelumnya."""
    return (round_to_tick(prev_close * (1 - arb_pct), "up"),
            round_to_tick(prev_close * (1 + ara_pct), "down"))
