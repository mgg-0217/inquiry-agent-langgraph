"""手动设置 IMAP 拉取基线（调试用）。

用法：
    python backend/scripts/set_imap_baseline.py 427

把基线 UID 设为指定值，时间设为「1 小时前」，并写入当前邮箱的 UIDVALIDITY + 用户，
这样 `establish_baseline` 会认可它，不会自动重建。
"""

from __future__ import annotations

import imaplib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.db.models import AppState  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: set_imap_baseline.py <uid>")
        return 2
    uid = int(sys.argv[1])

    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=30)
    imaplib.Commands["ID"] = ("AUTH", "SELECTED", "NONAUTH")
    try:
        conn._simple_command("ID", '("name" "inquiry-agent")')
    except Exception:  # noqa: BLE001
        pass
    conn.login(settings.imap_user, settings.imap_password)
    conn.select("INBOX", readonly=True)
    uidvalidity = int(conn.response("UIDVALIDITY")[1][0])
    uidnext = int(conn.response("UIDNEXT")[1][0])
    conn.logout()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    values = {
        "imap_baseline_time": (now - timedelta(hours=1)).isoformat(),
        "imap_baseline_uid": str(uid),
        "imap_baseline_uidvalidity": str(uidvalidity),
        "imap_baseline_user": settings.imap_user,
    }
    with SessionLocal() as session:
        for key, value in values.items():
            row = session.get(AppState, key)
            if row is None:
                session.add(AppState(key=key, value=value))
            else:
                row.value = value
        session.commit()

    print(
        f"baseline set: user={settings.imap_user} uid={uid} "
        f"uidvalidity={uidvalidity} uidnext={uidnext} time={(now - timedelta(hours=1)).isoformat()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
