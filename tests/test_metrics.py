from dataclasses import dataclass
from datetime import date

from app.metrics import (
    avg_cost_from_seed_and_trades,
    fifo_realized_pnl,
    twr_series,
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


def test_twr_series_no_flows_matches_rebase():
    pts = [
        (date(2026, 1, 1), 1000.0),
        (date(2026, 1, 2), 1100.0),
        (date(2026, 1, 3), 1050.0),
    ]
    out = twr_series(pts, {})
    # no flows → pure value-rebased series
    assert out[0] == (date(2026, 1, 1), 1.0)
    assert round(out[1][1], 3) == 1.1
    assert round(out[2][1], 3) == 1.05


def test_twr_series_strips_purchase_day_jump():
    # day 1: V=1000. day 2: market +10% → V=1100. day 3: buy 500 worth → V=1600.
    # day 4: market -5% on all → V=1520.
    # naive rebased would show 1.0 → 1.1 → 1.6 → 1.52 (artificial jump at day 3).
    # TWR should show 1.0 → 1.1 → 1.1 (no market move) → 1.045.
    pts = [
        (date(2026, 1, 1), 1000.0),
        (date(2026, 1, 2), 1100.0),
        (date(2026, 1, 3), 1600.0),
        (date(2026, 1, 4), 1520.0),
    ]
    flows = {date(2026, 1, 3): 500.0}
    out = twr_series(pts, flows)
    assert out[0][1] == 1.0
    assert round(out[1][1], 4) == 1.1
    assert round(out[2][1], 4) == 1.1      # flow cancels
    assert round(out[3][1], 4) == 1.045    # -5% from 1.1


def test_twr_series_ignores_flow_on_first_day():
    # A trade on the very first day is part of the starting position, not a flow.
    pts = [(date(2026, 1, 1), 1000.0), (date(2026, 1, 2), 1100.0)]
    out = twr_series(pts, {date(2026, 1, 1): 500.0})
    assert out[1][1] == 1.1


def test_twr_series_handles_zero_prev():
    # Starting from an empty portfolio (V_0 = 0, then V_1 = 1000 via buy).
    pts = [(date(2026, 1, 1), 0.0), (date(2026, 1, 2), 1000.0), (date(2026, 1, 3), 1050.0)]
    out = twr_series(pts, {date(2026, 1, 2): 1000.0})
    # day 2 skipped (v_prev = 0), day 3 is +5%
    assert out[0][1] == 1.0
    assert out[1][1] == 1.0
    assert round(out[2][1], 4) == 1.05
