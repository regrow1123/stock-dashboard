from datetime import datetime, timedelta

from app.agent import SlidingWindow


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
