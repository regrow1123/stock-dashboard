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
        {"ticker": t, "name": cache.get_name(t) or korean_name, "market": m}
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


# ---------- Write tools ----------

from datetime import date, timedelta  # noqa: E402

from app.prices import backfill_prices, refresh_live_prices  # noqa: E402
from app.snapshots import recompute_snapshots  # noqa: E402


def register_instrument(db: Session, ticker: str, name: str) -> dict[str, Any]:
    from app.sectors import fetch_sector

    inst = db.get(Instrument, ticker)
    if inst is None:
        sector = None
        try:
            sector = fetch_sector(ticker)
        except Exception:
            sector = None  # best-effort; registration must not fail
        db.add(Instrument(ticker=ticker, name=name, sector=sector))
    else:
        inst.name = name
    db.commit()
    return {"ok": True, "ticker": ticker, "name": name}


def _post_save_recompute(
    db: Session, *, account_id: str, ticker: str,
    executed_at: date, currency: str | None,
) -> None:
    """Backfill prices for the new ticker (best-effort) and recompute snapshots."""
    today = date.today()
    if currency is not None:
        try:
            backfill_prices(
                db, ticker=ticker, currency=currency,
                start=executed_at - timedelta(days=14),
                end=today + timedelta(days=1),
            )
        except Exception:
            pass
        try:
            refresh_live_prices(db, tickers=[ticker])
        except Exception:
            pass
    recompute_snapshots(
        db, account_id=account_id, from_date=executed_at, to_date=today,
    )


def _post_cancel_recompute(db: Session, *, account_id: str, executed_at: date) -> None:
    recompute_snapshots(
        db, account_id=account_id, from_date=executed_at, to_date=date.today(),
    )


def record_trade(
    db: Session, *, account_id: str, ticker: str, side: str,
    quantity: float, price: float, executed_at: date,
    name: str | None = None,
) -> dict[str, Any]:
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "invalid_side"}
    acc = db.get(Account, account_id)
    if acc is None:
        return {"ok": False, "error": "unknown_account"}
    if name is not None:
        register_instrument(db, ticker, name)
    trade = Trade(
        account_id=account_id, ticker=ticker, side=side,
        quantity=quantity, price=price, executed_at=executed_at,
        raw_text="", tg_message_id=None,
    )
    db.add(trade)
    db.commit()
    _post_save_recompute(
        db, account_id=account_id, ticker=ticker,
        executed_at=executed_at, currency=acc.currency,
    )
    return {"ok": True, "trade_id": trade.id}


def record_dividend(
    db: Session, *, account_id: str, ticker: str,
    amount: float, paid_at: date, name: str | None = None,
) -> dict[str, Any]:
    if db.get(Account, account_id) is None:
        return {"ok": False, "error": "unknown_account"}
    if name is not None:
        register_instrument(db, ticker, name)
    div = Dividend(
        account_id=account_id, ticker=ticker, amount=amount,
        paid_at=paid_at, raw_text="", tg_message_id=None,
    )
    db.add(div)
    db.commit()
    return {"ok": True, "dividend_id": div.id}


def cancel_trade(db: Session, trade_id: int) -> dict[str, Any]:
    t = db.get(Trade, trade_id)
    if t is None:
        return {"ok": False, "error": "not_found"}
    summary = {
        "ticker": t.ticker, "side": t.side, "quantity": t.quantity,
        "price": t.price, "executed_at": t.executed_at.isoformat(),
        "account_id": t.account_id,
    }
    account_id = t.account_id
    executed_at = t.executed_at
    db.delete(t)
    db.commit()
    _post_cancel_recompute(db, account_id=account_id, executed_at=executed_at)
    return {"ok": True, "removed": summary}


# ---------- MCP stdio entrypoint ----------

from datetime import date as _date  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app.db import make_engine, make_session_factory  # noqa: E402

mcp = FastMCP("stock-dashboard")

_session_factory = None


def _sf():
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(make_engine())
    return _session_factory


def _with_session(fn, *args, **kwargs):
    db = _sf()()
    try:
        return fn(db, *args, **kwargs)
    finally:
        db.close()


@mcp.tool()
def t_list_accounts() -> list[dict]:
    """List all portfolio accounts with id, name, currency, broker."""
    return _with_session(list_accounts)


@mcp.tool()
def t_list_holdings(account_id: str | None = None) -> list[dict]:
    """List current holdings (with current price + value), optionally filtered by account."""
    return _with_session(list_holdings, account_id=account_id)


@mcp.tool()
def t_recent_trades(limit: int = 10, account_id: str | None = None) -> list[dict]:
    """Most recent trades (descending by id)."""
    return _with_session(recent_trades, limit=limit, account_id=account_id)


@mcp.tool()
def t_recent_dividends(limit: int = 10, account_id: str | None = None) -> list[dict]:
    """Most recent dividends (descending by id)."""
    return _with_session(recent_dividends, limit=limit, account_id=account_id)


@mcp.tool()
def t_search_ticker_kr(korean_name: str) -> list[dict]:
    """Search KRX listings by Korean name. Returns 0..N candidates."""
    return search_ticker_kr(korean_name)


@mcp.tool()
def t_verify_ticker_us(ticker: str) -> dict | None:
    """Verify a US ticker via yfinance. Returns null if not found."""
    return verify_ticker_us(ticker)


@mcp.tool()
def t_lookup_ticker(ticker: str) -> dict:
    """Resolve a ticker to {name, currency, current_price}. Cache first, yfinance fallback."""
    return _with_session(lookup_ticker, ticker)


@mcp.tool()
def t_record_trade(
    account_id: str, ticker: str, side: str,
    quantity: float, price: float, executed_at: str,
    name: str | None = None,
) -> dict:
    """Record a buy or sell. Pass name to also register the ticker name."""
    return _with_session(
        record_trade,
        account_id=account_id, ticker=ticker, side=side,
        quantity=quantity, price=price,
        executed_at=_date.fromisoformat(executed_at), name=name,
    )


@mcp.tool()
def t_record_dividend(
    account_id: str, ticker: str, amount: float,
    paid_at: str, name: str | None = None,
) -> dict:
    """Record a cash dividend payment."""
    return _with_session(
        record_dividend,
        account_id=account_id, ticker=ticker, amount=amount,
        paid_at=_date.fromisoformat(paid_at), name=name,
    )


@mcp.tool()
def t_cancel_trade(trade_id: int) -> dict:
    """Delete a trade by id and recompute snapshots from its date forward."""
    return _with_session(cancel_trade, trade_id)


@mcp.tool()
def t_register_instrument(ticker: str, name: str) -> dict:
    """Map a ticker to its display name (Korean or English)."""
    return _with_session(register_instrument, ticker, name)


if __name__ == "__main__":
    mcp.run()
