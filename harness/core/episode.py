"""
Episode Package - 记录单次 Agent 执行的完整轨迹
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.core.verifier import VerificationResult


@dataclass
class EpisodePackage:
    execution_id: str
    agent_name: str
    skill_version: str
    input_summary: dict[str, Any]
    output_preview: str
    tool_calls: list[str]
    verification_result: dict[str, Any] | None
    retry_count: int
    total_execution_time: float
    success: bool
    attempts: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def save_episode(execution_dir: Path, episode: EpisodePackage) -> Path:
    """将 Episode Package 写入 logs/{execution_id}/episodes/。"""
    episodes_dir = execution_dir / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    file_path = episodes_dir / f"{episode.agent_name}_episode.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(episode.to_dict(), f, ensure_ascii=False, indent=2)
    return file_path


def verification_to_dict(result: VerificationResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "passed": result.passed,
        "checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail}
            for c in result.checks
        ],
    }
