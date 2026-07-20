"""
NewsAnalysis Agent: Performs news analysis with sentiment and risk assessment using ReAct Agent framework.
新闻分析 Agent：使用ReAct Agent框架进行新闻分析，包含情感分析和风险评估
"""
import asyncio
from datetime import datetime

from harness.core.agent_runner import run_react_agent
from src.utils.state_definition import AgentState


async def news_agent(state: AgentState) -> AgentState:
    """使用 Skill + ReAct 框架进行新闻分析。"""
    return await run_react_agent("news_agent", state)


async def test_news_agent():
    """新闻分析 Agent 的测试函数"""
    current_datetime = datetime.now()
    current_date_cn = current_datetime.strftime("%Y年%m月%d日")
    current_date_en = current_datetime.strftime("%Y-%m-%d")
    current_weekday_cn = ["星期一", "星期二", "星期三", "星期四",
                          "星期五", "星期六", "星期日"][current_datetime.weekday()]
    current_time = current_datetime.strftime("%H:%M:%S")
    current_time_info = f"{current_date_cn} ({current_date_en}) {current_weekday_cn} {current_time}"

    test_state = AgentState(
        messages=[],
        data={
            "query": "分析嘉友国际的新闻情况",
            "stock_code": "sh.603871",
            "company_name": "嘉友国际",
            "current_date": current_date_en,
            "current_date_cn": current_date_cn,
            "current_time": current_time,
            "current_weekday_cn": current_weekday_cn,
            "current_time_info": current_time_info,
            "analysis_timestamp": current_datetime.isoformat(),
        },
        metadata={},
    )

    result = await news_agent(test_state)
    print("News Analysis Result:")
    print(result.get("data", {}).get("news_analysis", "No analysis found"))
    return result


if __name__ == "__main__":
    asyncio.run(test_news_agent())
