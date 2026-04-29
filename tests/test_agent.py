from datetime import datetime, timedelta
from unittest.mock import MagicMock

from app.agent import SlidingWindow, build_prompt, run_agent


def test_window_renders_recent_messages():
    w = SlidingWindow(max_messages=10, max_age=timedelta(minutes=30))
    t0 = datetime(2026, 4, 29, 12, 0)
    w.append("user", "hi", at=t0)
    w.append("assistant", "hello!", at=t0 + timedelta(seconds=1))
    rendered = w.render(at=t0 + timedelta(seconds=5))
    assert "user: hi" in rendered
    assert "assistant: hello!" in rendered


def test_window_drops_old_messages():
    w = SlidingWindow(max_messages=10, max_age=timedelta(minutes=30))
    t0 = datetime(2026, 4, 29, 12, 0)
    w.append("user", "old", at=t0)
    w.append("user", "new", at=t0 + timedelta(minutes=31))
    rendered = w.render(at=t0 + timedelta(minutes=31, seconds=1))
    assert "old" not in rendered
    assert "new" in rendered


def test_window_caps_message_count():
    w = SlidingWindow(max_messages=3, max_age=timedelta(hours=1))
    t0 = datetime(2026, 4, 29, 12, 0)
    for i in range(5):
        w.append("user", f"m{i}", at=t0 + timedelta(seconds=i))
    rendered = w.render(at=t0 + timedelta(seconds=10))
    assert "m0" not in rendered
    assert "m1" not in rendered
    assert "m2" in rendered
    assert "m3" in rendered
    assert "m4" in rendered


def test_empty_window_renders_placeholder():
    w = SlidingWindow()
    out = w.render()
    assert "(empty" in out


def test_build_prompt_includes_window_and_message():
    w = SlidingWindow()
    w.append("user", "earlier message", at=datetime(2026, 4, 29, 12, 0))
    prompt = build_prompt(window=w, message="latest", at=datetime(2026, 4, 29, 12, 0, 5))
    assert "earlier message" in prompt
    assert "latest" in prompt
    assert "Tools:" in prompt
    assert "Resolution rules" in prompt


def test_run_agent_invokes_claude_and_returns_stdout(monkeypatch):
    fake_run = MagicMock()
    fake_run.return_value = MagicMock(
        returncode=0, stdout="✅ 매수 기록", stderr="",
    )
    monkeypatch.setattr("app.agent.subprocess.run", fake_run)
    out = run_agent("뉴로핏 10주 매수")
    assert out == "✅ 매수 기록"
    args, kwargs = fake_run.call_args
    cmd = args[0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--mcp-config" in cmd


def test_system_prompt_documents_options_marker():
    from app.agent import SYSTEM_PROMPT
    assert "[OPTIONS:" in SYSTEM_PROMPT
    assert "마지막 줄" in SYSTEM_PROMPT
    assert "21자" in SYSTEM_PROMPT


def test_run_agent_returns_error_text_on_failure(monkeypatch):
    fake_run = MagicMock()
    fake_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
    monkeypatch.setattr("app.agent.subprocess.run", fake_run)
    out = run_agent("hi")
    assert "오류" in out or "error" in out.lower()
