"""单轮 / 多轮分析执行逻辑。"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.agents.follow_up_agent import run_follow_up
from src.utils.execution_logger import get_execution_logger
from src.utils.logging_config import ERROR_ICON, SUCCESS_ICON, WAIT_ICON, setup_logger
from src.utils.session_context import SessionContext
from src.utils.state_definition import AgentState
from src.utils.stock_extractor import extract_stock_info, normalize_stock_code

logger = setup_logger(__name__)

EXIT_COMMANDS = {"exit", "quit", "q", "退出", "再见"}

ProgressCallback = Callable[[str, str], None]

ANALYSIS_OUTPUT_KEYS: dict[str, tuple[str, str]] = {
    "fundamental_analysis": ("fundamental", "基本面分析"),
    "technical_analysis": ("technical", "技术面分析"),
    "value_analysis": ("value", "估值分析"),
    "news_analysis": ("news", "新闻分析"),
}


def build_assistant_summary(state: AgentState, *, full_analysis: bool) -> str | None:
    """完整分析时写入 chat_history 的短摘要（完整报告存 analysis_snapshots）。"""
    if not full_analysis:
        return None
    data = state.get("data", {})
    company = data.get("company_name") or "标的"
    report = data.get("final_report") or ""
    return f"✅ 已完成 {company} 完整分析（报告约 {len(report)} 字）"


def build_time_context() -> dict[str, str]:
    now = datetime.now()
    current_date_cn = now.strftime("%Y年%m月%d日")
    current_date_en = now.strftime("%Y-%m-%d")
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]
    current_time = now.strftime("%H:%M:%S")
    return {
        "current_date": current_date_en,
        "current_date_cn": current_date_cn,
        "current_time": current_time,
        "current_weekday_cn": weekday_cn,
        "current_time_info": f"{current_date_cn} ({current_date_en}) {weekday_cn} {current_time}",
        "analysis_timestamp": now.isoformat(),
    }


def build_query_data(user_query: str, company_name: str | None, stock_code: str | None) -> dict[str, Any]:
    data = {"query": user_query, **build_time_context()}
    if company_name:
        data["company_name"] = company_name
    normalized = normalize_stock_code(stock_code)
    if normalized:
        data["stock_code"] = normalized
    return data


async def run_full_workflow(
    app,
    initial_state: AgentState,
    *,
    on_progress: ProgressCallback | None = None,
) -> AgentState:
    data = initial_state.get("data", {})
    if on_progress is None:
        print(f"\n{WAIT_ICON} 正在并行执行分析（基本面 / 技术面 / 估值 / 新闻）...")
        if data.get("company_name"):
            print(f"{WAIT_ICON} 分析公司: {data['company_name']}")
        if data.get("stock_code"):
            print(f"{WAIT_ICON} 股票代码: {data['stock_code']}")
        print(f"{WAIT_ICON} 这可能需要几分钟，请耐心等待...\n")
        return await app.ainvoke(initial_state)

    on_progress("parallel", "四路分析并行进行中…")
    seen_steps: set[str] = set()
    final_state: AgentState = initial_state

    async for state in app.astream(initial_state, stream_mode="values"):
        final_state = state
        step_data = state.get("data", {})
        for output_key, (step, label) in ANALYSIS_OUTPUT_KEYS.items():
            if step_data.get(output_key) and step not in seen_steps:
                seen_steps.add(step)
                on_progress(step, f"{label}完成 ({len(seen_steps)}/4)")
        if step_data.get("final_report"):
            on_progress("summary", "综合报告已生成")

    return final_state


async def process_turn(
    app,
    session: SessionContext,
    user_query: str,
    *,
    on_progress: ProgressCallback | None = None,
    quiet: bool = False,
    record_user_message: bool = True,
    user_id: str | None = None,
    session_id: str | None = None,
) -> AgentState | None:
    """处理一轮用户输入：完整分析或基于上下文的追问。"""
    execution_logger = get_execution_logger()
    if record_user_message:
        session.append_user(user_query)

    company_name, stock_code = extract_stock_info(user_query)
    logger.info(f"从查询中提取 - 公司名称: {company_name}, 股票代码: {stock_code}")

    if session.needs_full_analysis(user_query, company_name, stock_code):
        is_full = True
        query_data = build_query_data(user_query, company_name, stock_code)
        if not query_data.get("stock_code") and session.stock_code:
            query_data["stock_code"] = session.stock_code
        if not query_data.get("company_name") and session.company_name:
            query_data["company_name"] = session.company_name

        initial_state = session.merge_state_for_turn(query_data)
        logger.info(f"Starting full workflow for query: '{user_query}'")
        if not quiet:
            print(f"\n{WAIT_ICON} 正在对 '{user_query}' 进行金融分析...")
        if on_progress:
            on_progress("start", "开始完整分析")
        final_state = await run_full_workflow(app, initial_state, on_progress=on_progress)
        reply = _extract_reply(final_state, full_analysis=True)
    else:
        is_full = False
        logger.info(f"Follow-up turn for query: '{user_query}'")
        if not quiet:
            print(f"\n{WAIT_ICON} 基于已有分析回答追问...")
        if on_progress:
            on_progress("follow_up", "基于已有分析回答追问…")
        final_state = await run_follow_up(
            session,
            user_query,
            user_id=user_id,
            session_id=session_id,
        )
        reply = _extract_reply(final_state, full_analysis=False)

    history_reply = build_assistant_summary(final_state, full_analysis=is_full) or reply
    session.update_from_state(final_state, reply, history_reply=history_reply)
    if not quiet:
        _print_reply(final_state, reply, full_analysis=is_full)
    _log_outputs(final_state, execution_logger, reply)
    return final_state


def _extract_reply(state: AgentState, *, full_analysis: bool) -> str:
    data = state.get("data", {})
    if full_analysis:
        return data.get("final_report") or data.get("follow_up_reply") or "（未生成报告）"
    return data.get("follow_up_reply") or data.get("final_report") or "（未生成回答）"


def _print_reply(state: AgentState, reply: str, *, full_analysis: bool) -> None:
    data = state.get("data", {})
    if full_analysis:
        print(f"{SUCCESS_ICON} 分析完成！")
        print("\n--- 最终分析报告 (Final Analysis Report) ---\n")
        print(reply)
        if data.get("report_path"):
            print(f"\n{SUCCESS_ICON} 报告已保存到: {data['report_path']}")
    else:
        print(f"{SUCCESS_ICON} 追问回答：\n")
        print(reply)


def _log_outputs(state: AgentState, execution_logger, reply: str) -> None:
    data = state.get("data", {})
    if data.get("final_report") and data.get("report_path"):
        execution_logger.log_final_report(data["final_report"], data["report_path"])
    elif reply:
        execution_logger.log_final_report(reply, data.get("report_path", ""))
