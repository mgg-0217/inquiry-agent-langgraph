"""诊断 UID FETCH 返回结构（临时）。"""

import imaplib
import sys

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402


def main() -> int:
    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=30)
    imaplib.Commands["ID"] = ("AUTH", "SELECTED", "NONAUTH")
    conn._simple_command("ID", '("name" "inquiry-agent")')
    conn.login(settings.imap_user, settings.imap_password)
    conn.select("INBOX", readonly=True)

    for uid in (b"438", b"427"):
        typ, data = conn.uid("FETCH", uid, "(RFC822)")
        print(f"uid={uid!r} typ={typ} len={len(data) if data else 0}")
        if data:
            for i, item in enumerate(data):
                print(f"  [{i}] type={type(item).__name__} head={str(item)[:120]!r}")

    conn.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
