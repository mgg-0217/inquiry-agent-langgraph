"""检查 Agent 邮箱「已发送」文件夹最近邮件，确认 SMTP 真的发出去了。"""

from __future__ import annotations

import imaplib
import sys

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402


def main() -> int:
    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=30)
    imaplib.Commands["ID"] = ("AUTH", "SELECTED", "NONAUTH")
    try:
        conn._simple_command("ID", '("name" "inquiry-agent")')
    except Exception:  # noqa: BLE001
        pass
    conn.login(settings.imap_user, settings.imap_password)

    for folder in ('"Sent Messages"', '"&UXZO1mWHTvZZOQ-"', "INBOX"):
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            print(f"{folder}: cannot select")
            continue
        typ, data = conn.uid("SEARCH", None, "ALL")
        uids = (data[0] or b"").split()
        print(f"{folder}: {len(uids)} messages")
        if uids:
            last = uids[-1]
            typ, msg = conn.uid(
                "FETCH", last, "(BODY.PEEK[HEADER.FIELDS (SUBJECT TO DATE MESSAGE-ID)])"
            )
            if typ == "OK" and msg and isinstance(msg[0], tuple):
                print("  latest:", msg[0][1].decode("utf-8", errors="replace")[:300])
    conn.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
