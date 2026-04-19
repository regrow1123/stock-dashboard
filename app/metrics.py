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


def twr_series(
    values: list[tuple["date", float]],  # type: ignore[name-defined]  # noqa: F821
    flows_by_date: dict,
) -> list[tuple["date", float]]:  # type: ignore[name-defined]
    """Time-weighted return series rebased to 1.0 at the first date.

    For each step the daily return removes net external cash flow on that date:
        r_t = (V_t - V_{t-1} - F_t) / V_{t-1}
    where F_t is net cash flow INTO the portfolio on date t (positive for buys,
    negative for sells). A buy of N shares at P contributes +N*P; a sell
    contributes -N*P. This cancels the purchase-day "jump" that would otherwise
    appear when newly-acquired positions first enter the snapshot.

    Trades dated on the first day in `values` are ignored (no prior period to
    compute a return over; they're treated as part of the starting position).
    """
    if not values:
        return []
    out: list[tuple["date", float]] = [(values[0][0], 1.0)]  # type: ignore[name-defined]
    twr = 1.0
    for i in range(1, len(values)):
        d, v_t = values[i]
        _, v_prev = values[i - 1]
        f_t = flows_by_date.get(d, 0.0)
        if v_prev > 0:
            r = (v_t - v_prev - f_t) / v_prev
            twr *= 1.0 + r
        out.append((d, twr))
    return out
