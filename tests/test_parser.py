import json
from datetime import date
from unittest.mock import MagicMock

from app.parser import ParseResult, parse_message


def _fake_run(stdout: str, returncode: int = 0):
    r = MagicMock()
    r.stdout = stdout
    r.returncode = returncode
    return r


def test_parse_returns_trade(monkeypatch):
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "1")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    from app.config import get_settings
    get_settings.cache_clear()

    payload = {
        "type": "trade", "account": "mirae_kr", "ticker": "005930.KS",
        "side": "buy", "quantity": 10, "price": 75000,
        "executed_at": "2026-04-18", "confidence": 0.95, "note": "ok",
    }
    monkeypatch.setattr(
        "app.parser.subprocess.run",
        lambda *a, **kw: _fake_run(json.dumps(payload)),
    )
    r = parse_message("오늘 미래에셋에서 005930 10주 75000에 매수",
                     accounts=[{"id": "mirae_kr", "name": "미래에셋 국내"}],
                     today=date(2026, 4, 18))
    assert isinstance(r, ParseResult)
    assert r.type == "trade"
    assert r.ticker == "005930.KS"
    assert r.confidence >= 0.8


def test_parse_falls_back_to_unknown_on_garbage(monkeypatch):
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "1")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    from app.config import get_settings
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.parser.subprocess.run",
        lambda *a, **kw: _fake_run("not json at all"),
    )
    r = parse_message("뭐라는거야", accounts=[], today=date(2026, 4, 18))
    assert r.type == "unknown"
    assert r.confidence == 0.0
