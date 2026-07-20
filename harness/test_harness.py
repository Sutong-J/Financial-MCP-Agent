"""Harness 核心模块单元测试"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tempfile

from harness.core.skill_loader import (
    load_skill,
    clear_skill_cache,
    join_disclosure_sections,
)
from harness.core.verifier import verify
from harness.core.retry_policy import should_retry, build_retry_prompt
from harness.core.episode import EpisodePackage, save_episode, verification_to_dict


def test_verify_must_contain():
    result = verify("ROE 为 15%，毛利率 40%", [], {"must_contain": ["ROE", "毛利率"]})
    assert result.passed
    result2 = verify("ROE 为 15%", [], {"must_contain": ["ROE", "毛利率"]})
    assert not result2.passed
    assert any("毛利率" in m for m in result2.failure_messages())


def test_verify_must_not_call():
    result = verify("ok", ["get_profit_data"], {"must_not_call": ["crawl_news"]})
    assert result.passed
    result2 = verify("ok", ["crawl_news"], {"must_not_call": ["crawl_news"]})
    assert not result2.passed


def test_verify_must_have_sections():
    report = "## 执行摘要\n内容\n## 基本面分析\n内容\n## 投资建议\n内容"
    result = verify(report, [], {"must_have_sections": ["执行摘要", "基本面分析", "投资建议"]})
    assert result.passed


def test_retry_policy():
    from harness.core.verifier import VerificationResult, VerificationCheck
    vr = VerificationResult(passed=False, checks=[
        VerificationCheck("must_contain", False, "缺少关键词: ROE"),
    ])
    assert should_retry(vr, 0, 2)
    assert not should_retry(vr, 2, 2)
    prompt = build_retry_prompt("原始请求", vr)
    assert "ROE" in prompt
    assert "请修正后重新分析" in prompt


def test_episode_save():
    with tempfile.TemporaryDirectory() as tmp:
        ep = EpisodePackage(
            execution_id="test_001",
            agent_name="fundamental_agent",
            skill_version="1.0",
            input_summary={"query": "test"},
            output_preview="preview",
            tool_calls=["get_profit_data"],
            verification_result={"passed": True, "checks": []},
            retry_count=0,
            total_execution_time=1.5,
            success=True,
        )
        path = save_episode(Path(tmp), ep)
        assert path.exists()
        assert "fundamental_agent_episode.json" in str(path)


def test_skill_verification_loaded():
    clear_skill_cache()
    skill = load_skill("fundamental_agent")
    assert skill.max_retries == 2
    assert "ROE" in skill.verification.get("must_contain", [])
    assert "crawl_news" in skill.verification.get("must_not_call", [])


def test_progressive_disclosure_levels():
    clear_skill_cache()
    skill = load_skill("fundamental_agent")
    assert "core" in skill.disclosure_sections
    assert "execution" in skill.disclosure_sections
    assert "remediation" in skill.disclosure_sections

    first_prompt = skill.build_system_prompt(attempt=0)
    retry_prompt = skill.build_system_prompt(attempt=1)

    assert "基本面分析专家" in first_prompt
    assert "工具调用手册" in first_prompt
    assert "输出格式要求" not in first_prompt

    assert len(retry_prompt) > len(first_prompt)
    assert "输出格式要求" in retry_prompt

    assert skill.disclosed_level_names(0) == ["core", "execution"]
    assert skill.disclosed_level_names(1) == ["core", "execution", "remediation"]


def test_join_disclosure_sections():
    sections = {
        "core": "核心",
        "execution": "执行",
        "remediation": "修正",
    }
    assert "修正" not in join_disclosure_sections(sections, 0)
    assert "修正" in join_disclosure_sections(sections, 1)


if __name__ == "__main__":
    test_verify_must_contain()
    test_verify_must_not_call()
    test_verify_must_have_sections()
    test_retry_policy()
    test_episode_save()
    test_skill_verification_loaded()
    test_progressive_disclosure_levels()
    test_join_disclosure_sections()
    print("All harness tests passed")
