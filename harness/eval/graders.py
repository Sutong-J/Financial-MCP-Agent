"""
评测评分器 - 复用 verifier 对 benchmark expect 规则打分
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from harness.core.verifier import verify

VERIFICATION_RULE_KEYS = (
    "must_contain",
    "must_not_contain",
    "must_call",
    "must_not_call",
    "min_output_length",
    "must_have_sections",
)

ANALYSIS_AGENT_NAMES = (
    "fundamental_agent",
    "technical_agent",
    "value_agent",
    "news_agent",
)


@dataclass
class GradeResult:
    case_id: str
    agent: str
    skill_version: str
    passed: bool
    score: float
    check_details: list[dict[str, Any]] = field(default_factory=list)
    execution_time: float = 0.0
    output_preview: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_verification_rules(expect: dict[str, Any]) -> dict[str, Any]:
    return {key: expect[key] for key in VERIFICATION_RULE_KEYS if key in expect}


def _score_from_checks(checks: list[dict[str, Any]]) -> float:
    if not checks:
        return 1.0
    passed = sum(1 for check in checks if check["passed"])
    return passed / len(checks)


def _append_all_agents_success_checks(
    metadata: dict[str, Any],
    checks: list[dict[str, Any]],
) -> None:
    for agent_name in ANALYSIS_AGENT_NAMES:
        passed = metadata.get(f"{agent_name}_verification_passed", False)
        checks.append({
            "name": "all_agents_success",
            "passed": passed,
            "detail": (
                f"{agent_name} 验证通过"
                if passed
                else f"{agent_name} 验证未通过"
            ),
        })


def grade_output(
    case_id: str,
    agent: str,
    skill_version: str,
    output: str,
    tool_calls: list[str],
    expect: dict[str, Any],
    *,
    execution_time: float = 0.0,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> GradeResult:
    """对 Agent 输出按 expect 规则评分。"""
    if error:
        return GradeResult(
            case_id=case_id,
            agent=agent,
            skill_version=skill_version,
            passed=False,
            score=0.0,
            execution_time=execution_time,
            output_preview=(output or "")[:300],
            error=error,
        )

    rules = _extract_verification_rules(expect)
    result = verify(output, tool_calls, rules or None)
    check_details = [
        {"name": check.name, "passed": check.passed, "detail": check.detail}
        for check in result.checks
    ]

    if expect.get("all_agents_success"):
        _append_all_agents_success_checks(metadata or {}, check_details)

    passed = all(check["passed"] for check in check_details) if check_details else True
    score = _score_from_checks(check_details)

    return GradeResult(
        case_id=case_id,
        agent=agent,
        skill_version=skill_version,
        passed=passed,
        score=score,
        check_details=check_details,
        execution_time=execution_time,
        output_preview=(output or "")[:300],
    )


def grade_from_episode(
    case_id: str,
    agent: str,
    episode: dict[str, Any],
    expect: dict[str, Any],
    *,
    output: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> GradeResult:
    """从 episode 记录离线评分（output 可传入完整文本）。"""
    output_text = output if output is not None else episode.get("output_preview", "")
    tool_calls = episode.get("tool_calls", [])
    skill_version = str(episode.get("skill_version", "unknown"))
    execution_time = float(episode.get("total_execution_time", 0.0))

    return grade_output(
        case_id=case_id,
        agent=agent,
        skill_version=skill_version,
        output=output_text,
        tool_calls=tool_calls,
        expect=expect,
        execution_time=execution_time,
        metadata=metadata,
        error=episode.get("error"),
    )
