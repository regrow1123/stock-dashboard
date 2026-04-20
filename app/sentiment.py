"""Market-sentiment indicators fetched from external sources, cached in meta."""

import json
import urllib.request
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Meta

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
META_KEY = "cnn_fg"
TTL_SECONDS = 3600  # CNN updates daily; refresh hourly


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def fetch_cnn_fg() -> dict:
    req = urllib.request.Request(
        CNN_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.cnn.com/",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    fg = data.get("fear_and_greed", {})
    return {
        "score": fg.get("score"),
        "rating": fg.get("rating"),
        "previous_close": fg.get("previous_close"),
        "previous_1_week": fg.get("previous_1_week"),
        "previous_1_month": fg.get("previous_1_month"),
        "previous_1_year": fg.get("previous_1_year"),
        "as_of": fg.get("timestamp"),
    }


def cnn_fg(db: Session) -> dict | None:
    """Return cached CNN F&G if fresh, else refetch and cache. None on failure."""
    row = db.get(Meta, META_KEY)
    now = _now_ts()
    if row:
        try:
            cached = json.loads(row.value)
            if now - cached.get("_fetched_at", 0) < TTL_SECONDS:
                return cached.get("data")
        except (ValueError, KeyError):
            pass
    try:
        data = fetch_cnn_fg()
    except Exception:
        # serve stale cache if available
        if row:
            try:
                return json.loads(row.value).get("data")
            except ValueError:
                return None
        return None
    blob = json.dumps({"_fetched_at": now, "data": data})
    if row:
        row.value = blob
    else:
        db.add(Meta(key=META_KEY, value=blob))
    db.commit()
    return data
