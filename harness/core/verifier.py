"""
输出验证器 - 基于 Skill verification 规则的确定性检查
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VerificationCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class VerificationResult:
    passed: bool
    checks: list[VerificationCheck] = field(default_factory=list)

    def failure_messages(self) -> list[str]:
        return [c.detail for c in self.checks if not c.passed]


def verify(
    output: str,
    tool_calls: list[str],
    rules: dict[str, Any] | None,
) -> VerificationResult:
    """根据 Skill verification 规则验证 Agent 输出。"""
    if not rules:
        return VerificationResult(passed=True)

    checks: list[VerificationCheck] = []
    output_text = output or ""

    for keyword in rules.get("must_contain") or []:
        found = keyword in output_text
        checks.append(VerificationCheck(
            name="must_contain",
            passed=found,
            detail=f"缺少关键词: {keyword}" if not found else f"包含关键词: {keyword}",
        ))

    for keyword in rules.get("must_not_contain") or []:
        found = keyword in output_text
        checks.append(VerificationCheck(
            name="must_not_contain",
            passed=not found,
            detail=f"不应包含: {keyword}" if found else f"未包含禁用词: {keyword}",
        ))

    for tool_name in rules.get("must_not_call") or []:
        called = tool_name in tool_calls
        checks.append(VerificationCheck(
            name="must_not_call",
            passed=not called,
            detail=f"违规调用了工具: {tool_name}" if called else f"未调用禁用工具: {tool_name}",
        ))

    for tool_name in rules.get("must_call") or []:
        called = tool_name in tool_calls
        checks.append(VerificationCheck(
            name="must_call",
            passed=called,
            detail=f"未调用必需工具: {tool_name}" if not called else f"已调用工具: {tool_name}",
        ))

    min_length = rules.get("min_output_length")
    if min_length is not None:
        ok = len(output_text) >= int(min_length)
        checks.append(VerificationCheck(
            name="min_output_length",
            passed=ok,
            detail=(
                f"输出长度不足: {len(output_text)} < {min_length}"
                if not ok
                else f"输出长度满足: {len(output_text)} >= {min_length}"
            ),
        ))

    for section in rules.get("must_have_sections") or []:
        found = section in output_text
        checks.append(VerificationCheck(
            name="must_have_sections",
            passed=found,
            detail=f"缺少章节: {section}" if not found else f"包含章节: {section}",
        ))

    passed = all(c.passed for c in checks) if checks else True
    return VerificationResult(passed=passed, checks=checks)
