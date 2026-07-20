"""
LangGraph 工作流构建 - 供 main.py 与评测框架共用
"""
from langgraph.graph import END, StateGraph

from src.agents.fundamental_agent import fundamental_agent
from src.agents.news_agent import news_agent
from src.agents.summary_agent import summary_agent
from src.agents.technical_agent import technical_agent
from src.agents.value_agent import value_agent
from src.utils.state_definition import AgentState


def build_workflow():
    """构建并编译金融分析多 Agent 工作流。"""
    workflow = StateGraph(AgentState)

    workflow.add_node("start_node", lambda state: state)
    workflow.add_node("fundamental_analyst", fundamental_agent)
    workflow.add_node("technical_analyst", technical_agent)
    workflow.add_node("value_analyst", value_agent)
    workflow.add_node("news_analyst", news_agent)
    workflow.add_node("summarizer", summary_agent)

    workflow.set_entry_point("start_node")

    # 四个分析 Agent 并行；各自通过 mcp_agent_session() 独占 MCP subprocess
    workflow.add_edge("start_node", "fundamental_analyst")
    workflow.add_edge("start_node", "technical_analyst")
    workflow.add_edge("start_node", "value_analyst")
    workflow.add_edge("start_node", "news_analyst")

    # 全部完成后汇总（LangGraph fan-in）
    workflow.add_edge("fundamental_analyst", "summarizer")
    workflow.add_edge("technical_analyst", "summarizer")
    workflow.add_edge("value_analyst", "summarizer")
    workflow.add_edge("news_analyst", "summarizer")

    workflow.add_edge("summarizer", END)

    return workflow.compile()
