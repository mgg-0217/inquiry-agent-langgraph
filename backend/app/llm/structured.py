"""structured output 兼容层。

DeepSeek 目前不支持 `response_format: json_schema`（返回 400），
必须走 function calling；模型偶发不听话时由调用方重试或兜底。
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def structured_output(llm, schema: type[T], *, method: str = "function_calling"):
    return llm.with_structured_output(schema, method=method)
