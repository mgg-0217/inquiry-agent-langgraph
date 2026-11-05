"""AgentState 与各节点产物模型（PRD 7.1）。

约定（PRD 7.1 三条铁律）：
1. 每个字段只有一个节点能写，其他节点只读；
2. 节点不得修改他人产物，有异议写 `errors`；
3. `trace` 只追加不修改（用 `operator.add` reducer）。
"""

from __future__ import annotations

import operator
from datetime import date, datetime, timezone
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

from app.mail.base import ParsedMail
from app.strategy.schema import ReplyStrategy


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- 输入


class MailInput(BaseModel):
    """进入图的一封邮件。第 1 天入库用 dataclass，这里转成可 JSON 序列化的模型。

    `is_price_negotiation` / `client_offered_price` 由 `triage` 节点判定后写入
    （PRD 7.3.1），其余字段由 `receive` 节点写入。
    """

    message_id: str
    subject: str = ""
    from_email: str = ""
    from_name: str = ""
    to_emails: list[str] = Field(default_factory=list)
    cc_emails: list[str] = Field(default_factory=list)
    body_text: str = ""
    body_html: str = ""
    attachments: list[dict] = Field(default_factory=list)
    received_at: datetime = Field(default_factory=utcnow)
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    is_price_negotiation: bool = False
    client_offered_price: float | None = None

    @classmethod
    def from_parsed(cls, parsed: ParsedMail) -> "MailInput":
        return cls(
            message_id=parsed.message_id,
            subject=parsed.subject,
            from_email=parsed.from_email,
            from_name=parsed.from_name,
            to_emails=list(parsed.to_emails),
            cc_emails=list(parsed.cc_emails),
            body_text=parsed.body_text,
            body_html=parsed.body_html,
            attachments=list(parsed.attachments),
            received_at=_to_naive_utc(parsed.received_at or utcnow()),
            in_reply_to=parsed.in_reply_to,
            references=list(parsed.references),
        )


# ---------------------------------------------------------------- 分诊


class Triage(BaseModel):
    """`triage` 节点产物：一次调用给出垃圾判定 + 完整性判定（PRD F4）。"""

    is_spam: bool = False
    spam_reason: str = ""
    confidence: float = 0.0
    complete: bool = True
    missing: list[str] = Field(default_factory=list)
    clarify_questions: list[str] = Field(default_factory=list)
    is_negotiation: bool = False
    client_offered_price: float | None = None
    # 低置信度 / LLM 失败时置 true：不自动归档，但后续必须人工复核
    need_review: bool = False


class Resolved(BaseModel):
    """`resolve` 节点产物：四级实体解析结果（PRD F2）。"""

    customer_id: str
    method: Literal["email_exact", "domain", "company_fuzzy", "new"] = "new"
    confidence: float = 1.0
    need_confirm: bool = False


# ---------------------------------------------------------------- 记忆


class MemoryFact(BaseModel):
    key: str
    value: str
    confidence: float = 1.0
    evidence: str = ""
    source_msg: str | None = None
    valid_until: date | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Interaction(BaseModel):
    summary: str = ""
    outcome: str = ""
    lost_reason: str | None = None
    evidence: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class MemoryContext(BaseModel):
    """`recall` 节点产物：已召回的事实 + 最近交互 + 未闭环 thread + 拼好的记忆块。"""

    facts: list[MemoryFact] = Field(default_factory=list)
    recent: list[Interaction] = Field(default_factory=list)
    pending: list[dict] = Field(default_factory=list)
    block: str = ""


# ---------------------------------------------------------------- 产品与报价


class Product(BaseModel):
    sku: str
    name: str = ""
    specs: dict = Field(default_factory=dict)
    moq: int = 1


class Inventory(BaseModel):
    available: bool = True
    lead_time: str = ""
    can_expedite: bool = False


class PriceTier(BaseModel):
    min_qty: int
    max_qty: int | None = None
    unit_price: float


class Quote(BaseModel):
    """`draft_plan` 产物。数字只来自 `calc_price` 工具（PRD F5）。"""

    sku: str
    qty: int
    tiers: list[PriceTier] = Field(default_factory=list)
    unit_price: float = 0.0
    floor_price: float = 0.0
    target_matched_price: float | None = None
    total: float = 0.0
    currency: str = "USD"
    freight: float = 0.0
    insurance: float = 0.0
    incoterm: str = "FOB"
    destination: str = ""
    valid_until: date | None = None
    breakdown: dict = Field(default_factory=dict)


class InquirySpec(BaseModel):
    """从询盘邮件抽出的结构化采购需求（draft_plan 的输入）。"""

    sku: str | None = Field(default=None, description="产品型号，如 X200")
    product_keyword: str | None = Field(default=None, description="产品关键词，如 centrifugal pump")
    quantity: int | None = Field(default=None, description="数量")
    incoterm: str | None = Field(default=None, description="FOB / CFR / CIF")
    destination: str | None = Field(default=None, description="目的港/目的地")


# ---------------------------------------------------------------- 策略（PRD 7.8.2）

# ReplyStrategy 定义在 app/strategy/schema.py（策略层可脱库测试），
# 这里 re-export，节点与图直接 `from app.graph.state import ReplyStrategy`。


# ---------------------------------------------------------------- 合规


class ComplianceHit(BaseModel):
    list_name: str = ""
    entry_no: str = ""
    name: str = ""
    score: float = 0.0
    evidence: str = ""


class Verdict(BaseModel):
    """`compliance` 产物（PRD F6）。"""

    result: Literal["pass", "need_review", "reject"] = "pass"
    score: float = 0.0
    hits: list[ComplianceHit] = Field(default_factory=list)
    rules_hit: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 决策与审批


class Decision(BaseModel):
    action: Literal["auto_reply", "escalate", "reject"] = "auto_reply"
    reason: str = ""
    confidence: float = 1.0


class Approval(BaseModel):
    action: Literal["approve", "modify", "reject", "reassign"] = "approve"
    comment: str = ""
    edited_reply: str | None = None
    approver: str = ""
    decided_at: datetime | None = None


# ---------------------------------------------------------------- 轨迹


class StepError(BaseModel):
    node: str
    code: str
    message: str
    retryable: bool = False
    at: datetime = Field(default_factory=utcnow)


class Step(BaseModel):
    node: str
    status: Literal["ok", "error", "waiting", "resumed"] = "ok"
    summary: str = ""
    started_at: datetime = Field(default_factory=utcnow)
    duration_ms: int = 0
    tool_calls: list[dict] = Field(default_factory=list)
    tokens: dict | None = None


# ---------------------------------------------------------------- 状态


class AgentState(TypedDict, total=False):
    # 输入
    mail: MailInput
    thread_id: str
    customer_id: str | None

    # 分诊
    triage: Triage | None
    clarify_count: int
    resolved: Resolved | None

    # 记忆
    memory: MemoryContext | None

    # 方案
    products: list[Product] | None
    inventory: Inventory | None
    quote: Quote | None
    strategy: ReplyStrategy | None

    # 合规
    verdict: Verdict | None

    # 决策
    decision: Decision | None
    approval: Approval | None

    # 输出
    reply_draft: str | None
    reply_final: str | None
    sent: bool
    fact_check_ok: bool | None

    # 控制
    step: int
    errors: Annotated[list[StepError], operator.add]
    trace: Annotated[list[Step], operator.add]

    # 会话轮次（记忆答不了这部分，必须由状态提供）
    round: int
    is_followup: bool
    our_previous_quote: Quote | None
    client_previous_price: float | None

    # 其他
    manual_restore: bool  # 误判捞回：跳过 spam 判定（PRD F4）
    next: str | None  # 挂起时指向下一步（审批台用）
