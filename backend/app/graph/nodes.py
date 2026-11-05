"""12 个业务节点 + archive 归档节点。

实现进度：receive / triage / clarify / resolve / recall / persist / compliance 已接真实逻辑；
draft_plan / decide / compose / approval / dispatch 仍是骨架，按 START 排期替换。
"""

from __future__ import annotations

from typing import Callable

from langgraph.types import interrupt
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AuditLog, Customer, Message, Thread
from app.graph.clarify import compose_clarify
from app.graph.compose import compose_reply, facts_from_state
from app.graph.decide import decide
from app.graph.fact_check import check_reply
from app.graph.draft_plan import (
    build_quote,
    build_strategy,
    extract_inquiry_spec,
    run_react,
    target_price_from_memory,
)
from app.graph.resolve import resolve_customer
from app.graph.triage import triage_mail
from app.graph.state import (
    AgentState,
    Approval,
    ComplianceHit,
    Decision,
    Step,
    Triage,
    Verdict,
    utcnow,
)
from app.memory.extractor import extract_memory
from app.memory.recall import recall_memory
from app.memory.store import write_memory
from app.tools.comms import send_message
from app.tools.compliance import screen_compliance

SessionFactory = Callable[[], Session]


def _record(state: AgentState, node: str, summary: str = "", **extra) -> dict:
    """统一追加轨迹并递增全局步数（trace 用 operator.add 追加）。"""
    tool_calls = extra.pop("tool_calls", None) or []
    return {
        "step": state.get("step", 0) + 1,
        "trace": [
            Step(
                node=node,
                status="ok",
                summary=summary,
                started_at=utcnow(),
                tool_calls=list(tool_calls),
            )
        ],
        **extra,
    }


# ---------------------------------------------------------------- 1. receive


def receive_node(state: AgentState) -> dict:
    """解析、幂等、thread 归并、轮次自增（第 4 天接真实入库）。"""
    mail = state.get("mail")
    is_followup = bool(state.get("is_followup")) or bool(
        mail and (mail.in_reply_to or mail.references)
    )
    round_no = 1
    if is_followup:
        round_no = max(1, state.get("round", 1)) + 1
    thread_id = state.get("thread_id") or (
        f"thread:{mail.message_id}" if mail else "thread:unknown"
    )
    return _record(
        state,
        "receive",
        f"收到邮件 round={round_no} followup={is_followup}",
        thread_id=thread_id,
        round=round_no,
        is_followup=is_followup,
    )


# ---------------------------------------------------------------- 2. triage


def make_triage_node(llm):
    """垃圾判定 + 完整性判定 + is_negotiation（PRD F4）。"""

    def triage_node(state: AgentState) -> dict:
        mail = state["mail"]
        if state.get("manual_restore"):
            triage = Triage(is_spam=False, complete=True, confidence=1.0)
        else:
            triage = triage_mail(llm, mail)

        # 7.3.1：is_negotiation 由 triage 判定后写入 mail，供 after_decide 使用
        updated_mail = mail.model_copy(
            update={
                "is_price_negotiation": triage.is_negotiation,
                "client_offered_price": triage.client_offered_price,
            }
        )
        if triage.is_spam:
            summary = f"垃圾邮件（{triage.spam_reason}）"
        elif not triage.complete:
            summary = f"信息不完整：{'、'.join(triage.missing) or '未知'}"
        else:
            summary = "信息完整"
        if triage.is_negotiation:
            summary += f" / 还价 {triage.client_offered_price or ''}".rstrip()

        return _record(
            state,
            "triage",
            summary,
            triage=triage,
            mail=updated_mail,
            clarify_count=state.get("clarify_count", 0),
        )

    return triage_node


# ---------------------------------------------------------------- 3. clarify


def make_clarify_node(llm, session_factory: SessionFactory):
    """生成追问并**真正发出**，然后本轮 END，等客户回信重新 invoke。"""

    def clarify_node(state: AgentState) -> dict:
        mail = state["mail"]
        text = compose_clarify(llm, mail, state["triage"])
        subject = mail.subject if mail.subject.lower().startswith("re:") else f"Re: {mail.subject}"
        result = send_message(
            mail.from_email,
            subject,
            text,
            in_reply_to=mail.message_id,
            references=[*mail.references, mail.message_id],
        )
        data = result.get("data") or {}
        dry_run = bool(data.get("dry_run"))
        sent = bool(result.get("ok")) and not dry_run

        thread_id = state.get("thread_id")
        with session_factory() as session:
            if thread_id:
                thread = session.get(Thread, thread_id)
                if thread is not None:
                    thread.status = "waiting_clarify"
            if result.get("ok") and data.get("message_id"):
                session.add(
                    Message(
                        thread_id=thread_id or "",
                        message_id=str(data["message_id"]),
                        direction="outbound",
                        subject=subject,
                        from_email=settings.smtp_from or "",
                        from_name="Sales Team",
                        to_emails=[mail.from_email],
                        body_text=text,
                        received_at=utcnow(),
                    )
                )
            session.add(
                AuditLog(
                    thread_id=thread_id,
                    actor="agent",
                    action="clarify_send",
                    payload={
                        "to": mail.from_email,
                        "message_id": data.get("message_id"),
                        "dry_run": dry_run,
                        "ok": result.get("ok"),
                        "code": result.get("code"),
                    },
                )
            )
            session.commit()

        label = "已发送" if sent else ("DRY_RUN 未真发" if dry_run else "未发送")
        return _record(
            state,
            "clarify",
            f"生成追问并{label}（{result.get('code')}）",
            reply_draft=text,
            clarify_count=state.get("clarify_count", 0) + 1,
        )

    return clarify_node


# ---------------------------------------------------------------- 4. resolve


def make_resolve_node(session_factory: SessionFactory):
    """四级实体解析（第 4 天：L1 邮箱精确 + L4 新建）。"""

    def resolve_node(state: AgentState) -> dict:
        with session_factory() as session:
            resolved = resolve_customer(session, state["mail"])
            thread_id = state.get("thread_id")
            if thread_id:
                thread = session.get(Thread, thread_id)
                if thread is not None and not thread.customer_id:
                    thread.customer_id = resolved.customer_id
            session.commit()
        return _record(
            state,
            "resolve",
            f"命中方式 {resolved.method}",
            customer_id=resolved.customer_id,
            resolved=resolved,
        )

    return resolve_node


# ---------------------------------------------------------------- 5. recall


def make_recall_node(session_factory: SessionFactory):
    """记忆召回 + 拼记忆块（PRD F3）。"""

    def recall_node(state: AgentState) -> dict:
        with session_factory() as session:
            memory = recall_memory(session, state.get("customer_id"))
        return _record(
            state,
            "recall",
            f"事实 {len(memory.facts)} 条 / 交互 {len(memory.recent)} 条",
            memory=memory,
        )

    return recall_node


# ---------------------------------------------------------------- 6. draft_plan


def make_draft_plan_node(llm, session_factory: SessionFactory):
    """ReAct：匹配产品 → 查库存 → 算价 → 定策略（PRD 7.2 / F5 / 7.8）。"""

    def draft_plan_node(state: AgentState) -> dict:
        mail = state["mail"]
        memory = state.get("memory")
        customer: dict = {}
        with session_factory() as session:
            customer_id = state.get("customer_id")
            if customer_id:
                row = session.get(Customer, customer_id)
                if row is not None:
                    customer = {
                        "is_new": row.is_new,
                        "name": row.name,
                        "country": row.country,
                    }

        spec = extract_inquiry_spec(llm, mail)
        if spec is None:
            return _record(
                state,
                "draft_plan",
                "采购需求抽取失败",
                products=[],
                inventory=None,
                quote=None,
                strategy=None,
            )

        target = target_price_from_memory(memory)
        react_calls = run_react(llm, mail)
        fallback_calc: dict | None = None
        for call in reversed(react_calls):
            result = call.get("result")
            if (
                call.get("tool") == "calc_price"
                and isinstance(result, dict)
                and result.get("ok")
            ):
                fallback_calc = result.get("data")
                break

        quote, products, inventory, summary = build_quote(
            spec, target, fallback_calc=fallback_calc
        )
        if quote is None:
            return _record(
                state,
                "draft_plan",
                summary,
                products=products,
                inventory=inventory,
                quote=None,
                strategy=None,
            )

        strategy = build_strategy(
            llm, mail, memory, quote, customer, state.get("round", 1)
        )
        return _record(
            state,
            "draft_plan",
            f"{summary}：{quote.sku} × {quote.qty} {quote.incoterm} ${quote.unit_price}",
            products=products,
            inventory=inventory,
            quote=quote,
            strategy=strategy,
            tool_calls=react_calls,
        )

    return draft_plan_node


# ---------------------------------------------------------------- 7. compliance


def make_compliance_node(session_factory: SessionFactory):
    """OFAC 制裁名单筛查（PRD F6 L1）。

    阈值判定由代码硬规则决定：≥ reject 阈值 → reject，≥ review 阈值 → need_review。
    名单未加载时**不宣称放行**，转人工复核（宁可误杀）。
    本版不含内部资信评分与出口管制（需真实公司数据，已明确裁剪）。
    """

    def compliance_node(state: AgentState) -> dict:
        customer_id = state.get("customer_id")
        name = ""
        country = ""
        with session_factory() as session:
            if customer_id:
                customer = session.get(Customer, customer_id)
                if customer is not None:
                    name = customer.name or ""
                    country = customer.country or ""
            result = screen_compliance(name, country, session=session)

        data = result.get("data") or {}
        hits = [
            ComplianceHit(
                list_name=hit.get("list_name", ""),
                entry_no=hit.get("entry_no", ""),
                name=hit.get("name", ""),
                score=float(hit.get("score", 0.0)),
                evidence=hit.get("evidence", ""),
            )
            for hit in data.get("hits", [])
        ]
        score = float(data.get("score", 0.0))

        if not data.get("list_loaded"):
            verdict = Verdict(
                result="need_review",
                score=0.0,
                hits=[],
                rules_hit=["SANCTIONS_NOT_LOADED"],
                reasons=["制裁名单未加载，按宁可误杀原则转人工复核"],
                evidence=[],
            )
            summary = "名单未加载 → 转人工"
        elif score >= settings.sanction_reject_threshold:
            verdict = Verdict(
                result="reject",
                score=score,
                hits=hits,
                rules_hit=["SANCTION_HIT"],
                reasons=[f"命中制裁名单（{score:.2f}）"],
                evidence=list(data.get("evidence", [])),
            )
            summary = f"制裁命中（{score:.2f}）→ 拦截"
        elif score >= settings.sanction_review_threshold:
            verdict = Verdict(
                result="need_review",
                score=score,
                hits=hits,
                rules_hit=["SANCTION_SUSPECTED"],
                reasons=[f"疑似命中（{score:.2f}），需人工复核"],
                evidence=list(data.get("evidence", [])),
            )
            summary = f"疑似命中（{score:.2f}）→ 人工"
        else:
            verdict = Verdict(
                result="pass",
                score=score,
                hits=hits,
                rules_hit=[],
                reasons=["未命中制裁名单"],
                evidence=list(data.get("evidence", [])),
            )
            summary = f"未命中（{score:.2f}）→ 放行"

        return _record(state, "compliance", summary, verdict=verdict)

    return compliance_node


# ---------------------------------------------------------------- 8. decide


def make_decide_node(llm):
    """路由：模型建议 + 代码硬规则否决（PRD F8 / ADR-10）。"""

    def decide_node(state: AgentState) -> dict:
        decision = decide(llm, state)
        return _record(
            state,
            "decide",
            f"{decision.action}：{decision.reason}",
            decision=decision,
        )

    return decide_node


# ---------------------------------------------------------------- 9. compose


def make_compose_node(llm):
    """生成回复 + fact_check + 失败重写（PRD F7）。"""

    def compose_node(state: AgentState) -> dict:
        reply, result = compose_reply(llm, state)
        summary = "生成回复"
        if not result.ok:
            summary += f"（事实校验失败：{result.feedback}）"
        return _record(
            state,
            "compose",
            summary,
            reply_draft=reply,
            reply_final=reply,
            fact_check_ok=result.ok,
        )

    return compose_node


# ---------------------------------------------------------------- 10. approval


VALID_APPROVAL_ACTIONS = {"approve", "modify", "reject", "reassign"}


def make_approval_node(session_factory: SessionFactory):
    """interrupt 挂起等人工审批（PRD F8）。

    LangGraph 的 interrupt 在恢复时会**重新执行整个节点**，
    所以 interrupt 之前只做幂等操作（改 thread 状态），审计与改稿放在 interrupt 之后。
    """

    def _mark_waiting(thread_id: str | None) -> None:
        if not thread_id:
            return
        with session_factory() as session:
            thread = session.get(Thread, thread_id)
            if thread is not None:
                thread.status = "waiting_approval"
                session.commit()

    def approval_node(state: AgentState) -> dict:
        _mark_waiting(state.get("thread_id"))

        payload = interrupt(
            {
                "type": "approval_request",
                "thread_id": state.get("thread_id"),
                "reply_draft": state.get("reply_draft"),
                "quote": state["quote"].model_dump() if state.get("quote") else None,
                "verdict": state["verdict"].model_dump() if state.get("verdict") else None,
                "strategy": (
                    state["strategy"].model_dump() if state.get("strategy") else None
                ),
                "fact_check_ok": state.get("fact_check_ok"),
            }
        )

        data = payload if isinstance(payload, dict) else {}
        action = data.get("action")
        comment = str(data.get("comment") or "")
        approver = str(data.get("approver") or "")

        # 安全默认：非法或缺失的动作一律按驳回，绝不默认发送
        if action not in VALID_APPROVAL_ACTIONS:
            action = "reject"
            comment = comment or "非法或缺失的审批动作，按驳回处理"

        # 人工编辑后必须再跑一次 fact_check（PRD F8：不允许跳过）
        edited = (data.get("edited_reply") or "").strip() or None
        reply_final = state.get("reply_final")
        fact_ok = True
        if edited:
            checked = check_reply(edited, facts_from_state(state))
            fact_ok = checked.ok
            if checked.ok:
                reply_final = edited
            else:
                # 不发送、不归档：退回重写，业务员可以再改再批
                action = "modify"
                comment = f"编辑后事实校验失败：{checked.feedback}（已退回重写）"
                reply_final = None

        with session_factory() as session:
            session.add(
                AuditLog(
                    thread_id=state.get("thread_id"),
                    actor=approver or "human",
                    action="approval",
                    payload={
                        "action": action,
                        "comment": comment,
                        "edited": bool(edited),
                        "fact_check_ok": fact_ok,
                    },
                )
            )
            session.commit()

        next_node = {
            "approve": "dispatch",
            "modify": "compose",
            "reassign": "approval",
        }.get(action, "archive")
        return _record(
            state,
            "approval",
            f"人工动作 {action}" + ("" if fact_ok else "（编辑后校验失败）"),
            approval=Approval(
                action=action,
                comment=comment,
                edited_reply=edited,
                approver=approver,
                decided_at=utcnow(),
            ),
            reply_final=reply_final,
            next=next_node,
        )

    return approval_node


# ---------------------------------------------------------------- 11. dispatch


def make_dispatch_node(session_factory: SessionFactory):
    """发送邮件（写工具只在审批后由代码调用，PRD 7.4）。"""

    def dispatch_node(state: AgentState) -> dict:
        mail = state["mail"]
        reply = state.get("reply_final") or state.get("reply_draft") or ""
        subject = (
            mail.subject
            if mail.subject.lower().startswith("re:")
            else f"Re: {mail.subject}"
        )
        result = send_message(
            mail.from_email,
            subject,
            reply,
            in_reply_to=mail.message_id,
            references=[*mail.references, mail.message_id],
        )
        data = result.get("data") or {}
        dry_run = bool(data.get("dry_run"))
        sent = bool(result.get("ok")) and not dry_run

        thread_id = state.get("thread_id")
        now = utcnow()
        with session_factory() as session:
            if thread_id:
                thread = session.get(Thread, thread_id)
                if thread is not None:
                    # DRY_RUN 也算处理完成（开发期否则会永远显示"处理中"）
                    thread.status = "replied" if result.get("ok") else "processing"
            # 外发邮件也入库，否则线程详情看不到我方回复、也没法算首响
            if result.get("ok") and data.get("message_id"):
                session.add(
                    Message(
                        thread_id=thread_id or "",
                        message_id=str(data["message_id"]),
                        direction="outbound",
                        subject=subject,
                        from_email=settings.smtp_from or "",
                        from_name="Sales Team",
                        to_emails=[mail.from_email],
                        body_text=reply,
                        received_at=now,
                        in_reply_to=mail.message_id,
                        references=[*mail.references, mail.message_id],
                    )
                )
            session.add(
                AuditLog(
                    thread_id=thread_id,
                    actor="agent",
                    action="dispatch",
                    payload={
                        "to": mail.from_email,
                        "message_id": data.get("message_id"),
                        "dry_run": dry_run,
                        "ok": result.get("ok"),
                        "code": result.get("code"),
                    },
                )
            )
            session.commit()

        label = "已发送" if sent else "DRY_RUN 未真发"
        return _record(
            state,
            "dispatch",
            f"{label}（{result.get('code')}）",
            sent=sent,
            reply_final=reply,
        )

    return dispatch_node


# ---------------------------------------------------------------- 12. persist


def make_persist_node(llm, session_factory: SessionFactory):
    """记忆抽取写入 + 交互记录（PRD F3.3）。

    证据校验与冲突处理在 `memory/store.py`，这里只负责编排。
    """

    def persist_node(state: AgentState) -> dict:
        customer_id = state.get("customer_id")
        mail = state.get("mail")
        if not customer_id or mail is None:
            return _record(state, "persist", "跳过：没有客户或邮件")

        extract = extract_memory(llm, mail)
        with session_factory() as session:
            report = write_memory(
                session, customer_id, mail, extract, state.get("thread_id")
            )
            session.commit()

        return _record(
            state,
            "persist",
            f"写入 {len(report.written)} 条事实，丢弃 {len(report.dropped)} 条",
        )

    return persist_node


# ---------------------------------------------------------------- archive


def make_archive_node(session_factory: SessionFactory):
    """归档：写入终态与归档原因（PRD 8 状态枚举）。"""

    def archive_node(state: AgentState) -> dict:
        verdict = state.get("verdict")
        decision = state.get("decision")
        approval = state.get("approval")

        if verdict is not None and verdict.result == "reject":
            status, reason = "archived_compliance", "compliance"
        elif approval is not None and approval.action == "reject":
            status, reason = "archived_rejected", "approval_rejected"
        elif decision is not None and decision.action == "reject":
            status, reason = "archived_rejected", "decision_rejected"
        else:
            status, reason = "archived_spam", "spam"

        thread_id = state.get("thread_id")
        if thread_id:
            with session_factory() as session:
                thread = session.get(Thread, thread_id)
                if thread is not None:
                    thread.status = status
                    session.commit()

        return _record(state, "archive", f"已归档（{reason}）")

    return archive_node
