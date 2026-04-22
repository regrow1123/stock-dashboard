from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.metrics import avg_cost_from_seed_and_trades, pct_return, weights_from_values
from app.models import (
    Account, Benchmark, Dividend, Instrument, LivePrice, SeedHolding, Snapshot, Trade,
)
from app.prices import close_on_or_before
from app.sentiment import cnn_fg

router = APIRouter(prefix="/api")


def get_db():
    raise RuntimeError("overridden by app factory")


def _live(db: Session, ticker: str) -> float | None:
    r = db.get(LivePrice, ticker)
    return float(r.price) if r else None


def _name_map(db: Session) -> dict[str, str]:
    return {i.ticker: i.name for i in db.query(Instrument).all()}


def _holdings_for(db: Session, account_id: str) -> list[dict[str, Any]]:
    seeds = {
        sh.ticker: sh
        for sh in db.query(SeedHolding).filter_by(account_id=account_id).all()
    }
    trades_by_ticker: dict[str, list[Trade]] = {}
    for t in (
        db.query(Trade).filter_by(account_id=account_id).order_by(Trade.executed_at).all()
    ):
        trades_by_ticker.setdefault(t.ticker, []).append(t)
    tickers = set(seeds) | set(trades_by_ticker)
    names = _name_map(db)
    yesterday = date.today() - timedelta(days=1)
    out: list[dict[str, Any]] = []
    for tk in tickers:
        seed = seeds.get(tk)
        qty, avg = avg_cost_from_seed_and_trades(
            seed.quantity if seed else 0.0,
            seed.avg_price if seed else 0.0,
            trades_by_ticker.get(tk, []),
        )
        if qty <= 0:
            continue
        current = _live(db, tk)
        value = qty * current if current is not None else qty * avg
        cost = qty * avg
        prev = close_on_or_before(db, tk, yesterday)
        day_change = (current - prev) / prev if prev and current else None
        out.append({
            "ticker": tk,
            "name": names.get(tk, tk),
            "quantity": qty,
            "avg_price": avg,
            "cost": cost,
            "current_price": current,
            "prev_close": prev,
            "day_change_pct": day_change,
            "value": value,
            "pnl": value - cost,
            "pct_return": pct_return(cost, value),
        })
    out.sort(key=lambda r: r["value"], reverse=True)
    return out


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db)):
    return [
        {"id": a.id, "name": a.name, "broker": a.broker, "currency": a.currency,
         "display_order": a.display_order}
        for a in db.query(Account).order_by(Account.display_order).all()
    ]


@router.get("/accounts/{account_id}/holdings")
def account_holdings(account_id: str, db: Session = Depends(get_db)):
    if db.get(Account, account_id) is None:
        raise HTTPException(404)
    return _holdings_for(db, account_id)


@router.get("/accounts/{account_id}/weights")
def account_weights(account_id: str, db: Session = Depends(get_db)):
    if db.get(Account, account_id) is None:
        raise HTTPException(404)
    rows = _holdings_for(db, account_id)
    yesterday = date.today() - timedelta(days=1)
    weights = weights_from_values({r["ticker"]: r["value"] for r in rows})

    # yesterday's weights must use yesterday's quantities (replay trades
    # only up to `yesterday`), otherwise same-day buys/sells get hidden:
    # a buy that increases qty would inflate both numerator and denominator
    # by the same amount and the resulting weight_change would only reflect
    # price drift. If a ticker has no prev_close we exclude it from the
    # prev total to avoid skewing the denominator.
    seeds = {
        sh.ticker: sh
        for sh in db.query(SeedHolding).filter_by(account_id=account_id).all()
    }
    trades_yest: dict[str, list[Trade]] = {}
    for t in (
        db.query(Trade)
        .filter_by(account_id=account_id)
        .filter(Trade.executed_at <= yesterday)
        .order_by(Trade.executed_at)
        .all()
    ):
        trades_yest.setdefault(t.ticker, []).append(t)
    prev_values: dict[str, float] = {}
    for tk in set(seeds) | set(trades_yest):
        seed = seeds.get(tk)
        qty_yest, _ = avg_cost_from_seed_and_trades(
            seed.quantity if seed else 0.0,
            seed.avg_price if seed else 0.0,
            trades_yest.get(tk, []),
        )
        if qty_yest <= 0:
            continue
        prev = close_on_or_before(db, tk, yesterday)
        if prev is not None:
            prev_values[tk] = qty_yest * prev
    prev_total = sum(prev_values.values())
    prev_weights = {
        tk: v / prev_total for tk, v in prev_values.items()
    } if prev_total > 0 else {}

    out = []
    for r in rows:
        tk = r["ticker"]
        cur_w = weights.get(tk, 0.0)
        prev_w = prev_weights.get(tk)
        out.append({
            "ticker": tk,
            "name": r["name"],
            "weight": cur_w,
            "prev_weight": prev_w,
            "weight_change": (cur_w - prev_w) if prev_w is not None else None,
        })
    return out


MARKET_TICKERS = [
    # (ticker, label, group)
    ("^KS11",   "KOSPI",   "kr"),
    ("^KQ11",   "KOSDAQ",  "kr"),
    ("^GSPC",   "S&P",     "us"),
    ("^IXIC",   "NASDAQ",  "us"),
    ("KRW=X",   "USD/KRW", "us"),
    ("BTC-USD", "BTC",     "alt"),
    ("CL=F",    "WTI",     "alt"),
    ("GC=F",    "Gold",    "alt"),
]


@router.get("/markets")
def markets(db: Session = Depends(get_db)):
    out = []
    for tk, label, group in MARKET_TICKERS:
        rows = (
            db.query(Benchmark)
            .filter(Benchmark.ticker == tk)
            .order_by(Benchmark.date.desc())
            .limit(2)
            .all()
        )
        if len(rows) < 2:
            out.append({"ticker": tk, "label": label, "group": group,
                        "close": None, "change_pct": None})
            continue
        latest, prev = rows[0], rows[1]
        change = (latest.close - prev.close) / prev.close if prev.close else None
        out.append({
            "ticker": tk,
            "label": label,
            "group": group,
            "close": float(latest.close),
            "change_pct": change,
            "as_of": latest.date.isoformat(),
        })
    return out


@router.get("/sentiment")
def sentiment(db: Session = Depends(get_db)):
    skew_rows = (
        db.query(Benchmark)
        .filter(Benchmark.ticker == "^SKEW")
        .order_by(Benchmark.date.desc())
        .limit(60)
        .all()
    )
    skew = None
    if skew_rows:
        latest = skew_rows[0]
        prev = skew_rows[1] if len(skew_rows) > 1 else None
        history = [
            {"date": r.date.isoformat(), "score": float(r.close)}
            for r in reversed(skew_rows)
        ]
        skew = {
            "score": float(latest.close),
            "previous_close": float(prev.close) if prev else None,
            "as_of": latest.date.isoformat(),
            "history": history,
        }
    return {"fear_and_greed": cnn_fg(db), "skew": skew}


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    accounts = db.query(Account).order_by(Account.display_order).all()
    by_account = []
    by_currency: dict[str, dict[str, float]] = {}
    for a in accounts:
        rows = _holdings_for(db, a.id)
        value = sum(r["value"] for r in rows)
        cost = sum(r["cost"] for r in rows)
        # account-level daily % change: (today_value − yesterday_value) / yesterday
        prev_value = sum(
            r["quantity"] * r["prev_close"]
            for r in rows
            if r["prev_close"] is not None
        )
        day_change = (value - prev_value) / prev_value if prev_value > 0 else None
        by_account.append({
            "account_id": a.id, "name": a.name, "broker": a.broker,
            "currency": a.currency, "value": value, "cost": cost,
            "pnl": value - cost, "pct_return": pct_return(cost, value),
            "day_change_pct": day_change,
        })
        c = by_currency.setdefault(a.currency, {"value": 0.0, "cost": 0.0})
        c["value"] += value
        c["cost"] += cost
    totals = [
        {"currency": c, "value": v["value"], "cost": v["cost"],
         "pnl": v["value"] - v["cost"], "pct_return": pct_return(v["cost"], v["value"])}
        for c, v in by_currency.items()
    ]
    return {"accounts": by_account, "totals": totals}


@router.get("/accounts/{account_id}/history")
def account_history(
    account_id: str,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    if db.get(Account, account_id) is None:
        raise HTTPException(404)
    q = db.query(Snapshot).filter_by(account_id=account_id)
    if from_date is not None:
        q = q.filter(Snapshot.date >= from_date)
    if to_date is not None:
        q = q.filter(Snapshot.date <= to_date)
    by_date: dict[date, float] = {}
    for s in q.all():
        by_date[s.date] = by_date.get(s.date, 0.0) + s.value
    return [{"date": d.isoformat(), "value": v} for d, v in sorted(by_date.items())]


@router.get("/accounts/{account_id}/trades")
def account_trades(account_id: str, limit: int = 20, db: Session = Depends(get_db)):
    if db.get(Account, account_id) is None:
        raise HTTPException(404)
    rows = (
        db.query(Trade)
        .filter_by(account_id=account_id)
        .order_by(Trade.executed_at.desc(), Trade.id.desc())
        .limit(limit)
        .all()
    )
    names = _name_map(db)
    return [
        {"id": t.id, "ticker": t.ticker, "name": names.get(t.ticker, t.ticker),
         "side": t.side, "quantity": t.quantity, "price": t.price,
         "executed_at": t.executed_at.isoformat()}
        for t in rows
    ]


@router.get("/accounts/{account_id}/dividends")
def account_dividends(account_id: str, db: Session = Depends(get_db)):
    if db.get(Account, account_id) is None:
        raise HTTPException(404)
    rows = db.query(Dividend).filter_by(account_id=account_id).order_by(Dividend.paid_at).all()
    total = sum(r.amount for r in rows)
    return {
        "total": total,
        "entries": [
            {"ticker": r.ticker, "amount": r.amount, "paid_at": r.paid_at.isoformat()}
            for r in rows
        ],
    }


from app.benchmarks import BENCHMARK_FOR_CURRENCY, rebase_series
from app.metrics import fifo_realized_pnl, twr_series
from app.models import Benchmark as _Bench


@router.get("/accounts/{account_id}/realized")
def account_realized(account_id: str, db: Session = Depends(get_db)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404)
    total = 0.0
    by_ticker: dict[str, float] = {}
    trades_by_ticker: dict[str, list[Trade]] = {}
    for t in (
        db.query(Trade).filter_by(account_id=account_id).order_by(Trade.executed_at).all()
    ):
        trades_by_ticker.setdefault(t.ticker, []).append(t)
    seeds = {s.ticker: s for s in db.query(SeedHolding).filter_by(account_id=account_id).all()}
    for tk, trades in trades_by_ticker.items():
        s = seeds.get(tk)
        pnl = fifo_realized_pnl(
            seed_qty=s.quantity if s else 0.0,
            seed_avg=s.avg_price if s else 0.0,
            trades=trades,
        )
        by_ticker[tk] = pnl
        total += pnl
    return {"realized": total,
            "by_ticker": [{"ticker": k, "realized": v} for k, v in by_ticker.items()]}


@router.get("/accounts/{account_id}/benchmark")
def account_benchmark(
    account_id: str,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404)
    bench_ticker = BENCHMARK_FOR_CURRENCY.get(acc.currency)
    if bench_ticker is None:
        raise HTTPException(400, "no benchmark configured for this currency")

    snap_q = db.query(Snapshot).filter_by(account_id=account_id)
    if from_date is not None:
        snap_q = snap_q.filter(Snapshot.date >= from_date)
    if to_date is not None:
        snap_q = snap_q.filter(Snapshot.date <= to_date)
    by_date: dict[date, float] = {}
    for s in snap_q.all():
        by_date[s.date] = by_date.get(s.date, 0.0) + s.value
    port = sorted(by_date.items())

    # Net cash flows per date from trades in the same window (buys = inflow,
    # sells = outflow). Used to strip the purchase-day jump from the TWR curve.
    flow_q = db.query(Trade).filter_by(account_id=account_id)
    if port:
        flow_q = flow_q.filter(Trade.executed_at >= port[0][0])
    if to_date is not None:
        flow_q = flow_q.filter(Trade.executed_at <= to_date)
    flows_by_date: dict[date, float] = {}
    for t in flow_q.all():
        sign = 1.0 if t.side == "buy" else -1.0
        flows_by_date[t.executed_at] = (
            flows_by_date.get(t.executed_at, 0.0) + sign * t.quantity * t.price
        )

    bench_q = db.query(_Bench).filter_by(ticker=bench_ticker)
    if from_date is not None:
        bench_q = bench_q.filter(_Bench.date >= from_date)
    if to_date is not None:
        bench_q = bench_q.filter(_Bench.date <= to_date)
    bench = [(b.date, b.close) for b in bench_q.order_by(_Bench.date).all()]
    if port:
        start = port[0][0]
        bench = [(d, v) for d, v in bench if d >= start]
    port_rebased = twr_series(port, flows_by_date)
    bench_rebased = rebase_series(bench)
    bench_name = {"^KS11": "KOSPI", "^GSPC": "S&P 500"}.get(bench_ticker, bench_ticker)
    return {
        "benchmark_ticker": bench_ticker,
        "benchmark_name": bench_name,
        "portfolio": [{"date": d.isoformat(), "value": v} for d, v in port_rebased],
        "benchmark": [{"date": d.isoformat(), "value": v} for d, v in bench_rebased],
    }
