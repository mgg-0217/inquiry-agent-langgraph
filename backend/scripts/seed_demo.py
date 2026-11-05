"""写入演示客户种子数据（PRD F2）。

用法：
    python backend/scripts/seed_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.migrate import run_migrations  # noqa: E402
from app.db.seed import seed_demo_customers  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def main() -> int:
    run_migrations()
    with SessionLocal() as session:
        report = seed_demo_customers(session)
    print(f"✅ 演示客户已写入：新建 {report['created']}，更新 {report['updated']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
