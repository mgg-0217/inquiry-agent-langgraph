"""记忆抽取：LLM 结构化输出 + 空结果兜底。

失败时返回空 ExtractedMemory（宁可不记，也不写脏数据）。
"""

from __future__ import annotations

import logging

from app.graph.prompts.persist import build_persist_messages
from app.graph.state import MailInput
from app.llm.structured import structured_output
from app.memory.schema import ExtractedMemory

logger = logging.getLogger(__name__)


def extract_memory(llm, mail: MailInput) -> ExtractedMemory:
    try:
        structured = structured_output(llm, ExtractedMemory)
        result = structured.invoke(build_persist_messages(mail))
        if isinstance(result, ExtractedMemory):
            return result
        return ExtractedMemory.model_validate(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("记忆抽取失败，本次不写记忆：%s", exc)
        return ExtractedMemory()
