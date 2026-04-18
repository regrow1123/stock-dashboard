from collections import deque
from typing import Iterable, Protocol


class TradeLike(Protocol):
    ticker: str
    side: str
    quantity: float
    price: float


def avg_cost_from_seed_and_trades(
    seed_qty: float, seed_avg: float, trades: Iterable[TradeLike]
) -> tuple[float, float]:
    """Weighted-average cost: buys update avg, sells keep avg."""
    qty = seed_qty
    avg = seed_avg
    for t in trades:
        if t.side == "buy":
            new_qty = qty + t.quantity
            if new_qty <= 0:
                qty, avg = new_qty, 0.0
            else:
                avg = (qty * avg + t.quantity * t.price) / new_qty
                qty = new_qty
        elif t.side == "sell":
            qty -= t.quantity
            if qty <= 0:
                qty, avg = max(qty, 0.0), 0.0
    return qty, avg


def fifo_realized_pnl(
    seed_qty: float, seed_avg: float, trades: Iterable[TradeLike]
) -> float:
    """FIFO realized P&L. Seed lot is treated as the oldest lot at seed_avg."""
    lots: deque[list[float]] = deque()
    if seed_qty > 0:
        lots.append([seed_qty, seed_avg])
    realized = 0.0
    for t in trades:
        if t.side == "buy":
            lots.append([t.quantity, t.price])
        else:  # sell
            remaining = t.quantity
            while remaining > 0 and lots:
                lot_qty, lot_price = lots[0]
                take = min(lot_qty, remaining)
                realized += take * (t.price - lot_price)
                lot_qty -= take
                remaining -= take
                if lot_qty == 0:
                    lots.popleft()
                else:
                    lots[0][0] = lot_qty
    return realized


def weights_from_values(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    if total == 0:
        return {k: 0.0 for k in values}
    return {k: v / total for k, v in values.items()}


def pct_return(cost: float, value: float) -> float:
    if cost <= 0:
        return 0.0
    return (value - cost) / cost
