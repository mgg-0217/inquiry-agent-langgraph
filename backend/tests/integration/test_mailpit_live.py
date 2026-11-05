"""集成测试：从 Mailpit 拉取真实邮件 → 解析 → 入库（内存库）。

前置：Mailpit 已启动（scripts/start-mailpit.cmd），且至少有一封邮件
      （`python scripts/send_test_mail.py`）。不满足则跳过。

设计说明：本测试**不再向外发信**，避免污染 Mailpit 和开发库；
SMTP 投递链路由 `scripts/send_test_mail.py` + 工作台手工自检覆盖。
运行：pytest backend/tests/integration/test_mailpit_live.py -v
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.orm import Session

from app.mail.ingest import ingest_parsed
from app.mail.mailpit import MailpitProvider

MAILPIT_API = "http://127.0.0.1:8025"


def _mailpit_up() -> bool:
    try:
        return httpx.get(f"{MAILPIT_API}/api/v1/messages", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _mailpit_up(), reason="Mailpit 未启动")


def test_mailpit_fetch_parse_and_ingest(session: Session):
    provider = MailpitProvider()
    mails = provider.fetch_new(known_message_ids=set())
    if not mails:
        pytest.skip("Mailpit 没有可用邮件，先跑 python scripts/send_test_mail.py")

    mail = mails[0]
    assert mail.message_id.startswith("<")
    assert mail.from_email
    assert mail.subject

    result = ingest_parsed(session, mail)
    session.commit()
    assert result.duplicated is False

    # 幂等：同一封邮件再次入库不新增记录
    again = ingest_parsed(session, mail)
    session.commit()
    assert again.duplicated is True
    assert again.thread_id == result.thread_id
