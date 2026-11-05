from __future__ import annotations

import pytest

from app import monitor


@pytest.fixture
def alert_calls(monkeypatch):
    calls: list[str] = []

    def fake_alert(subject: str, body: str) -> bool:
        calls.append(subject)
        return True

    monkeypatch.setattr(monitor, "send_alert", fake_alert)
    return calls


def test_alert_after_three_failures(session_factory, alert_calls, monkeypatch):
    monkeypatch.setattr(monitor, "SessionLocal", session_factory)
    for i in range(3):
        monitor.record_failure(f"err{i}")
    assert len(alert_calls) == 1
    assert "连续失败 3 次" in alert_calls[0]


def test_alert_cooldown_prevents_spam(session_factory, alert_calls, monkeypatch):
    monkeypatch.setattr(monitor, "SessionLocal", session_factory)
    for i in range(6):
        monitor.record_failure(f"err{i}")
    assert len(alert_calls) == 1


def test_recovery_sends_notice(session_factory, alert_calls, monkeypatch):
    monkeypatch.setattr(monitor, "SessionLocal", session_factory)
    for i in range(3):
        monitor.record_failure(f"err{i}")
    monitor.record_success()
    assert len(alert_calls) == 2
    assert "已恢复" in alert_calls[1]


def test_success_resets_failures(session_factory, monkeypatch):
    monkeypatch.setattr(monitor, "SessionLocal", session_factory)
    monkeypatch.setattr(monitor, "send_alert", lambda subject, body: True)
    monitor.record_failure("err")
    monitor.record_failure("err")
    monitor.record_success()
    health = monitor.load_health()
    assert health["consecutive_failures"] == 0
    assert health["alert_active"] is False


def test_no_alert_before_threshold(session_factory, alert_calls, monkeypatch):
    monkeypatch.setattr(monitor, "SessionLocal", session_factory)
    monitor.record_failure("err1")
    monitor.record_failure("err2")
    assert alert_calls == []
