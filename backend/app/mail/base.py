"""MailProvider 抽象接口。

两套实现（PRD F1）：
- mailpit.py：开发期，Mailpit 本地沙箱（SMTP 收信 + HTTP API 拉原始 EML）
- imap.py：真实邮箱（第 11 天实现）

provider 只负责"取信 / 发信"，不做入库、不做线程归并。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ParsedMail:
    """归一化后的单封邮件，parser 的统一产物。"""

    message_id: str
    subject: str
    from_email: str
    from_name: str = ""
    to_emails: list[str] = field(default_factory=list)
    cc_emails: list[str] = field(default_factory=list)
    body_text: str = ""
    body_html: str = ""
    attachments: list[dict] = field(default_factory=list)
    received_at: datetime | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    raw_headers: dict[str, str] = field(default_factory=dict)


class MailProvider(ABC):
    name: str = "base"

    @abstractmethod
    def fetch_new(self, known_message_ids: set[str] | None = None) -> list[ParsedMail]:
        """拉取邮件。

        known_message_ids：已入库的 Message-ID 集合，实现方可据此跳过下载原始邮件。
        返回顺序不保证，由调用方负责幂等。
        """

    @abstractmethod
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
        """发送邮件，返回 Message-ID。"""
