from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.mail.parser import normalize_subject, parse_raw_email


def _eml(
    *,
    subject: str,
    body: str,
    from_addr: str = "Carlos Mendoza <carlos@acme-import.example>",
    to: str = "sales@example.com",
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    attachment: bool = False,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id or make_msgid(domain="acme-import.example")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(references)
    msg.set_content(body)
    if attachment:
        msg.add_attachment(
            b"%PDF-1.4 fake",
            maintype="application",
            subtype="pdf",
            filename="specification.pdf",
        )
    return msg.as_bytes()


class TestNormalizeSubject:
    def test_strip_english_prefixes(self):
        assert normalize_subject("Re: Re: Fwd: Inquiry X200") == "inquiry x200"
        assert normalize_subject("RE[2]: Inquiry X200") == "inquiry x200"

    def test_strip_chinese_prefixes(self):
        assert normalize_subject("回复：询盘 X200") == "询盘 x200"
        assert normalize_subject("转发: 回复: 询盘") == "询盘"

    def test_collapse_whitespace(self):
        assert normalize_subject("  Inquiry   X200  ") == "inquiry x200"


class TestParseRawEmail:
    def test_chinese_subject_and_body(self):
        raw = _eml(subject="询盘：X200 离心泵 500 台", body="你好，我们想询价 500 台。")
        mail = parse_raw_email(raw)
        assert mail.subject == "询盘：X200 离心泵 500 台"
        assert "500 台" in mail.body_text
        assert mail.from_email == "carlos@acme-import.example"
        assert mail.from_name == "Carlos Mendoza"

    def test_message_id_and_threading_headers(self):
        parent = "<parent-001@acme-import.example>"
        raw = _eml(
            subject="Re: Inquiry X200",
            body="Thanks.",
            in_reply_to=parent,
            references=[f"<root-000@acme-import.example>", parent],
        )
        mail = parse_raw_email(raw)
        assert mail.message_id.startswith("<")
        assert mail.in_reply_to == parent
        assert mail.references == ["<root-000@acme-import.example>", parent]

    def test_attachment_metadata(self):
        raw = _eml(subject="With attachment", body="see attached", attachment=True)
        mail = parse_raw_email(raw)
        assert len(mail.attachments) == 1
        att = mail.attachments[0]
        assert att["filename"] == "specification.pdf"
        assert att["content_type"] == "application/pdf"
        assert att["size"] > 0

    def test_generated_message_id_when_missing(self):
        raw = (
            b"From: a@b.example\r\n"
            b"To: c@d.example\r\n"
            b"Subject: no message id\r\n"
            b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
            b"\r\nhi\r\n"
        )
        mail = parse_raw_email(raw)
        assert mail.message_id.startswith("<generated-")

    def test_malformed_message_id_does_not_crash(self):
        """真实邮件里 Microsoft 出站的 Message-ID 含方括号，headerregistry 会抛异常。"""
        raw = (
            b"From: a@b.example\r\n"
            b"To: c@d.example\r\n"
            b"Subject: malformed\r\n"
            b"Message-ID: <[1d97-JFBVALKQOJXWILKNK4YVA7CTORQXE5CFP@microsoft.com]>\r\n"
            b"Date: Fri, 30 Oct 2026 10:00:00 +0800\r\n"
            b"\r\nbody\r\n"
        )
        mail = parse_raw_email(raw)
        assert mail.message_id
        assert mail.from_email == "a@b.example"
        assert mail.subject == "malformed"

    def test_html_body_extracted(self):
        msg = EmailMessage()
        msg["From"] = "a@b.example"
        msg["To"] = "c@d.example"
        msg["Subject"] = "HTML only"
        msg["Message-ID"] = "<html-1@b.example>"
        msg.set_content("<p>Hello <b>world</b></p>", subtype="html")
        mail = parse_raw_email(msg.as_bytes())
        assert "Hello" in mail.body_html
        assert mail.body_text == ""
