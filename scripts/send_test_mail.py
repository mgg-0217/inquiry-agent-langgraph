"""向 Mailpit 投递一封测试询盘邮件（第 1 天自检用）。

用法：
    python scripts/send_test_mail.py                 # 场景 A：老客户询盘
    python scripts/send_test_mail.py --subject "..." --body "..."

邮件会进入 Mailpit 的 SMTP（127.0.0.1:1025），随后由后端轮询任务自动入库。
"""

from __future__ import annotations

import argparse
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

SMTP_HOST = "127.0.0.1"
SMTP_PORT = 1025
SMTP_FROM = "sales@example.com"

SCENARIO_A = {
    "from_name": "Carlos Mendoza",
    "from_email": "carlos@acme-import.example",
    "to": "sales@example.com",
    "subject": "Inquiry: X200 centrifugal pump, 500 units, CIF Valencia",
    "body": """Dear Sales Team,

We are Inversiones Valencianas S.L., an industrial equipment distributor based in Valencia, Spain.

We are interested in your X200 centrifugal pump and would like to receive a quotation for the following:

- Model: X200 centrifugal pump
- Quantity: 500 units
- Voltage: 380V / 50Hz
- Incoterm: CIF Valencia
- Packaging: export carton

Please also confirm the lead time and the quotation validity.

Best regards,
Carlos Mendoza
Purchasing Manager
Inversiones Valencianas S.L.
""",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="向 Mailpit 投递测试询盘")
    parser.add_argument("--subject", default=SCENARIO_A["subject"])
    parser.add_argument("--body", default=SCENARIO_A["body"])
    args = parser.parse_args()

    msg = EmailMessage()
    msg["From"] = f'{SCENARIO_A["from_name"]} <{SCENARIO_A["from_email"]}>'
    msg["To"] = SCENARIO_A["to"]
    msg["Subject"] = args.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="acme-import.example")
    msg.set_content(args.body)

    # 本机主机名含中文，必须指定 local_hostname
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10, local_hostname="localhost") as server:
        server.send_message(msg)

    print("✅ 测试邮件已投递到 Mailpit")
    print(f"   Message-ID : {msg['Message-ID']}")
    print(f"   From       : {SCENARIO_A['from_email']}")
    print(f"   Subject    : {args.subject}")
    print(f"   Web UI     : http://localhost:8025")
    return 0


if __name__ == "__main__":
    sys.exit(main())
