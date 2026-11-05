"""诊断 UID SEARCH 语法（临时）。"""

import imaplib
import sqlite3
import sys

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402


def main() -> int:
    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=30)
    imaplib.Commands["ID"] = ("AUTH", "SELECTED", "NONAUTH")
    conn._simple_command("ID", '("name" "inquiry-agent")')
    conn.login(settings.imap_user, settings.imap_password)
    conn.select("INBOX", readonly=True)

    base = int(
        sqlite3.connect("data/inquiry.db")
        .execute("select value from app_state where key = 'imap_baseline_uid'")
        .fetchone()[0]
    )
    print("baseline uid:", base)

    queries = [f"UID {base}:*", f"UID {base}:* ALL", f"UID {base}:1000", "ALL"]
    for q in queries:
        typ, data = conn.uid("SEARCH", None, q)
        uids = (data[0] or b"").split()
        print(f"{q!r} -> {typ} count={len(uids)} tail={[u.decode() for u in uids[-6:]]}")

    conn.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
