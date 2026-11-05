"""制裁名单启动引导：如果数据库为空但有解析好的 entries.json，自动导入。"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.compliance.loader import load_json, save_to_db
from app.config import DATA_DIR
from app.db.models import SanctionEntry
from app.db.session import session_scope

logger = logging.getLogger(__name__)

ENTRIES_JSON = DATA_DIR / "sanctions" / "entries.json"


def ensure_sanctions_loaded() -> int:
    with session_scope() as session:
        count = session.scalar(select(func.count(SanctionEntry.id))) or 0
        if count:
            return count
        if not ENTRIES_JSON.exists():
            logger.info("制裁名单未加载（%s 不存在），合规筛查将转人工", ENTRIES_JSON)
            return 0
        records = load_json(ENTRIES_JSON)
        inserted = save_to_db(session, records)
        logger.info("从 %s 导入制裁名单 %d 条", ENTRIES_JSON, inserted)
        return inserted
