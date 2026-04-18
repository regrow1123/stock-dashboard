from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.metrics import avg_cost_from_seed_and_trades, pct_return, weights_from_values
from app.models import (
    Account, Dividend, LivePrice, SeedHolding, Snapshot, Trade,
)

router = APIRouter(prefix="/api")


def get_db():
    raise RuntimeError("overridden by app factory")


def _live(db: Session, ticker: str) -> float | None:
    r = db.get(LivePrice, ticker)
    return float(r.price) if r else None


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
        out.append({
            "ticker": tk,
            "quantity": qty,
            "avg_price": avg,
            "cost": cost,
            "current_price": current,
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
    values = {r["ticker"]: r["value"] for r in rows}
    return [{"ticker": k, "weight": v} for k, v in weights_from_values(values).items()]


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    accounts = db.query(Account).order_by(Account.display_order).all()
    by_account = []
    by_currency: dict[str, dict[str, float]] = {}
    for a in accounts:
        rows = _holdings_for(db, a.id)
        value = sum(r["value"] for r in rows)
        cost = sum(r["cost"] for r in rows)
        by_account.append({
            "account_id": a.id, "name": a.name, "broker": a.broker,
            "currency": a.currency, "value": value, "cost": cost,
            "pnl": value - cost, "pct_return": pct_return(cost, value),
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
def account_history(account_id: str, db: Session = Depends(get_db)):
    if db.get(Account, account_id) is None:
        raise HTTPException(404)
    by_date: dict[date, float] = {}
    for s in db.query(Snapshot).filter_by(account_id=account_id).all():
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
    return [
        {"id": t.id, "ticker": t.ticker, "side": t.side,
         "quantity": t.quantity, "price": t.price,
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
