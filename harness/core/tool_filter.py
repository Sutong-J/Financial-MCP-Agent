"""
MCP 工具过滤器 - 按 Skill 的 allowed/forbidden 配置过滤工具
"""
from __future__ import annotations

from typing import Any

from src.utils.logging_config import setup_logger, WAIT_ICON

logger = setup_logger(__name__)


def filter_tools(
    all_tools: list[Any],
    allowed: list[str] | None = None,
    forbidden: list[str] | None = None,
) -> list[Any]:
    """
    按白名单/黑名单过滤 MCP 工具。

    1. allowed 非空 → 只保留白名单工具
    2. forbidden 非空 → 移除黑名单工具
    3. 过滤后为空 → 回退到全部工具并记录 warning
    """
    if not all_tools:
        return []

    filtered = list(all_tools)

    if allowed:
        allowed_set = set(allowed)
        filtered = [t for t in filtered if getattr(t, "name", None) in allowed_set]

    if forbidden:
        forbidden_set = set(forbidden)
        filtered = [t for t in filtered if getattr(t, "name", None) not in forbidden_set]

    if not filtered:
        logger.warning(
            f"{WAIT_ICON} tool_filter: 过滤后工具列表为空，回退到全部 {len(all_tools)} 个工具"
        )
        return list(all_tools)

    return filtered
