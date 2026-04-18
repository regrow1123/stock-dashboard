import os

from app.config import Settings


def test_settings_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "42")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("CLAUDE_BIN", "claude")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "d.db"))
    monkeypatch.setenv("SEED_PATH", str(tmp_path / "seed.yaml"))
    s = Settings()
    assert s.tg_bot_token == "t"
    assert s.tg_chat_id == 42
    assert s.port == 8080
    assert s.db_url.startswith("sqlite:///")
