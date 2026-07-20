"""多轮对话会话上下文。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.utils.state_definition import AgentState
from src.utils.stock_extractor import normalize_stock_code

FULL_ANALYSIS_KEYWORDS = (
    "重新分析", "再分析", "刷新分析", "更新分析", "换一只", "换个",
)


class SessionContext:
    """在同一次进程运行中保留对话与分析结果。"""

    def __init__(self) -> None:
        self.chat_history: list[dict[str, str]] = []
        self.last_state: AgentState | None = None
        self.turn_count = 0

    def has_analysis(self) -> bool:
        data = (self.last_state or {}).get("data", {})
        return bool(data.get("final_report") or data.get("fundamental_analysis"))

    @property
    def company_name(self) -> str | None:
        if not self.last_state:
            return None
        return self.last_state.get("data", {}).get("company_name")

    @property
    def stock_code(self) -> str | None:
        if not self.last_state:
            return None
        return self.last_state.get("data", {}).get("stock_code")

    def append_user(self, content: str) -> None:
        self.chat_history.append({"role": "user", "content": content})

    def append_assistant(self, content: str) -> None:
        self.chat_history.append({"role": "assistant", "content": content})

    def format_chat_history(self, max_turns: int = 8) -> str:
        if not self.chat_history:
            return "（暂无历史对话）"
        recent = self.chat_history[-max_turns * 2 :]
        lines = []
        for msg in recent:
            role = "用户" if msg["role"] == "user" else "助手"
            lines.append(f"{role}: {msg['content']}")
        return "\n\n".join(lines)

    def needs_full_analysis(
        self,
        query: str,
        company_name: str | None,
        stock_code: str | None,
    ) -> bool:
        if not self.has_analysis():
            return True
        if any(kw in query for kw in FULL_ANALYSIS_KEYWORDS):
            return True

        new_code = normalize_stock_code(stock_code)
        prev_code = normalize_stock_code(self.stock_code)
        if new_code and prev_code and new_code != prev_code:
            return True

        if company_name and self.company_name:
            a, b = company_name.strip(), self.company_name.strip()
            if a and b and a not in b and b not in a:
                if stock_code or any(kw in query for kw in ("分析", "看看", "了解")):
                    return True
        return False

    def merge_state_for_turn(self, new_data: dict[str, Any]) -> AgentState:
        prev_data = dict((self.last_state or {}).get("data", {}))
        prev_data.update(new_data)
        prev_data["chat_history"] = deepcopy(self.chat_history)
        prev_data["chat_history_text"] = self.format_chat_history()
        return AgentState(
            messages=list((self.last_state or {}).get("messages", [])),
            data=prev_data,
            metadata=dict((self.last_state or {}).get("metadata", {})),
        )

    def update_from_state(
        self,
        state: AgentState,
        assistant_reply: str,
        *,
        history_reply: str | None = None,
    ) -> None:
        self.last_state = state
        self.turn_count += 1
        self.append_assistant(history_reply or assistant_reply)
