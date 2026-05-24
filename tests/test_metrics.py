from dataclasses import dataclass
from datetime import date

from app.metrics import (
    avg_cost_from_seed_and_trades,
    fifo_realized_pnl,
    weights_from_values,
    pct_return,
)


@dataclass
class T:
    ticker: str
    side: str
    quantity: float
    price: float
    executed_at: date


def test_avg_cost_combines_seed_and_buys():
    seed_qty, seed_avg = 10, 100.0
    trades = [T("X", "buy", 10, 120, date(2026, 1, 2))]
    qty, avg = avg_cost_from_seed_and_trades(seed_qty, seed_avg, trades)
    assert qty == 20
    assert avg == 110.0


def test_avg_cost_sell_preserves_avg():
    trades = [
        T("X", "buy", 10, 100, date(2026, 1, 1)),
        T("X", "sell", 4, 150, date(2026, 1, 2)),
    ]
    qty, avg = avg_cost_from_seed_and_trades(0, 0.0, trades)
    assert qty == 6
    assert avg == 100.0


def test_fifo_realized_pnl():
    trades = [
        T("X", "buy", 10, 100, date(2026, 1, 1)),
        T("X", "buy", 10, 120, date(2026, 1, 2)),
        T("X", "sell", 15, 150, date(2026, 1, 3)),
    ]
    realized = fifo_realized_pnl(seed_qty=0, seed_avg=0.0, trades=trades)
    # first 10 @ 100 → 10*(150-100)=500 ; next 5 @ 120 → 5*(150-120)=150 ; total 650
    assert realized == 650.0


def test_weights_and_return():
    assert weights_from_values({"A": 100, "B": 300}) == {"A": 0.25, "B": 0.75}
    assert pct_return(cost=100, value=150) == 0.5
    assert pct_return(cost=0, value=100) == 0.0


