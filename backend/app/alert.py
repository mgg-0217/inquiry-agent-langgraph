"""系统告警邮件。

与客户邮件不同：告警直接走 provider 的 SMTP，**不经过** `SEND_WHITELIST`
（那是限制给客户发信的，不是运维通知）。
告警失败不能拖垮主流程，所以这里只记日志、不抛异常。
"""

from __future__ import annotations

import logging

from app.config import settings
from app.mail.factory import build_provider

logger = logging.getLogger(__name__)


def send_alert(subject: str, body: str) -> bool:
    if not settings.alert_email:
        logger.info("告警未发送（ALERT_EMAIL 未配置）：%s", subject)
        return False
    try:
        build_provider().send(settings.alert_email, subject, body)
        logger.warning("已发送告警邮件：%s -> %s", subject, settings.alert_email)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("告警邮件发送失败：%s", subject)
        return False
