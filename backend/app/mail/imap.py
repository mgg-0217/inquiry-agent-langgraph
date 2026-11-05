"""真实邮箱 IMAP/SMTP provider（第 11 天）。

关键设计：
- **首次连接建立 UID 基线**：记录当时的 UIDNEXT，之后只拉「UID ≥ 基线」的新邮件，
  不会把历史收件箱（810 封）全部导入，也不会每轮重复扫描当天旧邮件
- QQ / 163 登录后必须发送 ID 命令，否则 SELECT 报 Unsafe Login
- 解析复用 `parser.parse_raw_email`，与 Mailpit 链路同一套 MIME 处理
- 发送用 SMTP（QQ 465 SSL），`local_hostname="localhost"` 规避中文主机名
"""

from __future__ import annotations

import imaplib
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.config import settings
from app.db.models import AppState
from app.db.session import SessionLocal
from app.mail.base import MailProvider, ParsedMail
from app.mail.parser import parse_raw_email

logger = logging.getLogger(__name__)

BASELINE_TIME_KEY = "imap_baseline_time"
BASELINE_UID_KEY = "imap_baseline_uid"
BASELINE_UIDVALIDITY_KEY = "imap_baseline_uidvalidity"
BASELINE_USER_KEY = "imap_baseline_user"
ID_PAYLOAD = '("name" "inquiry-agent" "version" "1.0" "vendor" "python")'


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _resp_int(conn: imaplib.IMAP4, name: str) -> int | None:
    try:
        _typ, data = conn.response(name)
    except Exception:  # noqa: BLE001
        return None
    if data and data[0]:
        try:
            return int(data[0])
        except (TypeError, ValueError):
            return None
    return None


def _set_state(session, key: str, value: str) -> None:
    row = session.get(AppState, key)
    if row is None:
        session.add(AppState(key=key, value=value))
    else:
        row.value = value


def establish_baseline(conn: imaplib.IMAP4) -> tuple[datetime, int]:
    """首次连接记录「现在 + UIDNEXT」；换邮箱 / UIDVALIDITY 变化时自动重建。"""
    uidvalidity = _resp_int(conn, "UIDVALIDITY") or 0
    with SessionLocal() as session:
        time_row = session.get(AppState, BASELINE_TIME_KEY)
        uid_row = session.get(AppState, BASELINE_UID_KEY)
        uvi_row = session.get(AppState, BASELINE_UIDVALIDITY_KEY)
        user_row = session.get(AppState, BASELINE_USER_KEY)

        same_mailbox = (
            uvi_row is not None
            and user_row is not None
            and uvi_row.value == str(uidvalidity)
            and user_row.value == settings.imap_user
        )
        if time_row and uid_row and same_mailbox:
            try:
                return datetime.fromisoformat(time_row.value), int(uid_row.value)
            except ValueError:
                logger.warning("IMAP 基线格式异常，重建")

        # 基线缺失、换了邮箱、或 UIDVALIDITY 变了：以当前 UIDNEXT 为新起点
        uidnext = _resp_int(conn, "UIDNEXT") or 1
        now = _utcnow()
        _set_state(session, BASELINE_TIME_KEY, now.isoformat())
        _set_state(session, BASELINE_UID_KEY, str(uidnext))
        _set_state(session, BASELINE_UIDVALIDITY_KEY, str(uidvalidity))
        _set_state(session, BASELINE_USER_KEY, settings.imap_user)
        session.commit()
        logger.warning(
            "IMAP 基线重建：user=%s uidvalidity=%s uidnext=%s（只拉之后的新邮件）",
            settings.imap_user,
            uidvalidity,
            uidnext,
        )
        return now, uidnext


class ImapProvider(MailProvider):
    name = "imap"

    def __init__(self) -> None:
        self.host = settings.imap_host
        self.port = settings.imap_port
        self.user = settings.imap_user
        self.password = settings.imap_password

    # ---------------- 连接 ----------------
    def _connect(self) -> imaplib.IMAP4:
        if settings.imap_ssl:
            conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(self.host, self.port, timeout=30)
        else:
            conn = imaplib.IMAP4(self.host, self.port, timeout=30)

        # QQ / 163 邮箱必需：登录后发送 ID，否则 SELECT 会报 Unsafe Login
        imaplib.Commands["ID"] = ("AUTH", "SELECTED", "NONAUTH")
        try:
            conn._simple_command("ID", ID_PAYLOAD)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ID 命令失败（部分服务商不需要）：%s", exc)

        conn.login(self.user, self.password)
        return conn

    # ---------------- 收信 ----------------
    def fetch_new(self, known_message_ids: set[str] | None = None) -> list[ParsedMail]:
        conn = self._connect()
        try:
            typ, _ = conn.select("INBOX", readonly=True)
            if typ != "OK":
                raise RuntimeError("无法打开 INBOX")

            baseline_time, baseline_uid = establish_baseline(conn)
            typ, data = conn.uid("SEARCH", None, f"UID {baseline_uid}:*")
            if typ != "OK":
                raise RuntimeError(f"IMAP SEARCH 失败：{data}")
            uids = (data[0] or b"").split()
            logger.info("IMAP 基线 uid=%s，候选 %d 封", baseline_uid, len(uids))

            mails: list[ParsedMail] = []
            for uid in uids:
                try:
                    uid_int = int(uid)
                except (TypeError, ValueError):
                    continue
                if uid_int < baseline_uid:
                    continue
                typ, msg_data = conn.uid("FETCH", uid, "(RFC822)")
                if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                raw = msg_data[0][1]
                if not raw:
                    continue
                try:
                    mail = parse_raw_email(raw)
                except Exception:
                    logger.exception("IMAP 邮件解析失败 uid=%s", uid)
                    continue
                if mail.received_at is not None and mail.received_at <= baseline_time:
                    continue
                # 自己发的告警/通知会被投回 INBOX，不能当客户来信处理
                sender = (mail.from_email or "").lower()
                if sender and sender == (settings.smtp_from or "").lower():
                    logger.info("跳过自己发出的邮件 uid=%s（%s）", uid, mail.subject[:40])
                    continue
                # 不在 provider 层按已知 message_id 过滤：让入库层判重，
                # 这样同步报告里的 created / duplicated 才能反映真实结果
                mails.append(mail)
            return mails
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

    # ---------------- 基线推进 ----------------
    def advance_baseline(self) -> None:
        """同步成功后把基线推进到当前 UIDNEXT，避免每轮重复扫描旧邮件。"""
        conn = self._connect()
        try:
            typ, _ = conn.select("INBOX", readonly=True)
            if typ != "OK":
                return
            uidnext = _resp_int(conn, "UIDNEXT")
            uidvalidity = _resp_int(conn, "UIDVALIDITY") or 0
            if not uidnext:
                return
            with SessionLocal() as session:
                _set_state(session, BASELINE_TIME_KEY, _utcnow().isoformat())
                _set_state(session, BASELINE_UID_KEY, str(uidnext))
                _set_state(session, BASELINE_UIDVALIDITY_KEY, str(uidvalidity))
                _set_state(session, BASELINE_USER_KEY, settings.imap_user)
                session.commit()
            logger.info("IMAP 基线推进到 uidnext=%s", uidnext)
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

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
        msg["From"] = settings.smtp_from or self.user
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

        password = settings.smtp_password or self.password
        if settings.smtp_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=30,
                local_hostname="localhost",
            )
        else:
            server = smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=30,
                local_hostname="localhost",
            )
        with server:
            if not settings.smtp_ssl:
                server.starttls()
            server.login(self.user, password)
            server.send_message(msg)
        logger.info("IMAP provider 已发送邮件 to=%s", recipients)
        return str(msg["Message-ID"])
