"""MIME 解析：把原始邮件字节归一化成 ParsedMail。

真实 IMAP 和 Mailpit 的 .eml 都走这里，保证两条链路的解析行为一致。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from app.mail.base import ParsedMail

# Re: / Re[2]: / Fwd: / FW: / 回复：/ 转发：
_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*((re|fw|fwd|aw|sv|回复|答复|转发)\s*(\[\d+\])?\s*[:：]\s*)+",
    re.IGNORECASE,
)
_MSGID_RE = re.compile(r"<[^<>\s]+>")


def normalize_subject(subject: str) -> str:
    """线程归并兜底用：去回复前缀、压缩空白、转小写。"""
    s = _SUBJECT_PREFIX_RE.sub("", subject or "")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # pragma: no cover - 非法编码兜底
        return value


def _address_str_list(pairs: list[tuple[str, str]]) -> list[str]:
    return [f"{name} <{addr}>" if name else addr for name, addr in pairs if addr]


def _split_references(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        out.extend(_MSGID_RE.findall(raw))
    # 去重保持顺序
    seen: set[str] = set()
    uniq: list[str] = []
    for mid in out:
        if mid not in seen:
            seen.add(mid)
            uniq.append(mid)
    return uniq


def _extract_body(msg: EmailMessage) -> tuple[str, str]:
    """返回 (text, html)。分别取第一个 text/plain 与 text/html 的完整内容。"""
    text_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            if ctype == "text/plain":
                text_parts.append(_part_text(part))
            elif ctype == "text/html":
                html_parts.append(_part_text(part))
    else:
        ctype = msg.get_content_type()
        if ctype == "text/html":
            html_parts.append(_part_text(msg))
        else:
            text_parts.append(_part_text(msg))
    return "\n".join(p for p in text_parts if p), "\n".join(p for p in html_parts if p)


def _part_text(part: EmailMessage) -> str:
    try:
        return part.get_content()
    except Exception:  # pragma: no cover - 异常编码兜底
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def _extract_attachments(msg: EmailMessage) -> list[dict]:
    out: list[dict] = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        disposition = part.get("Content-Disposition", "")
        if not filename and not disposition.startswith("attachment"):
            continue
        payload = part.get_payload(decode=True) or b""
        out.append(
            {
                "filename": _decode(filename) if filename else "unnamed",
                "content_type": part.get_content_type(),
                "size": len(payload),
                "content_id": (part.get("Content-ID") or "").strip("<>") or None,
            }
        )
    return out


def _parse_single_message_id(value: str | None) -> str | None:
    if not value:
        return None
    found = _MSGID_RE.findall(value)
    return found[0] if found else value.strip() or None


def _raw_headers(msg: EmailMessage) -> dict[str, str]:
    """按原始值读取头，绕过 email.headerregistry 的严格解析。

    有些真实邮件（例如 Microsoft 出站）的 Message-ID 形如
    `<[1d97...-JFB...@microsoft.com]>`，headerregistry 会抛 IndexError；
    这里直接用 raw_items() 拿未经解析的字符串，保证邮件不会因为一个头崩掉。
    """
    headers: dict[str, str] = {}
    for name, value in msg.raw_items():
        key = name.lower()
        if key not in headers:
            headers[key] = value
    return headers


def parse_raw_email(raw: bytes, fallback_received_at: datetime | None = None) -> ParsedMail:
    """解析原始邮件字节（RFC 822）。"""
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)
    headers = _raw_headers(msg)

    message_id = _parse_single_message_id(headers.get("message-id"))
    if not message_id:
        # 极少数邮件没有（或无法解析）Message-ID：用内容哈希兜底，保证幂等
        message_id = f"<generated-{hashlib.sha1(raw).hexdigest()}@local>"

    from_pairs = getaddresses([headers.get("from", "")])
    to_pairs = getaddresses([headers.get("to", "")])
    cc_pairs = getaddresses([headers.get("cc", "")])
    from_name, from_email = "", ""
    if from_pairs:
        from_name, from_email = from_pairs[0]
        from_name = _decode(from_name)

    received_at = fallback_received_at
    if received_at is None:
        try:
            received_at = parsedate_to_datetime(headers.get("date", ""))
        except Exception:
            received_at = None
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    # 统一转成 UTC naive，便于 sqlite 存取与比较
    received_at = received_at.astimezone(timezone.utc).replace(tzinfo=None)

    body_text, body_html = _extract_body(msg)
    subject = _decode(headers.get("subject", ""))
    references_raw = headers.get("references", "")

    return ParsedMail(
        message_id=message_id,
        subject=subject,
        from_email=from_email.lower(),
        from_name=from_name,
        to_emails=_address_str_list(to_pairs),
        cc_emails=_address_str_list(cc_pairs),
        body_text=body_text,
        body_html=body_html,
        attachments=_extract_attachments(msg),
        received_at=received_at,
        in_reply_to=_parse_single_message_id(headers.get("in-reply-to")),
        references=_split_references([references_raw] if references_raw else []),
        raw_headers={"subject": subject},
    )
