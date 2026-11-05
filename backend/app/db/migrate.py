"""数据库迁移入口（Alembic）。

应用启动时执行 `upgrade head`，保证 schema 与代码一致；
测试用 `Base.metadata.create_all` 建内存库，不走这里。
"""

from __future__ import annotations

import logging

from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR, settings

logger = logging.getLogger(__name__)


def build_alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option(
        "sqlalchemy.url", f"sqlite:///{settings.database_file.as_posix()}"
    )
    cfg.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    return cfg


def run_migrations() -> None:
    """把数据库升级到最新版本。"""
    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    logger.info("执行数据库迁移：%s", settings.database_file)
    command.upgrade(build_alembic_config(), "head")
