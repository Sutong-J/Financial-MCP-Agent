"""
统一 ReAct Agent 执行入口 - 通过 Skill 驱动分析 Agent
"""
from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from harness.core.episode import EpisodePackage, save_episode, verification_to_dict
from harness.core.retry_policy import build_retry_prompt, should_retry
from harness.core.skill_loader import Skill, load_skill, render_skill
from harness.core.tool_filter import filter_tools
from harness.core.verifier import verify
from src.tools.mcp_client import mcp_agent_session
from src.utils.execution_logger import get_execution_logger
from src.utils.logging_config import setup_logger, ERROR_ICON, SUCCESS_ICON, WAIT_ICON
from src.utils.state_definition import AgentState

load_dotenv(override=True)

logger = setup_logger(__name__)

REACT_AGENT_CONFIG: dict[str, dict[str, str]] = {
    "fundamental_agent": {
        "output_key": "fundamental_analysis",
        "error_key": "fundamental_analysis_error",
        "executed_key": "fundamental_agent_executed",
        "timestamp_key": "fundamental_agent_timestamp",
        "execution_time_key": "fundamental_agent_execution_time",
        "error_meta_key": "fundamental_agent_error",
        "completion_message": "基本面分析已完成",
        "preview_key": "fundamental_analysis_length",
        "log_label": "FundamentalAgent",
    },
    "technical_agent": {
        "output_key": "technical_analysis",
        "error_key": "technical_analysis_error",
        "executed_key": "technical_agent_executed",
        "timestamp_key": "technical_agent_timestamp",
        "execution_time_key": "technical_agent_execution_time",
        "error_meta_key": "technical_agent_error",
        "completion_message": "技术分析已完成",
        "preview_key": "technical_analysis_length",
        "log_label": "TechnicalAgent",
    },
    "value_agent": {
        "output_key": "value_analysis",
        "error_key": "value_analysis_error",
        "executed_key": "value_agent_executed",
        "timestamp_key": "value_agent_timestamp",
        "execution_time_key": "value_agent_execution_time",
        "error_meta_key": "value_agent_error",
        "completion_message": "估值分析已完成",
        "preview_key": "value_analysis_length",
        "log_label": "ValueAgent",
    },
    "news_agent": {
        "output_key": "news_analysis",
        "error_key": "news_analysis_error",
        "executed_key": "news_agent_executed",
        "timestamp_key": "news_agent_timestamp",
        "execution_time_key": "news_agent_execution_time",
        "error_meta_key": "news_agent_error",
        "completion_message": "新闻分析已完成",
        "preview_key": "news_analysis_length",
        "log_label": "NewsAgent",
    },
}


def _build_variables(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "company_name": data.get("company_name", "Unknown"),
        "stock_code": data.get("stock_code", "Unknown"),
        "current_time_info": data.get("current_time_info", "未知时间"),
        "current_date": data.get("current_date", "未知日期"),
        "user_query": data.get("query", ""),
    }


def _extract_output(response: dict[str, Any]) -> str:
    final_output = "No analysis generated."
    if "messages" not in response or not isinstance(response["messages"], list):
        logger.error(f"Unexpected response format: {type(response)}")
        return final_output

    messages = response["messages"]
    ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]
    if ai_messages:
        return ai_messages[-1].content or final_output

    all_content = []
    for msg in messages:
        if hasattr(msg, "content") and msg.content:
            all_content.append(str(msg.content))
    return "\n".join(all_content) if all_content else final_output


def _extract_tool_calls(messages: list) -> list[str]:
    tool_names: list[str] = []
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            if isinstance(tc, dict):
                name = tc.get("name")
            else:
                name = getattr(tc, "name", None)
            if name:
                tool_names.append(name)
    return tool_names


def _build_messages(skill: Skill, user_prompt: str | None = None, *, attempt: int = 0) -> list:
    messages = []
    system_content = skill.build_system_prompt(attempt)
    if system_content:
        messages.append(SystemMessage(content=system_content))
    messages.append(HumanMessage(content=user_prompt or skill.user_prompt_template))
    return messages


async def run_react_agent(
    agent_name: str,
    state: AgentState,
    *,
    use_verification: bool = True,
    use_retry: bool = True,
) -> AgentState:
    """使用 Skill 配置执行 ReAct Agent，支持验证、重试和 Episode 记录。"""
    if agent_name not in REACT_AGENT_CONFIG:
        raise ValueError(f"未知 ReAct Agent: {agent_name}")

    config = REACT_AGENT_CONFIG[agent_name]
    label = config["log_label"]
    execution_logger = get_execution_logger()

    current_data = dict(state.get("data", {}))
    current_messages = list(state.get("messages", []))
    current_metadata = dict(state.get("metadata", {}))
    user_query = current_data.get("query")

    execution_logger.log_agent_start(agent_name, {
        "user_query": user_query,
        "stock_code": current_data.get("stock_code"),
        "company_name": current_data.get("company_name"),
        "input_data_keys": list(current_data.keys()),
    })

    if not user_query:
        logger.error(f"{ERROR_ICON} {label}: User query is missing in state data.")
        current_data[config["error_key"]] = "User query is missing."
        execution_logger.log_agent_complete(agent_name, current_data, 0, False, "User query is missing")
        return {"data": current_data, "messages": current_messages, "metadata": current_metadata}

    agent_start_time = time.time()

    try:
        api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
        base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
        model_name = os.getenv("OPENAI_COMPATIBLE_MODEL")

        if not all([api_key, base_url, model_name]):
            logger.error(f"{ERROR_ICON} {label}: Missing OpenAI environment variables.")
            current_data[config["error_key"]] = "Missing OpenAI environment variables."
            execution_logger.log_agent_complete(
                agent_name, current_data, time.time() - agent_start_time,
                False, "Missing OpenAI environment variables",
            )
            return {"data": current_data, "messages": current_messages, "metadata": current_metadata}

        skill = render_skill(load_skill(agent_name), _build_variables(current_data))

        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=skill.temperature,
            max_tokens=skill.max_tokens,
        )

        logger.info(f"{WAIT_ICON} {label}: Opening dedicated MCP session (skill v{skill.version})...")
        async with mcp_agent_session() as mcp_tools:
            if not mcp_tools:
                logger.error(f"{ERROR_ICON} {label}: No MCP tools available.")
                current_data[config["error_key"]] = "No MCP tools available."
                execution_logger.log_agent_complete(
                    agent_name, current_data, time.time() - agent_start_time,
                    False, "No MCP tools available",
                )
                return {"data": current_data, "messages": current_messages, "metadata": current_metadata}

            filtered_tools = filter_tools(mcp_tools, skill.allowed_tools, skill.forbidden_tools)
            tool_names = [t.name for t in filtered_tools]
            logger.info(f"{SUCCESS_ICON} {label}: Using {len(filtered_tools)} tools: {tool_names}")

            agent = create_react_agent(llm, filtered_tools)

            user_prompt = skill.user_prompt_template
            final_output = ""
            all_tool_calls: list[str] = []
            verification = None
            attempts_log: list[dict[str, Any]] = []
            retry_count = 0
            llm_execution_time = 0.0
            attempt = 0
            max_retries = skill.max_retries if use_retry else 0

            while True:
                input_messages = _build_messages(skill, user_prompt, attempt=attempt)
                disclosed = skill.disclosed_level_names(attempt)
                logger.info(
                    f"{WAIT_ICON} {label}: Calling ReAct agent"
                    f"{f' (retry {attempt})' if attempt > 0 else ''}"
                    f" [disclosed: {', '.join(disclosed)}]..."
                )
                llm_start = time.time()
                response = await agent.ainvoke({"messages": input_messages})
                attempt_time = time.time() - llm_start
                llm_execution_time += attempt_time

                output = _extract_output(response)
                response_messages = response.get("messages", [])
                tool_calls = _extract_tool_calls(response_messages)
                all_tool_calls.extend(tool_calls)

                if use_verification and skill.verification:
                    verification = verify(output, tool_calls, skill.verification)
                else:
                    verification = None

                attempt_record = {
                    "attempt": attempt,
                    "disclosed_levels": skill.disclosed_level_names(attempt),
                    "execution_time": attempt_time,
                    "output_length": len(output),
                    "tool_calls": tool_calls,
                    "verification_passed": verification.passed if verification else True,
                }
                if verification and not verification.passed:
                    attempt_record["failures"] = verification.failure_messages()
                attempts_log.append(attempt_record)

                log_input = []
                system_content = skill.build_system_prompt(attempt)
                if system_content:
                    log_input.append({"role": "system", "content": system_content})
                log_input.append({"role": "user", "content": user_prompt})

                execution_logger.log_llm_interaction(
                    agent_name=agent_name,
                    interaction_type="react_agent" if attempt == 0 else f"react_agent_retry_{attempt}",
                    input_messages=log_input,
                    output_content=output,
                    model_config={
                        "model": model_name,
                        "temperature": skill.temperature,
                        "max_tokens": skill.max_tokens,
                        "api_base": base_url,
                        "skill_version": skill.version,
                        "attempt": attempt,
                        "disclosed_levels": skill.disclosed_level_names(attempt),
                    },
                    execution_time=attempt_time,
                )

                if verification is None or verification.passed:
                    final_output = output
                    break

                if should_retry(verification, attempt, max_retries):
                    retry_count += 1
                    logger.warning(
                        f"{WAIT_ICON} {label}: Verification failed, retrying "
                        f"({retry_count}/{max_retries}): {verification.failure_messages()}"
                    )
                    user_prompt = build_retry_prompt(skill.user_prompt_template, verification)
                    attempt += 1
                    continue

                final_output = output
                logger.warning(
                    f"{WAIT_ICON} {label}: Verification failed after {attempt + 1} attempt(s), "
                    f"using last output: {verification.failure_messages()}"
                )
                break

            logger.info(f"ReAct agent execution completed in {llm_execution_time:.2f} seconds")
            print(f"{label.upper()}: {final_output}")

            verification_passed = verification.passed if verification else True
            total_time = time.time() - agent_start_time

            episode = EpisodePackage(
                execution_id=execution_logger.execution_id,
                agent_name=agent_name,
                skill_version=skill.version,
                input_summary={
                    "company_name": current_data.get("company_name"),
                    "stock_code": current_data.get("stock_code"),
                    "query": user_query,
                },
                output_preview=final_output[:500] if len(final_output) > 500 else final_output,
                tool_calls=list(dict.fromkeys(all_tool_calls)),
                verification_result=verification_to_dict(verification),
                retry_count=retry_count,
                total_execution_time=total_time,
                success=verification_passed,
                attempts=attempts_log,
            )
            episode_path = save_episode(execution_logger.execution_dir, episode)
            logger.info(f"{SUCCESS_ICON} {label}: Episode saved to {episode_path}")

            current_data[config["output_key"]] = final_output
            current_metadata[config["executed_key"]] = True
            current_metadata[config["timestamp_key"]] = str(time.time())
            current_metadata[config["execution_time_key"]] = f"{llm_execution_time:.2f} seconds"
            current_metadata[f"{agent_name}_skill_version"] = skill.version
            current_metadata[f"{agent_name}_retry_count"] = retry_count
            current_metadata[f"{agent_name}_tool_calls"] = list(dict.fromkeys(all_tool_calls))
            current_metadata[f"{agent_name}_verification_passed"] = verification_passed
            if verification and not verification_passed:
                current_metadata[f"{agent_name}_verification_failures"] = verification.failure_messages()

            updated_messages = current_messages + [{"role": "assistant", "content": config["completion_message"]}]

            execution_logger.log_agent_complete(agent_name, {
                config["preview_key"]: len(final_output),
                "analysis_preview": final_output[:500] if len(final_output) > 500 else final_output,
                "llm_execution_time": llm_execution_time,
                "total_execution_time": total_time,
                "skill_version": skill.version,
                "retry_count": retry_count,
                "verification_passed": verification_passed,
                "episode_path": str(episode_path),
            }, total_time, verification_passed)

            if verification_passed:
                logger.info(f"{SUCCESS_ICON} {label}: Successfully completed analysis.")
            else:
                logger.warning(f"{WAIT_ICON} {label}: Completed with verification warnings.")

            return {"data": current_data, "messages": updated_messages, "metadata": current_metadata}

    except Exception as e:
        logger.error(f"{ERROR_ICON} {label}: Error during execution: {e}", exc_info=True)
        current_data[config["error_key"]] = f"Error during execution: {e}"
        current_data[config["output_key"]] = f"分析过程中出现错误: {str(e)}"
        current_metadata[config["error_meta_key"]] = str(e)
        execution_logger.log_agent_complete(
            agent_name, current_data, time.time() - agent_start_time, False, str(e),
        )
        return {"data": current_data, "messages": current_messages, "metadata": current_metadata}
