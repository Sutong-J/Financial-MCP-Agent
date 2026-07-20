"""Harness 评测评分器单元测试（不调用 LLM）"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.eval.graders import grade_from_episode, grade_output


def test_grade_output_pass():
    result = grade_output(
        case_id="test_pass",
        agent="fundamental_agent",
        skill_version="1.0",
        output="ROE 为 15%，毛利率 40%，净利润增长",
        tool_calls=["get_profit_data"],
        expect={
            "must_contain": ["ROE", "毛利率"],
            "must_not_call": ["crawl_news"],
            "min_output_length": 10,
        },
    )
    assert result.passed
    assert result.score == 1.0


def test_grade_output_fail():
    result = grade_output(
        case_id="test_fail",
        agent="fundamental_agent",
        skill_version="1.0",
        output="ROE 为 15%",
        tool_calls=["crawl_news"],
        expect={
            "must_contain": ["ROE", "毛利率"],
            "must_not_call": ["crawl_news"],
        },
    )
    assert not result.passed
    assert result.score < 1.0
    assert len(result.check_details) >= 2


def test_grade_all_agents_success():
    result = grade_output(
        case_id="pipeline",
        agent="main",
        skill_version="pipeline",
        output="## 执行摘要\n## 基本面分析\n## 技术分析\n## 投资建议",
        tool_calls=[],
        expect={
            "must_have_sections": ["执行摘要", "投资建议"],
            "all_agents_success": True,
        },
        metadata={
            "fundamental_agent_verification_passed": True,
            "technical_agent_verification_passed": True,
            "value_agent_verification_passed": False,
            "news_agent_verification_passed": True,
        },
    )
    assert not result.passed
    assert any("value_agent" in check["detail"] for check in result.check_details)


def test_grade_from_episode():
    episode = {
        "skill_version": "1.0",
        "output_preview": "情感分析显示市场情绪偏正面",
        "tool_calls": ["crawl_news"],
        "total_execution_time": 2.5,
        "success": True,
    }
    result = grade_from_episode(
        case_id="news_offline",
        agent="news_agent",
        episode=episode,
        expect={"must_contain": ["情感"], "must_call": ["crawl_news"]},
    )
    assert result.passed
    assert result.skill_version == "1.0"


if __name__ == "__main__":
    test_grade_output_pass()
    test_grade_output_fail()
    test_grade_all_agents_success()
    test_grade_from_episode()
    print("All eval grader tests passed")
