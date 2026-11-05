"""查看某客户的召回记忆块（调试用）。

用法：
    python backend/scripts/show_memory.py carlos@acme-import.example
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.models import Customer  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.memory.recall import recall_memory  # noqa: E402


def main() -> int:
    email = sys.argv[1] if len(sys.argv) > 1 else "carlos@acme-import.example"
    with SessionLocal() as session:
        customer = session.scalar(select(Customer).where(Customer.email == email))
        if customer is None:
            print(f"未找到客户：{email}")
            return 1
        memory = recall_memory(session, customer.id)
        print(f"客户：{customer.name} <{customer.email}>  is_new={customer.is_new}")
        print(f"事实 {len(memory.facts)} 条，交互 {len(memory.recent)} 条")
        print("-" * 60)
        print(memory.block or "（无记忆）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
