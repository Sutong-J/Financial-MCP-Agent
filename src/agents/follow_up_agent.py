"""追问 Agent - 基于会话历史与已有分析回答后续问题。"""
from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from harness.core.skill_loader import load_skill, render_skill
from src.rag.query_router import RetrievalScope, classify_retrieval_scope, scope_label
from src.utils.execution_logger import get_execution_logger
from src.utils.logging_config import setup_logger, ERROR_ICON, SUCCESS_ICON, WAIT_ICON
from src.utils.session_context import SessionContext
from src.utils.state_definition import AgentState

load_dotenv(override=True)
logger = setup_logger(__name__)

_REPORT_FIELDS = (
    ("final_report", "综合报告"),
    ("fundamental_analysis", "基本面"),
    ("technical_analysis", "技术面"),
    ("value_analysis", "估值"),
    ("news_analysis", "新闻"),
)


def _format_session_summary(data: dict[str, Any]) -> str:
    company = data.get("company_name", "未知公司")
    stock = data.get("stock_code", "未知代码")
    when = data.get("current_date") or data.get("current_time_info") or "未知"
    return f"- **标的**：{company}（{stock}）\n- **分析时间**：{when}"


def _format_report_fallback(data: dict[str, Any]) -> str:
    sections: list[str] = []
    for field, label in _REPORT_FIELDS:
        raw = data.get(field)
        if raw and str(raw).strip() and str(raw).strip() != "Not available":
            sections.append(f"### {label}\n{raw}")
    if not sections:
        return ""
    return "## 完整分析报告（RAG 不可用时的 fallback）\n\n" + "\n\n".join(sections)


def _resolve_retrieval_scope(user_query: str) -> RetrievalScope:
    return classify_retrieval_scope(user_query)


async def run_follow_up(
    session: SessionContext,
    user_query: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
) -> AgentState:
    """使用已有分析结果与对话历史回答追问。"""
    agent_name = "follow_up_agent"
    execution_logger = get_execution_logger()
    base_state = session.last_state or AgentState(messages=[], data={}, metadata={})
    current_data = dict(base_state.get("data", {}))
    current_metadata = dict(base_state.get("metadata", {}))

    execution_logger.log_agent_start(agent_name, {
        "user_query": user_query,
        "turn": session.turn_count + 1,
        "chat_history_length": len(session.chat_history),
    })

    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
    model_name = os.getenv("OPENAI_COMPATIBLE_MODEL")
    if not all([api_key, base_url, model_name]):
        reply = "错误：未配置 OpenAI 兼容 API 环境变量，无法回答追问。"
        current_data["follow_up_error"] = reply
        execution_logger.log_agent_complete(agent_name, current_data, 0, False, reply)
        return {"data": current_data, "messages": base_state.get("messages", []), "metadata": current_metadata}

    retrieval_scope = _resolve_retrieval_scope(user_query)
    retrieved_context = "（未启用 RAG 检索）"
    if user_id:
        try:
            from src.rag import get_report_rag

            retrieved_context = get_report_rag().retrieve(
                user_id,
                user_query,
                scope=retrieval_scope,
                session_id=session_id,
            )
        except Exception as exc:
            logger.warning("Follow-up RAG retrieve skipped: %s", exc)

    from src.rag.service import is_empty_retrieval

    report_fallback = ""
    if is_empty_retrieval(retrieved_context):
        report_fallback = _format_report_fallback(current_data)

    skill = render_skill(load_skill(agent_name), {
        "company_name": current_data.get("company_name", "未知公司"),
        "stock_code": current_data.get("stock_code", "未知代码"),
        "current_time_info": current_data.get("current_time_info", ""),
        "current_date": current_data.get("current_date", ""),
        "user_query": user_query,
        "chat_history": session.format_chat_history(),
        "session_summary": _format_session_summary(current_data),
        "retrieval_mode": scope_label(retrieval_scope),
        "retrieved_context": retrieved_context,
        "report_fallback": report_fallback,
    })

    llm = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=skill.temperature,
        max_tokens=skill.max_tokens,
    )

    start = time.time()
    logger.info(
        f"{WAIT_ICON} FollowUpAgent: answering follow-up "
        f"(skill v{skill.version}, rag={retrieval_scope.value})..."
    )
    response = await llm.ainvoke([
        {"role": "system", "content": skill.build_system_prompt(0)},
        {"role": "user", "content": skill.user_prompt_template},
    ])
    elapsed = time.time() - start
    reply = (response.content or "").strip()

    current_data["follow_up_reply"] = reply
    current_data["last_reply"] = reply
    current_data["chat_history"] = session.chat_history.copy()
    current_data["chat_history_text"] = session.format_chat_history()
    current_data["rag_retrieval_scope"] = retrieval_scope.value

    execution_logger.log_llm_interaction(
        agent_name=agent_name,
        interaction_type="follow_up",
        input_messages=[
            {"role": "system", "content": skill.build_system_prompt(0)},
            {"role": "user", "content": skill.user_prompt_template},
        ],
        output_content=reply,
        model_config={
            "model": model_name,
            "temperature": skill.temperature,
            "max_tokens": skill.max_tokens,
            "skill_version": skill.version,
            "rag_retrieval_scope": retrieval_scope.value,
        },
        execution_time=elapsed,
    )
    execution_logger.log_agent_complete(agent_name, {
        "reply_length": len(reply),
        "reply_preview": reply[:500],
        "rag_retrieval_scope": retrieval_scope.value,
    }, elapsed, True)
    logger.info(f"{SUCCESS_ICON} FollowUpAgent: follow-up answered in {elapsed:.2f}s")

    return {
        "data": current_data,
        "messages": list(base_state.get("messages", [])),
        "metadata": current_metadata,
    }
