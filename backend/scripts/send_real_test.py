"""真实邮件联调：用客户邮箱 SMTP 给 Agent 邮箱发测试邮件。

用法（PowerShell）：
    python backend/scripts/send_real_test.py --mode chinese
    python backend/scripts/send_real_test.py --mode attachment
    python backend/scripts/send_real_test.py --mode followup --in-reply-to "<原邮件Message-ID>"

客户邮箱凭证从环境变量读：
    TEST_CUSTOMER_USER / TEST_CUSTOMER_PASSWORD
默认收件人是 .env 里的 IMAP_USER（Agent 邮箱）。
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402


def build_message(mode: str, to: str, sender: str, in_reply_to: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])

    if mode == "chinese":
        msg["Subject"] = "询价：X200 离心泵 100 台，CIF 汉堡"
        msg.set_content(
            "您好，\n\n"
            "我们是汉堡的 Nordwind Handels GmbH。\n"
            "请报价 X200 离心泵 100 台，380V/50Hz，CIF 汉堡。\n"
            "请确认交期与报价有效期。\n\n"
            "谢谢！\nThomas Müller\n"
        )
    elif mode == "attachment":
        msg["Subject"] = "Inquiry: Y300 valve, 200 units, CIF Jakarta (spec attached)"
        msg.set_content(
            "Dear Sales Team,\n\n"
            "Please quote 200 units of Y300 valve, DN150, CIF Jakarta.\n"
            "Technical specification attached.\n\n"
            "Best regards,\nBudi Santoso\nPT Nusantara Teknik\n"
        )
        msg.add_attachment(
            b"%PDF-1.4\n% fake spec sheet for integration test\n",
            maintype="application",
            subtype="pdf",
            filename="Y300-spec.pdf",
        )
    else:  # followup
        msg["Subject"] = "Re: Inquiry: X200 centrifugal pump, 100 units, CIF Hamburg"
        msg.set_content("Hi, thanks. Could you confirm the lead time for 100 units?\n")
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

    return msg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["chinese", "attachment", "followup"], required=True)
    parser.add_argument("--to", default=settings.imap_user)
    parser.add_argument("--in-reply-to", default=None)
    args = parser.parse_args()

    user = os.environ.get("TEST_CUSTOMER_USER")
    password = os.environ.get("TEST_CUSTOMER_PASSWORD")
    if not user or not password:
        print("需要环境变量 TEST_CUSTOMER_USER / TEST_CUSTOMER_PASSWORD")
        return 2

    msg = build_message(args.mode, args.to, user, args.in_reply_to)
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30, local_hostname="localhost") as server:
        server.login(user, password)
        server.send_message(msg)

    print(f"sent mode={args.mode} to={args.to} message_id={msg['Message-ID']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
