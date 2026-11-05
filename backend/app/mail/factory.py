"""MailProvider 工厂：按 .env 的 MAIL_PROVIDER 选择实现。"""

from __future__ import annotations

from app.config import settings
from app.mail.base import MailProvider
from app.mail.mailpit import MailpitProvider


def build_provider() -> MailProvider:
    name = (settings.mail_provider or "mailpit").lower()
    if name == "mailpit":
        return MailpitProvider()
    if name == "imap":
        # 第 11 天实现：真实邮箱 IMAP 收信 + SMTP 发信
        from app.mail.imap import ImapProvider

        return ImapProvider()
    raise ValueError(f"未知 MAIL_PROVIDER: {name}")
