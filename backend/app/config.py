"""应用配置：Pydantic Settings 读取 backend/.env。

约定：
- 所有可调参数集中在这里，业务代码只读 settings，不直接读 os.environ。
- 路径类配置统一解析成绝对路径，避免 cwd 变化导致 sqlite 建到别处。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（config.py 在 backend/app/ 下）
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------- LLM ----------------
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_temperature_judge: float = 0.0
    llm_temperature_compose: float = 0.3

    # ---------------- 数据库 ----------------
    database_url: str = "sqlite:///./data/inquiry.db"

    # ---------------- Agent ----------------
    agent_mode: str = "single"
    max_steps: int = 15
    max_turns: int = 8
    spam_threshold: float = 0.85
    sanction_reject_threshold: float = 0.95
    sanction_review_threshold: float = 0.75

    # ---------------- 邮件：开发期（Mailpit） ----------------
    mail_provider: str = "mailpit"
    dry_run: bool = True
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_from: str = "sales@example.com"
    # Mailpit Web/API 地址与 SMTP 同主机
    mailpit_api_base: str = "http://127.0.0.1:8025"
    imap_host: str = "127.0.0.1"
    imap_port: int = 2114
    imap_poll_interval: int = 10

    # ---------------- 邮件：真实邮箱（第 11 天切） ----------------
    imap_user: str = ""
    imap_password: str = ""
    imap_ssl: bool = True
    smtp_password: str = ""
    smtp_ssl: bool = True
    send_whitelist: str = ""

    # ---------------- 认证 ----------------
    auth_secret_key: str = "dev-only-change-me"
    auth_username: str = "admin"
    auth_password_hash: str = ""

    # ---------------- 业务 ----------------
    quote_valid_days: int = 7
    auto_reply_limit: float = 150000
    default_incoterm: str = "FOB"

    # ---------------- 告警 ----------------
    alert_email: str = ""
    alert_after_failures: int = 3
    alert_cooldown_minutes: int = 30

    @property
    def database_file(self) -> Path:
        """把 DATABASE_URL 里的 sqlite 相对路径解析为 backend/ 下的绝对路径。"""
        url = self.database_url
        prefix = "sqlite:///"
        if not url.startswith(prefix):
            raise ValueError(f"当前仅支持 sqlite，收到 DATABASE_URL={url!r}")
        raw = url[len(prefix):]
        p = Path(raw)
        if not p.is_absolute():
            p = (BACKEND_DIR / raw).resolve()
        return p

    @property
    def send_whitelist_set(self) -> set[str]:
        return {x.strip().lower() for x in self.send_whitelist.split(",") if x.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
