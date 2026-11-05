"""Mailpit 邮件 provider（开发期默认）。

Mailpit 是本地 SMTP 沙箱（v1.32.0）：
- SMTP  : 127.0.0.1:1025  收信
- Web/API: http://127.0.0.1:8025
- 邮件原始 EML: GET /api/v1/message/{ID}.eml

本 provider 通过 HTTP API 拉原始 EML，再交给 parser 统一解析，
这样 Mailpit 与真实 IMAP 走同一套解析逻辑，避免"本地能跑、真实邮箱翻车"。
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import httpx

from app.config import settings
from app.mail.base import MailProvider, ParsedMail
from app.mail.parser import parse_raw_email

logger = logging.getLogger(__name__)


def _norm_mid(value: str | None) -> str:
    """Mailpit 列表里的 MessageID 去掉了尖括号，这里统一归一化再比较。"""
    return (value or "").strip().strip("<>").lower()


class MailpitError(RuntimeError):
    pass


class MailpitProvider(MailProvider):
    name = "mailpit"

    def __init__(self, api_base: str | None = None, timeout: float = 10.0):
        self.api_base = (api_base or settings.mailpit_api_base).rstrip("/")
        self.timeout = timeout

    # ---------------- 收信 ----------------
    def _list_messages(self, client: httpx.Client) -> list[dict]:
        resp = client.get(f"{self.api_base}/api/v1/messages", params={"limit": 500})
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("messages", [])

    def fetch_new(self, known_message_ids: set[str] | None = None) -> list[ParsedMail]:
        known = known_message_ids or set()
        known_norm = {_norm_mid(m) for m in known}
        mails: list[ParsedMail] = []
        with httpx.Client(timeout=self.timeout) as client:
            try:
                items = self._list_messages(client)
            except httpx.HTTPError as exc:
                raise MailpitError(f"连接 Mailpit 失败：{exc}") from exc

            for item in items:
                mid = _norm_mid(item.get("MessageID"))
                if mid and mid in known_norm:
                    continue
                mail_id = item.get("ID")
                if not mail_id:
                    continue
                try:
                    raw = client.get(
                        f"{self.api_base}/api/v1/message/{mail_id}/raw"
                    )
                    raw.raise_for_status()
                    created = _parse_created(item.get("Created"))
                    mails.append(parse_raw_email(raw.content, fallback_received_at=created))
                except Exception:
                    logger.exception("解析 Mailpit 邮件失败 id=%s", mail_id)
        logger.info("Mailpit 拉取到 %d 封新邮件", len(mails))
        return mails

    # ---------------- 发信 ----------------
    def send(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        *,
        body_html: str | None = None,
        in_reply_to: str | None = None,
        references: list[str] | None = None,
    ) -> str:
        recipients = [to] if isinstance(to, str) else list(to)
        msg = EmailMessage()
        msg["From"] = settings.smtp_from
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="inquiry-agent.local")
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = " ".join(references)
        msg.set_content(body)
        if body_html:
            msg.add_alternative(body_html, subtype="html")

        # 本机主机名含中文，必须显式 local_hostname，否则 EHLO 报 ASCII 编码错误
        if settings.smtp_ssl and settings.smtp_port != 1025:
            server = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=20,
                local_hostname="localhost",
            )
        else:
            server = smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=20,
                local_hostname="localhost",
            )
        with server:
            if settings.smtp_password and not settings.smtp_ssl:
                server.starttls()
                server.login(settings.smtp_from, settings.smtp_password)
            server.send_message(msg)
        logger.info("已通过 Mailpit 发送邮件 to=%s subject=%s", recipients, subject)
        return str(msg["Message-ID"])


def _parse_created(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
