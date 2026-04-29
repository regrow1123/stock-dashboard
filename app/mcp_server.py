from __future__ import annotations

from typing import Any

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.krx_listings import get_cache
from app.models import (
    Account, Dividend, Instrument, LivePrice, SeedHolding, Trade,
)


# ---------- Read-only tools ----------

def list_accounts(db: Session) -> list[dict[str, Any]]:
    accs = db.execute(select(Account).order_by(Account.display_order)).scalars().all()
    return [
        {"id": a.id, "name": a.name, "currency": a.currency, "broker": a.broker}
        for a in accs
    ]


def list_holdings(
    db: Session, account_id: str | None = None
) -> list[dict[str, Any]]:
    """Aggregate quantity from seeds + trades, decorate with current price."""
    accounts = (
        db.execute(select(Account).where(Account.id == account_id)).scalars().all()
        if account_id
        else db.execute(select(Account).order_by(Account.display_order)).scalars().all()
    )
    out: list[dict[str, Any]] = []
    for acc in accounts:
        seeds = {
            s.ticker: (s.quantity, s.avg_price)
            for s in db.execute(
                select(SeedHolding).where(SeedHolding.account_id == acc.id)
            ).scalars()
        }
        trades = db.execute(
            select(Trade).where(Trade.account_id == acc.id)
        ).scalars().all()
        # Aggregate ticker -> [qty, total_cost]
        agg: dict[str, list[float]] = {}
        for tk, (qty, avg) in seeds.items():
            agg[tk] = [qty, qty * avg]
        for t in trades:
            cur = agg.setdefault(t.ticker, [0.0, 0.0])
            if t.side == "buy":
                cur[0] += t.quantity
                cur[1] += t.quantity * t.price
            else:
                cur[0] -= t.quantity
                cur[1] -= t.quantity * t.price
        for tk, (qty, total_cost) in agg.items():
            if qty <= 0:
                continue
            avg_price = total_cost / qty if qty else 0.0
            inst = db.get(Instrument, tk)
            lp = db.get(LivePrice, tk)
            out.append({
                "account_id": acc.id,
                "ticker": tk,
                "name": inst.name if inst else tk,
                "quantity": qty,
                "avg_price": avg_price,
                "current_price": lp.price if lp else None,
                "value": (lp.price * qty) if lp else None,
            })
    return out


def recent_trades(
    db: Session, limit: int = 10, account_id: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(Trade).order_by(Trade.id.desc()).limit(limit)
    if account_id:
        stmt = (
            select(Trade).where(Trade.account_id == account_id)
            .order_by(Trade.id.desc()).limit(limit)
        )
    rows = db.execute(stmt).scalars().all()
    out: list[dict[str, Any]] = []
    for t in rows:
        inst = db.get(Instrument, t.ticker)
        out.append({
            "id": t.id, "account_id": t.account_id, "ticker": t.ticker,
            "name": inst.name if inst else t.ticker,
            "side": t.side, "quantity": t.quantity, "price": t.price,
            "executed_at": t.executed_at.isoformat(),
        })
    return out


def recent_dividends(
    db: Session, limit: int = 10, account_id: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(Dividend).order_by(Dividend.id.desc()).limit(limit)
    if account_id:
        stmt = (
            select(Dividend).where(Dividend.account_id == account_id)
            .order_by(Dividend.id.desc()).limit(limit)
        )
    rows = db.execute(stmt).scalars().all()
    out: list[dict[str, Any]] = []
    for d in rows:
        inst = db.get(Instrument, d.ticker)
        out.append({
            "id": d.id, "account_id": d.account_id, "ticker": d.ticker,
            "name": inst.name if inst else d.ticker,
            "amount": d.amount, "paid_at": d.paid_at.isoformat(),
        })
    return out


def search_ticker_kr(korean_name: str) -> list[dict[str, Any]]:
    cache = get_cache()
    return [
        {"ticker": t, "name": korean_name, "market": m}
        for t, m in cache.search_by_name(korean_name)
    ]


def verify_ticker_us(ticker: str) -> dict[str, Any] | None:
    info = yf.Ticker(ticker).info
    name = info.get("longName") or info.get("shortName")
    price = info.get("regularMarketPrice") or info.get("currentPrice")
    if not name:
        return None
    return {"ticker": ticker, "name_en": name, "current_price": price}


def lookup_ticker(db: Session, ticker: str) -> dict[str, Any]:
    inst = db.get(Instrument, ticker)
    if inst is not None:
        lp = db.get(LivePrice, ticker)
        return {
            "ticker": ticker, "name": inst.name,
            "currency": lp.currency if lp else None,
            "current_price": lp.price if lp else None,
        }
    info = yf.Ticker(ticker).info
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "currency": info.get("currency"),
        "current_price": info.get("regularMarketPrice") or info.get("currentPrice"),
    }
