"""轮询健康监控：连续失败 → 告警；恢复 → 通知。

状态存 `app_state.sync_monitor`（JSON），这样进程重启后计数和冷却还在。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from app.alert import send_alert
from app.config import settings
from app.db.models import AppState
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

STATE_KEY = "sync_monitor"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load(session) -> dict:
    row = session.get(AppState, STATE_KEY)
    if row is None or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return {}


def _save(session, state: dict) -> None:
    row = session.get(AppState, STATE_KEY)
    value = json.dumps(state)
    if row is None:
        session.add(AppState(key=STATE_KEY, value=value))
    else:
        row.value = value
    session.commit()


def load_health() -> dict:
    with SessionLocal() as session:
        state = _load(session)
    return {
        "last_sync_at": state.get("last_sync_at"),
        "last_ok_at": state.get("last_ok_at"),
        "consecutive_failures": int(state.get("failures", 0)),
        "alert_active": bool(state.get("alert_active", False)),
        "last_alert_at": state.get("last_alert_at"),
        "last_error": state.get("last_error"),
    }


def record_success() -> None:
    now = _now()
    with SessionLocal() as session:
        state = _load(session)
        was_alerting = bool(state.get("alert_active"))
        state.update(
            {
                "last_sync_at": now.isoformat(),
                "last_ok_at": now.isoformat(),
                "failures": 0,
                "alert_active": False,
                "last_error": None,
            }
        )
        _save(session, state)
    if was_alerting:
        send_alert(
            "【询盘 Agent】已恢复",
            f"IMAP 同步已恢复正常（{now.isoformat()}），连续失败计数已清零。",
        )


def record_failure(error: str) -> None:
    now = _now()
    failures = 0
    should_alert = False
    with SessionLocal() as session:
        state = _load(session)
        failures = int(state.get("failures", 0)) + 1
        state.update(
            {
                "last_sync_at": now.isoformat(),
                "failures": failures,
                "last_error": (error or "")[:500],
            }
        )

        if failures >= settings.alert_after_failures:
            cooldown = timedelta(minutes=settings.alert_cooldown_minutes)
            last_alert_raw = state.get("last_alert_at")
            last_alert: datetime | None = None
            if last_alert_raw:
                try:
                    last_alert = datetime.fromisoformat(last_alert_raw)
                except ValueError:
                    last_alert = None
            if last_alert is None or now - last_alert >= cooldown:
                should_alert = True
                state["alert_active"] = True
                state["last_alert_at"] = now.isoformat()

        _save(session, state)

    if should_alert:
        logger.warning("IMAP 同步连续失败 %d 次，发送告警", failures)
        send_alert(
            f"【询盘 Agent 告警】IMAP 同步连续失败 {failures} 次",
            (
                f"时间：{now.isoformat()}\n"
                f"连续失败：{failures} 次\n"
                f"最近错误：{(error or '')[:500]}\n\n"
                "建议：\n"
                "1. 检查邮箱授权码是否失效（QQ 邮箱重置过就会失效）\n"
                "2. 确认 IMAP 服务仍开启\n"
                "3. 查看后端日志定位\n\n"
                "恢复后会自动发一封「已恢复」邮件。"
            ),
        )
