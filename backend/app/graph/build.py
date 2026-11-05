"""图构建（PRD 7.7）。

`clarify` 是 `→ END`：追问发出后本次执行结束，客户回信时用同一个 thread_id 重新 invoke。
`approval` 是 `interrupt()`：挂起等人工决策，用 `Command(resume=...)` 恢复。
两者性质不同，不能写混（ADR-16）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.config import DATA_DIR
from app.db.session import SessionLocal
from app.graph.edges import (
    after_approval,
    after_compliance,
    after_compose,
    after_decide,
    after_triage,
)
from app.graph.nodes import (
    make_approval_node,
    make_archive_node,
    make_clarify_node,
    make_compliance_node,
    make_compose_node,
    make_decide_node,
    make_dispatch_node,
    make_draft_plan_node,
    make_persist_node,
    make_recall_node,
    make_resolve_node,
    make_triage_node,
    receive_node,
)
from app.graph.state import AgentState
from app.llm.client import get_chat_llm

CHECKPOINT_FILE = DATA_DIR / "checkpoints.db"

# LangGraph 1.x 默认拒绝反序列化未注册的自定义类型（未来版本会直接报错）。
# 这里显式放行 AgentState 里用到的模型，避免"能跑但迟早崩"的隐患。
ALLOWED_MSGPACK_MODULES: list[tuple[str, str]] = [
    ("app.graph.state", name)
    for name in (
        "MailInput",
        "Triage",
        "MemoryFact",
        "Interaction",
        "MemoryContext",
        "Product",
        "Inventory",
        "PriceTier",
        "Quote",
        "ComplianceHit",
        "Verdict",
        "Decision",
        "Approval",
        "Resolved",
        "InquirySpec",
        "StepError",
        "Step",
    )
] + [
    # ReplyStrategy 定义在策略层（graph.state 只是 re-export），模块路径必须写真实来源
    ("app.strategy.schema", "ReplyStrategy"),
]


def build_serde() -> JsonPlusSerializer:
    """构造带白名单的序列化器（自定义 Pydantic 模型需要显式注册）。"""
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_MSGPACK_MODULES)


_default_conn: sqlite3.Connection | None = None
_default_checkpointer: SqliteSaver | None = None


def get_default_checkpointer(path: str | Path | None = None) -> SqliteSaver:
    """进程内复用同一个 sqlite checkpointer，避免每次建图泄漏连接。

    SqliteSaver.from_conn_string() 是 context manager，必须自己建连接（START 坑 2）；
    这里再把它缓存成单例，供 API 每次请求复用。
    """
    global _default_conn, _default_checkpointer
    if _default_checkpointer is None:
        file = Path(path) if path else CHECKPOINT_FILE
        file.parent.mkdir(parents=True, exist_ok=True)
        _default_conn = sqlite3.connect(str(file), check_same_thread=False)
        _default_checkpointer = SqliteSaver(_default_conn, serde=build_serde())
        _default_checkpointer.setup()
    return _default_checkpointer


def close_default_checkpointer() -> None:
    """应用关闭时释放连接（测试/热重载用）。"""
    global _default_conn, _default_checkpointer
    if _default_conn is not None:
        _default_conn.close()
    _default_conn = None
    _default_checkpointer = None

BUSINESS_NODES = (
    "receive",
    "triage",
    "clarify",
    "resolve",
    "recall",
    "draft_plan",
    "compliance",
    "decide",
    "compose",
    "approval",
    "dispatch",
    "persist",
    "archive",
)


def build_single_agent(
    *,
    checkpointer: Any = None,
    checkpoint_path: str | Path | None = None,
    llm: Any = None,
    session_factory: Any = None,
):
    """构建并编译单 Agent 图。默认用 sqlite checkpointer（跨进程可恢复）。

    `llm` / `session_factory` 可注入，便于测试完全脱库、脱 API。
    """
    llm = llm if llm is not None else get_chat_llm()
    factory = session_factory if session_factory is not None else SessionLocal

    graph = StateGraph(AgentState)

    graph.add_node("receive", receive_node)
    graph.add_node("triage", make_triage_node(llm))
    graph.add_node("clarify", make_clarify_node(llm, factory))
    graph.add_node("resolve", make_resolve_node(factory))
    graph.add_node("recall", make_recall_node(factory))
    graph.add_node("draft_plan", make_draft_plan_node(llm, factory))
    graph.add_node("compliance", make_compliance_node(factory))
    graph.add_node("decide", make_decide_node(llm))
    graph.add_node("compose", make_compose_node(llm))
    graph.add_node("approval", make_approval_node(factory))
    graph.add_node("dispatch", make_dispatch_node(factory))
    graph.add_node("persist", make_persist_node(llm, factory))
    graph.add_node("archive", make_archive_node(factory))

    graph.add_edge(START, "receive")
    graph.add_edge("receive", "triage")
    graph.add_conditional_edges(
        "triage",
        after_triage,
        {"archive": "archive", "clarify": "clarify", "resolve": "resolve"},
    )
    graph.add_edge("clarify", END)
    graph.add_edge("resolve", "recall")
    graph.add_edge("recall", "draft_plan")
    graph.add_edge("draft_plan", "compliance")
    graph.add_conditional_edges(
        "compliance",
        after_compliance,
        {"archive": "archive", "decide": "decide"},
    )
    graph.add_conditional_edges(
        "decide",
        after_decide,
        {"archive": "archive", "compose": "compose", "dispatch": "dispatch"},
    )
    graph.add_conditional_edges(
        "compose",
        after_compose,
        {"dispatch": "dispatch", "approval": "approval"},
    )
    graph.add_conditional_edges(
        "approval",
        after_approval,
        {
            "dispatch": "dispatch",
            "compose": "compose",
            "archive": "archive",
            "approval": "approval",
        },
    )
    graph.add_edge("dispatch", "persist")
    graph.add_edge("archive", "persist")
    graph.add_edge("persist", END)

    if checkpointer is None:
        checkpointer = get_default_checkpointer(checkpoint_path)

    setup = getattr(checkpointer, "setup", None)
    if callable(setup):
        setup()

    return graph.compile(checkpointer=checkpointer)
