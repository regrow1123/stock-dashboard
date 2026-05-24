from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from app.benchmarks import backfill_benchmark
from app.models import Benchmark


def test_backfill_benchmark(db, monkeypatch):
    def fake_download(ticker, start, end, progress=False, auto_adjust=False):
        idx = pd.to_datetime(["2026-04-15", "2026-04-16"])
        return pd.DataFrame({"Close": [5000.0, 5050.0]}, index=idx)

    fake_yf = MagicMock()
    fake_yf.download.side_effect = fake_download
    monkeypatch.setattr("app.benchmarks.yf", fake_yf)

    backfill_benchmark(db, ticker="^GSPC",
                       start=date(2026, 4, 15), end=date(2026, 4, 17))
    rows = db.query(Benchmark).order_by(Benchmark.date).all()
    assert len(rows) == 2
    assert rows[1].close == 5050.0
