"""诊断 IMAP 收信（不改数据）：查看 UID 范围、基线、最近邮件和文件夹。"""

from __future__ import annotations

import sys

import imaplib

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402

ID_PAYLOAD = '("name" "inquiry-agent" "version" "1.0" "vendor" "python")'


def main() -> int:
    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=30)
    imaplib.Commands["ID"] = ("AUTH", "SELECTED", "NONAUTH")
    try:
        conn._simple_command("ID", ID_PAYLOAD)
    except Exception as exc:  # noqa: BLE001
        print("ID failed:", exc)
    conn.login(settings.imap_user, settings.imap_password)
    print("user:", settings.imap_user)

    typ, data = conn.list()
    print("\nfolders:")
    for line in data or []:
        print(" ", line.decode("utf-8", errors="replace"))

    typ, data = conn.select("INBOX", readonly=True)
    print("\nINBOX exists:", data[0].decode() if data and data[0] else "?")
    print("UIDNEXT:", conn.response("UIDNEXT"))
    print("UIDVALIDITY:", conn.response("UIDVALIDITY"))

    typ, data = conn.uid("SEARCH", None, "ALL")
    uids = [int(u) for u in (data[0] or b"").split()]
    print("total uids:", len(uids), "min:", min(uids) if uids else None, "max:", max(uids) if uids else None)

    if uids:
        typ, data = conn.uid("FETCH", str(max(uids)), "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)])")
        if typ == "OK" and data and isinstance(data[0], tuple):
            print("\nlatest message headers:")
            print(data[0][1].decode("utf-8", errors="replace")[:600])

    typ, data = conn.uid("SEARCH", None, "UID 839:*")
    print("\nUID >= 839:", [u.decode() for u in (data[0] or b"").split()])

    conn.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
