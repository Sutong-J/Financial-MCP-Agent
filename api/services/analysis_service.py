from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.orm import Session

from api.services.session_store import SessionStore
from src.utils.stock_extractor import extract_stock_info

from src.run_session import build_assistant_summary, process_turn
from src.utils.execution_logger import finalize_execution_logger, initialize_execution_logger
from src.utils.session_context import SessionContext
from src.utils.state_definition import AgentState

_analysis_lock = asyncio.Lock()

STEP_LABELS = {
    "start": "准备分析",
    "parallel": "四路分析并行",
    "fundamental": "基本面",
    "technical": "技术面",
    "value": "估值",
    "news": "新闻",
    "summary": "汇总报告",
    "follow_up": "追问回答",
}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_chat_turn(
    db: Session,
    workflow_app,
    session_id: str,
    user_id: str,
    user_message: str,
) -> AsyncIterator[str]:
    store = SessionStore(db, user_id)
    if not store.get_session(session_id):
        yield _sse("error", {"message": "会话不存在"})
        return

    if _analysis_lock.locked():
        yield _sse("error", {"message": "系统正在执行其他分析，请稍候再试"})
        return

    store.add_user_message(session_id, user_message)
    ctx = store.load_session_context(session_id) or SessionContext()
    company_name, stock_code = extract_stock_info(user_message)
    is_full_analysis = ctx.needs_full_analysis(user_message, company_name, stock_code)

    progress_events: list[tuple[str, str]] = []

    def on_progress(step: str, label: str) -> None:
        progress_events.append((step, label))

    async with _analysis_lock:
        execution_logger = initialize_execution_logger()
        try:
            yield ": connected\n\n"
            yield _sse("progress", {"step": "queued", "label": "任务已开始…"})

            async def run_turn() -> AgentState | None:
                return await process_turn(
                    workflow_app,
                    ctx,
                    user_message,
                    on_progress=on_progress,
                    quiet=True,
                    record_user_message=False,
                    user_id=user_id,
                    session_id=session_id,
                )

            task = asyncio.create_task(run_turn())
            tick = 0

            while not task.done():
                while progress_events:
                    step, label = progress_events.pop(0)
                    yield _sse(
                        "progress",
                        {
                            "step": step,
                            "label": label,
                            "display": STEP_LABELS.get(step, label),
                        },
                    )
                tick += 1
                if tick % 10 == 0:
                    elapsed = int(tick * 0.3)
                    yield _sse(
                        "progress",
                        {
                            "step": "heartbeat",
                            "label": f"分析进行中，已等待约 {elapsed} 秒…",
                            "display": f"分析进行中（约 {elapsed}s）",
                            "elapsed": elapsed,
                        },
                    )
                await asyncio.sleep(0.3)

            while progress_events:
                step, label = progress_events.pop(0)
                yield _sse(
                    "progress",
                    {"step": step, "label": label, "display": STEP_LABELS.get(step, label)},
                )

            final_state = await task
            finalize_execution_logger(success=True)

            if not final_state:
                yield _sse("error", {"message": "分析未返回结果"})
                return

            data = final_state.get("data", {})
            message_type = "report" if is_full_analysis else "follow_up"
            display_content = (
                data.get("final_report")
                if is_full_analysis
                else data.get("follow_up_reply") or data.get("final_report") or "（无内容）"
            )
            summary = build_assistant_summary(final_state, full_analysis=is_full_analysis)

            assistant_msg = store.add_assistant_message(
                session_id,
                display_content,
                message_type=message_type,
            )
            store.save_snapshot(
                session_id,
                final_state,
                report_path=data.get("report_path"),
            )

            yield _sse(
                "message",
                {
                    "message": assistant_msg,
                    "summary": summary,
                },
            )
            yield _sse(
                "done",
                {
                    "session_id": session_id,
                    "report_path": data.get("report_path"),
                },
            )
        except Exception as exc:
            finalize_execution_logger(success=False, error=str(exc))
            yield _sse("error", {"message": str(exc)})
