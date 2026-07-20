"""
批量评测入口 - 对 benchmark_cases 运行 Agent 并输出评分报告
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

from harness.eval.graders import ANALYSIS_AGENT_NAMES, GradeResult, grade_from_episode, grade_output

BENCHMARK_PATH = Path(__file__).resolve().parent / "benchmark_cases.json"


def _get_single_agent_names() -> set[str]:
    from harness.core.agent_runner import REACT_AGENT_CONFIG
    return set(REACT_AGENT_CONFIG.keys())


def _get_react_agent_config() -> dict[str, dict[str, str]]:
    from harness.core.agent_runner import REACT_AGENT_CONFIG
    return REACT_AGENT_CONFIG


def load_benchmark_cases() -> list[dict[str, Any]]:
    with open(BENCHMARK_PATH, encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark_cases.json 必须是非空数组")
    return cases


def validate_case(case: dict[str, Any]) -> None:
    required = ("id", "agent", "input", "expect")
    missing = [field for field in required if field not in case]
    if missing:
        raise ValueError(f"用例 {case.get('id', '<unknown>')} 缺少字段: {', '.join(missing)}")
    if not case["input"].get("query"):
        raise ValueError(f"用例 {case['id']} 的 input.query 不能为空")


def filter_cases(
    cases: list[dict[str, Any]],
    *,
    agent: str | None = None,
    case_id: str | None = None,
) -> list[dict[str, Any]]:
    filtered = cases
    if agent:
        filtered = [case for case in filtered if case["agent"] == agent]
    if case_id:
        filtered = [case for case in filtered if case["id"] == case_id]
    return filtered


def build_eval_state(case_input: dict[str, Any]):
    from src.utils.state_definition import AgentState

    now = datetime.now()
    current_date_en = now.strftime("%Y-%m-%d")
    current_date_cn = now.strftime("%Y年%m月%d日")
    current_weekday_cn = ["星期一", "星期二", "星期三", "星期四",
                          "星期五", "星期六", "星期日"][now.weekday()]
    current_time = now.strftime("%H:%M:%S")
    current_time_info = (
        f"{current_date_cn} ({current_date_en}) {current_weekday_cn} {current_time}"
    )

    return AgentState(
        messages=[],
        data={
            **case_input,
            "current_date": current_date_en,
            "current_date_cn": current_date_cn,
            "current_time": current_time,
            "current_weekday_cn": current_weekday_cn,
            "current_time_info": current_time_info,
            "analysis_timestamp": now.isoformat(),
        },
        metadata={},
    )


async def run_single_agent_case(case: dict[str, Any]) -> GradeResult:
    from harness.core.agent_runner import run_react_agent
    from harness.core.skill_loader import load_skill

    agent_name = case["agent"]
    single_agent_names = _get_single_agent_names()
    if agent_name not in single_agent_names:
        raise ValueError(f"未知单 Agent 用例: {agent_name}")

    skill = load_skill(agent_name)
    state = build_eval_state(case["input"])
    start = time.time()

    try:
        result_state = await run_react_agent(
            agent_name,
            state,
            use_verification=False,
            use_retry=False,
        )
    except Exception as exc:
        return GradeResult(
            case_id=case["id"],
            agent=agent_name,
            skill_version=skill.version,
            passed=False,
            score=0.0,
            execution_time=time.time() - start,
            error=str(exc),
        )

    elapsed = time.time() - start
    react_agent_config = _get_react_agent_config()
    config = react_agent_config[agent_name]
    output = result_state.get("data", {}).get(config["output_key"], "")
    metadata = result_state.get("metadata", {})
    tool_calls = metadata.get(f"{agent_name}_tool_calls", [])
    error = result_state.get("data", {}).get(config["error_key"])

    return grade_output(
        case_id=case["id"],
        agent=agent_name,
        skill_version=skill.version,
        output=output,
        tool_calls=tool_calls,
        expect=case["expect"],
        execution_time=elapsed,
        metadata=metadata,
        error=error,
    )


async def run_pipeline_case(case: dict[str, Any]) -> GradeResult:
    from src.utils.execution_logger import finalize_execution_logger, initialize_execution_logger
    from src.workflow import build_workflow

    initialize_execution_logger()
    state = build_eval_state(case["input"])
    app = build_workflow()
    start = time.time()

    try:
        result_state = await app.ainvoke(state)
        finalize_execution_logger(success=True)
    except Exception as exc:
        finalize_execution_logger(success=False, error=str(exc))
        return GradeResult(
            case_id=case["id"],
            agent="main",
            skill_version="pipeline",
            passed=False,
            score=0.0,
            execution_time=time.time() - start,
            error=str(exc),
        )

    elapsed = time.time() - start
    data = result_state.get("data", {})
    metadata = result_state.get("metadata", {})
    output = data.get("final_report", "")
    error = data.get("summary_error")

    return grade_output(
        case_id=case["id"],
        agent="main",
        skill_version="pipeline",
        output=output,
        tool_calls=[],
        expect=case["expect"],
        execution_time=elapsed,
        metadata=metadata,
        error=error,
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _offline_metadata_from_episodes(execution_dir: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    episodes_dir = execution_dir / "episodes"
    for agent_name in ANALYSIS_AGENT_NAMES:
        episode = _read_json(episodes_dir / f"{agent_name}_episode.json")
        if episode is not None:
            metadata[f"{agent_name}_verification_passed"] = episode.get("success", False)
    return metadata


def _offline_output_for_case(case: dict[str, Any], execution_dir: Path) -> str:
    agent = case["agent"]
    if agent == "main":
        report_path = execution_dir / "reports" / "final_report.md"
        if report_path.exists():
            return _read_text(report_path)
        summary_log = _read_json(execution_dir / "agents" / "summary_agent_execution.json")
        if summary_log:
            return str(summary_log.get("output_data", {}).get("report_preview", ""))
        return ""

    if agent not in _get_single_agent_names():
        return ""

    agent_log = _read_json(execution_dir / "agents" / f"{agent}_execution.json")
    if agent_log:
        preview = agent_log.get("output_data", {}).get("analysis_preview")
        if preview:
            return str(preview)

    episode = _read_json(execution_dir / "episodes" / f"{agent}_episode.json")
    if episode:
        return str(episode.get("output_preview", ""))
    return ""


def run_offline_case(case: dict[str, Any], execution_id: str) -> GradeResult:
    execution_dir = PROJECT_ROOT / "logs" / execution_id
    if not execution_dir.exists():
        return GradeResult(
            case_id=case["id"],
            agent=case["agent"],
            skill_version="offline",
            passed=False,
            score=0.0,
            error=f"执行目录不存在: {execution_dir}",
        )

    episode_path = execution_dir / "episodes" / f"{case['agent']}_episode.json"
    episode = _read_json(episode_path) or {}
    output = _offline_output_for_case(case, execution_dir)
    metadata = _offline_metadata_from_episodes(execution_dir)

    if case["agent"] == "main":
        summary_episode = _read_json(execution_dir / "episodes" / "summary_agent_episode.json") or {}
        skill_version = str(summary_episode.get("skill_version", "pipeline"))
    else:
        skill_version = str(episode.get("skill_version", "offline"))

    return grade_from_episode(
        case_id=case["id"],
        agent=case["agent"],
        episode=episode,
        expect=case["expect"],
        output=output,
        metadata=metadata,
    )


def build_eval_report(results: list[GradeResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    avg_score = sum(result.score for result in results) / total if total else 0.0
    total_time = sum(result.execution_time for result in results)

    return {
        "eval_id": f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "avg_score": round(avg_score, 4),
            "total_time_seconds": round(total_time, 2),
        },
        "results": [result.to_dict() for result in results],
    }


def save_eval_report(report: dict[str, Any], output_dir: Path | None = None) -> Path:
    if output_dir is None:
        output_dir = PROJECT_ROOT / "logs" / report["eval_id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "eval_report.json"
    with open(report_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    return report_path


def print_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("\n=== Eval Summary ===")
    print(f"Total: {summary['total']}  Passed: {summary['passed']}  Failed: {summary['failed']}")
    print(f"Avg Score: {summary['avg_score']:.2%}  Total Time: {summary['total_time_seconds']}s")
    print("\nCases:")
    for result in report["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        print(
            f"  [{status}] {result['case_id']} ({result['agent']}) "
            f"score={result['score']:.2%} time={result['execution_time']:.1f}s"
        )
        if result.get("error"):
            print(f"         error: {result['error']}")


async def run_eval(
    *,
    agent: str | None = None,
    case_id: str | None = None,
    offline: bool = False,
    execution_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    cases = filter_cases(load_benchmark_cases(), agent=agent, case_id=case_id)
    if not cases:
        raise ValueError("没有匹配的评测用例")

    if dry_run:
        for case in cases:
            validate_case(case)
        report = {
            "eval_id": f"eval_dry_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(cases),
                "passed": len(cases),
                "failed": 0,
                "avg_score": 1.0,
                "total_time_seconds": 0,
            },
            "results": [
                {
                    "case_id": case["id"],
                    "agent": case["agent"],
                    "passed": True,
                    "score": 1.0,
                    "execution_time": 0.0,
                }
                for case in cases
            ],
            "dry_run": True,
        }
        print_summary(report)
        return report

    if offline and not execution_id:
        raise ValueError("离线评分需要 --execution-id")

    results: list[GradeResult] = []
    for case in cases:
        validate_case(case)
        print(f"Running case: {case['id']} ({case['agent']})")
        if offline:
            result = run_offline_case(case, execution_id)  # type: ignore[arg-type]
        elif case["agent"] == "main":
            result = await run_pipeline_case(case)
        else:
            result = await run_single_agent_case(case)
        results.append(result)

    report = build_eval_report(results)
    report_path = save_eval_report(report)
    print_summary(report)
    print(f"\nReport saved to: {report_path}")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Financial MCP Agent harness eval")
    parser.add_argument("--agent", type=str, help="只评测指定 Agent（含 main）")
    parser.add_argument("--case", type=str, help="只评测指定 case id")
    parser.add_argument("--offline", action="store_true", help="基于已有 logs 离线评分")
    parser.add_argument("--execution-id", type=str, help="离线评分使用的 logs 子目录名")
    parser.add_argument("--dry-run", action="store_true", help="只校验 benchmark_cases.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_eval(
        agent=args.agent,
        case_id=args.case,
        offline=args.offline,
        execution_id=args.execution_id,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
