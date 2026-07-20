"""
Summary Agent: Consolidates analyses from other agents into a final report.
汇总 Agent：将其他 Agent的分析结果整合成最终报告
"""
import os
import time
from typing import Dict, Any
from langchain_openai import ChatOpenAI  # 恢复OpenAI导入
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import re

from harness.core.skill_loader import load_skill, render_skill
from harness.core.verifier import verify
from harness.core.retry_policy import should_retry, build_retry_prompt
from harness.core.episode import EpisodePackage, save_episode, verification_to_dict
from src.utils.state_definition import AgentState
from src.utils.logging_config import setup_logger, ERROR_ICON, SUCCESS_ICON, WAIT_ICON
from src.utils.execution_logger import get_execution_logger
from dotenv import load_dotenv

# 从.env文件加载环境变量
load_dotenv(override=True)

logger = setup_logger(__name__)


def truncate_report_at_baseline_time(report_content: str, current_time_info: str) -> str:
    """
    使用正则表达式截断报告，在"分析基准时间"那一行之后停止
    
    Args:
        report_content: 完整的报告内容
        current_time_info: 当前时间信息
    
    Returns:
        截断后的报告内容
    """
    # 构建多种可能的"分析基准时间"模式
    baseline_patterns = [
        rf'分析基准时间[：:]\s*{re.escape(current_time_info)}',
        rf'分析基准时间[：:]\s*{re.escape(current_time_info)}\s*$',
        rf'基准时间[：:]\s*{re.escape(current_time_info)}',
        rf'时间基准[：:]\s*{re.escape(current_time_info)}',
        rf'分析时间[：:]\s*{re.escape(current_time_info)}',
        rf'报告时间[：:]\s*{re.escape(current_time_info)}',
        rf'生成时间[：:]\s*{re.escape(current_time_info)}',
        rf'更新时间[：:]\s*{re.escape(current_time_info)}',
        rf'数据时间[：:]\s*{re.escape(current_time_info)}',
        rf'分析基准[：:]\s*{re.escape(current_time_info)}'
    ]
    
    # 尝试匹配各种模式
    for pattern in baseline_patterns:
        match = re.search(pattern, report_content, re.MULTILINE | re.IGNORECASE)
        if match:
            # 找到匹配位置，截断到该行的末尾
            end_pos = match.end()
            
            # 查找该行的结束位置（换行符）
            line_end = report_content.find('\n', end_pos)
            if line_end == -1:
                # 如果没有换行符，说明是最后一行，直接截断
                truncated_content = report_content[:end_pos].strip()
            else:
                # 截断到该行结束
                truncated_content = report_content[:line_end].strip()
            
            logger.info(f"截断报告在'分析基准时间'行之后，截断位置: {end_pos}")
            return truncated_content
    
    # 如果没有找到匹配的模式，尝试查找包含时间信息的行
    time_patterns = [
        rf'.*{re.escape(current_time_info)}.*',
        rf'.*{re.escape(current_time_info.split()[0])}.*',  # 只匹配日期部分
        rf'.*{re.escape(current_time_info.split()[1])}.*'   # 只匹配时间部分
    ]
    
    for pattern in time_patterns:
        match = re.search(pattern, report_content, re.MULTILINE | re.IGNORECASE)
        if match:
            end_pos = match.end()
            line_end = report_content.find('\n', end_pos)
            if line_end == -1:
                truncated_content = report_content[:end_pos].strip()
            else:
                truncated_content = report_content[:line_end].strip()
            
            logger.info(f"截断报告在时间信息行之后，截断位置: {end_pos}")
            return truncated_content
    
    # 如果都没有找到，返回原始内容
    logger.warning("未找到'分析基准时间'模式，返回原始报告内容")
    return report_content


def load_finr1_model(model_path="/root/code/Finance/FinR1"):
    """加载FinR1模型"""
    logger.info(f"{WAIT_ICON} Loading FinR1 model from {model_path}...")
    
    try:
        # 加载tokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        
        # 加载模型
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True
        )
        
        model.eval()
        logger.info(f"{SUCCESS_ICON} FinR1 model loaded successfully")
        return model, tokenizer
    
    except Exception as e:
        logger.error(f"{ERROR_ICON} Failed to load FinR1 model: {e}")
        raise e


def generate_report_with_finr1(model, tokenizer, prompt, max_new_tokens=5000):
    """使用FinR1模型生成报告"""
    
    try:
        # 编码输入
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        
        # 生成预测
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=0.5,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id
            )
        
        # 解码输出
        generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # 提取生成的报告部分（移除输入提示）
        # 方法1：尝试通过字符串匹配移除输入提示
        if prompt in generated_text:
            report = generated_text[len(prompt):].strip()
        else:
            # 方法2：如果字符串匹配失败，尝试通过token长度来提取
            input_length = len(tokenizer.encode(prompt, return_tensors="pt")[0])
            output_length = len(outputs[0])
            
            if output_length > input_length:
                # 只保留新生成的部分
                new_tokens = outputs[0][input_length:]
                report = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
            else:
                # 如果无法确定，返回完整文本但尝试清理
                report = generated_text.strip()
        
        return report
    
    except Exception as e:
        logger.error(f"{ERROR_ICON} Error generating report with FinR1: {e}")
        raise e


def get_model_choice():
    """获取模型选择，默认选择API"""
    # 可以通过环境变量控制模型选择
    model_choice = os.getenv("USE_LOCAL_MODEL", "api").lower()
    return model_choice


async def summary_agent(state: AgentState) -> Dict[str, Any]:
    """
    整合基本面、技术面和估值分析的结果
    使用LLM生成最终的综合性报告
    """
    logger.info(f"{WAIT_ICON} SummaryAgent: Starting to consolidate analyses.")

    # 获取执行日志记录器，用于记录 Agent的执行过程
    execution_logger = get_execution_logger()
    agent_name = "summary_agent"

    # 从状态中提取当前数据、消息和用户查询
    current_data = state.get("data", {})
    messages = state.get("messages", [])
    user_query = current_data.get("query", "")

    # 记录 Agent开始执行，包含可用的分析类型
    execution_logger.log_agent_start(agent_name, {
        "user_query": user_query,
        "available_analyses": {
            "fundamental": "fundamental_analysis" in current_data,
            "technical": "technical_analysis" in current_data,
            "value": "value_analysis" in current_data,
            "news": "news_analysis" in current_data
        },
        "input_data_keys": list(current_data.keys())
    })

    # 记录 Agent开始时间，用于计算执行时长
    agent_start_time = time.time()

    # 获取之前 Agent的分析结果
    fundamental_analysis = current_data.get(
        "fundamental_analysis", "Not available")
    technical_analysis = current_data.get(
        "technical_analysis", "Not available")
    value_analysis = current_data.get("value_analysis", "Not available")
    news_analysis = current_data.get("news_analysis", "Not available")

    # 处理各个分析的错误信息
    errors = []
    if "fundamental_analysis_error" in current_data:
        errors.append(
            f"Fundamental Analysis Error: {current_data['fundamental_analysis_error']}")
    if "technical_analysis_error" in current_data:
        errors.append(
            f"Technical Analysis Error: {current_data['technical_analysis_error']}")
    if "value_analysis_error" in current_data:
        errors.append(
            f"Value Analysis Error: {current_data['value_analysis_error']}")
    if "news_analysis_error" in current_data:
        errors.append(
            f"News Analysis Error: {current_data['news_analysis_error']}")

    # 基本股票标识信息
    stock_code = current_data.get("stock_code", "Unknown Stock")
    company_name = current_data.get("company_name", "Unknown Company")

    try:
        # 获取模型选择
        model_choice = get_model_choice()
        logger.info(f"{WAIT_ICON} SummaryAgent: Using model choice: {model_choice}")

        # 获取当前时间信息，用于报告中的时间标注
        current_time_info = current_data.get("current_time_info", "未知时间")
        current_date = current_data.get("current_date", "未知日期")

        errors_section = ""
        if errors:
            errors_section = "ANALYSIS ISSUES:\n" + ". ".join(errors)

        skill = render_skill(load_skill("summary_agent"), {
            "company_name": company_name,
            "stock_code": stock_code,
            "current_time_info": current_time_info,
            "current_date": current_date,
            "user_query": user_query,
            "fundamental_analysis": fundamental_analysis,
            "technical_analysis": technical_analysis,
            "value_analysis": value_analysis,
            "news_analysis": news_analysis,
            "errors_section": errors_section,
        })
        user_prompt = skill.user_prompt_template
        logger.info(f"{WAIT_ICON} SummaryAgent: Loaded skill v{skill.version}")

        current_user_prompt = user_prompt
        final_report = ""
        verification = None
        retry_count = 0
        attempts_log: list[dict] = []
        llm_execution_time = 0.0
        model_config: dict = {}

        for attempt in range(skill.max_retries + 1):
            system_prompt = skill.build_system_prompt(attempt)
            disclosed = skill.disclosed_level_names(attempt)
            logger.info(
                f"{WAIT_ICON} SummaryAgent: disclosed levels: {', '.join(disclosed)}"
            )
            if model_choice == "local":
                logger.info(f"{WAIT_ICON} SummaryAgent: Using local FinR1 model...")
                model_config = {
                    "model": "FinR1",
                    "temperature": skill.temperature,
                    "max_tokens": skill.max_tokens,
                    "model_path": "/root/code/Finance/FinR1",
                    "skill_version": skill.version,
                    "attempt": attempt,
                    "disclosed_levels": disclosed,
                }
                model, tokenizer = load_finr1_model()
                full_prompt = f"{system_prompt}\n\n{current_user_prompt}"
                llm_start_time = time.time()
                raw_report = generate_report_with_finr1(model, tokenizer, full_prompt)
                attempt_time = time.time() - llm_start_time
            else:
                logger.info(f"{WAIT_ICON} SummaryAgent: Using OpenAI API...")
                api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
                base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
                model_name = os.getenv("OPENAI_COMPATIBLE_MODEL")

                if not all([api_key, base_url, model_name]):
                    logger.error(
                        f"{ERROR_ICON} SummaryAgent: Missing OpenAI environment variables.")
                    current_data["summary_error"] = "Missing OpenAI environment variables."
                    execution_logger.log_agent_complete(
                        agent_name, current_data, time.time() - agent_start_time,
                        False, "Missing OpenAI environment variables",
                    )
                    return {"data": current_data, "messages": messages}

                model_config = {
                    "model": model_name,
                    "temperature": skill.temperature,
                    "max_tokens": skill.max_tokens,
                    "api_base": base_url,
                    "skill_version": skill.version,
                    "attempt": attempt,
                    "disclosed_levels": disclosed,
                }
                llm = ChatOpenAI(
                    model=model_name,
                    api_key=api_key,
                    base_url=base_url,
                    temperature=skill.temperature,
                    max_tokens=skill.max_tokens,
                )
                summary_prompt_messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": current_user_prompt},
                ]
                logger.info(f"{WAIT_ICON} SummaryAgent: Creating ChatOpenAI with model {model_name}")
                llm_start_time = time.time()
                llm_message = await llm.ainvoke(summary_prompt_messages)
                raw_report = llm_message.content
                attempt_time = time.time() - llm_start_time

            llm_execution_time += attempt_time
            final_report = raw_report.replace("```markdown", "").replace("```", "").strip()
            final_report = truncate_report_at_baseline_time(final_report, current_time_info)

            verification = verify(final_report, [], skill.verification) if skill.verification else None
            attempt_record = {
                "attempt": attempt,
                "disclosed_levels": disclosed,
                "execution_time": attempt_time,
                "output_length": len(final_report),
                "verification_passed": verification.passed if verification else True,
            }
            if verification and not verification.passed:
                attempt_record["failures"] = verification.failure_messages()
            attempts_log.append(attempt_record)

            interaction_type = "summary_generation" if attempt == 0 else f"summary_generation_retry_{attempt}"
            execution_logger.log_llm_interaction(
                agent_name=agent_name,
                interaction_type=interaction_type,
                input_messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": current_user_prompt},
                ],
                output_content=final_report,
                model_config=model_config,
                execution_time=attempt_time,
            )

            if verification is None or verification.passed:
                break
            if should_retry(verification, attempt, skill.max_retries):
                retry_count += 1
                logger.warning(
                    f"{WAIT_ICON} SummaryAgent: Verification failed, retrying "
                    f"({retry_count}/{skill.max_retries}): {verification.failure_messages()}"
                )
                current_user_prompt = build_retry_prompt(user_prompt, verification)
                continue
            logger.warning(
                f"{WAIT_ICON} SummaryAgent: Verification failed after {attempt + 1} attempt(s)"
            )
            break

        verification_passed = verification.passed if verification else True
        total_execution_time = time.time() - agent_start_time

        episode = EpisodePackage(
            execution_id=execution_logger.execution_id,
            agent_name=agent_name,
            skill_version=skill.version,
            input_summary={
                "company_name": company_name,
                "stock_code": stock_code,
                "query": user_query,
            },
            output_preview=final_report[:500] if len(final_report) > 500 else final_report,
            tool_calls=[],
            verification_result=verification_to_dict(verification),
            retry_count=retry_count,
            total_execution_time=total_execution_time,
            success=verification_passed,
            attempts=attempts_log,
        )
        episode_path = save_episode(execution_logger.execution_dir, episode)
        logger.info(f"{SUCCESS_ICON} SummaryAgent: Episode saved to {episode_path}")

        logger.info(
            f"{SUCCESS_ICON} SummaryAgent: Final report generated for {company_name} ({stock_code}).")
        logger.debug(f"Final report preview: {final_report[:300]}...")

        # 将报告保存到Markdown文件
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # 处理公司名称和股票代码，确保文件名有意义
        if stock_code == "Unknown Stock" or stock_code == "Extracted from analysis":
            # 从用户查询中提取更有意义的名称
            query_based_name = user_query.replace(
                " ", "_").replace("分析", "").strip()
            if not query_based_name:
                query_based_name = "financial_analysis"
            safe_file_prefix = f"report_{query_based_name}"
        else:
            # 正常情况下使用公司名称和股票代码
            safe_company_name = company_name.replace(" ", "_").replace(".", "")
            if safe_company_name == "Unknown_Company" or safe_company_name == "Extracted_from_analysis":
                safe_company_name = user_query.replace(
                    " ", "_").replace("分析", "").strip()
                if not safe_company_name:
                    safe_company_name = "company"

            # 清理股票代码（移除可能的前缀）
            clean_stock_code = stock_code.replace("sh.", "").replace("sz.", "")
            safe_file_prefix = f"report_{safe_company_name}_{clean_stock_code}"

        report_filename = f"{safe_file_prefix}_{timestamp}.md"

        # 确保reports目录存在
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "reports")
        os.makedirs(reports_dir, exist_ok=True)

        report_path = os.path.join(reports_dir, report_filename)

        # 将报告写入文件
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(final_report)

        logger.info(
            f"{SUCCESS_ICON} SummaryAgent: Report saved to {report_path}")

        # 返回更新后的状态，包含最终报告
        current_data["final_report"] = final_report
        current_data["report_path"] = report_path

        # 记录 Agent执行结果
        execution_logger.log_agent_complete(agent_name, {
            "final_report_length": len(final_report),
            "report_path": report_path,
            "report_preview": final_report,
            "llm_execution_time": llm_execution_time,
            "total_execution_time": total_execution_time,
            "skill_version": skill.version,
            "retry_count": retry_count,
            "verification_passed": verification_passed,
            "episode_path": str(episode_path),
        }, total_execution_time, verification_passed)

        return {"data": current_data, "messages": messages}

    except Exception as e:
        logger.error(
            f"{ERROR_ICON} SummaryAgent: Error generating final report: {e}", exc_info=True)
        current_data["summary_error"] = f"Error generating final report: {e}"

        # 即使出现错误也创建最小化的报告
        error_report = f"""
        # Analysis Report for {company_name} ({stock_code})
        
        **Error encountered during report generation**: {e}
        
        ## Available Analysis Fragments:
        
        - Fundamental Analysis: {"Available" if fundamental_analysis != "Not available" else "Not available"}
        - Technical Analysis: {"Available" if technical_analysis != "Not available" else "Not available"}
        - Value Analysis: {"Available" if value_analysis != "Not available" else "Not available"}
        - News Analysis: {"Available" if news_analysis != "Not available" else "Not available"}
        
        Please review the individual analyses directly for more information.
        """
        current_data["final_report"] = error_report

        # 也将错误报告保存到文件
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # 处理公司名称和股票代码，确保文件名有意义
        if stock_code == "Unknown Stock" or stock_code == "Extracted from analysis":
            # 从用户查询中提取更有意义的名称
            query_based_name = user_query.replace(
                " ", "_").replace("分析", "").strip()
            if not query_based_name:
                query_based_name = "financial_analysis"
            safe_file_prefix = f"error_report_{query_based_name}"
        else:
            # 正常情况下使用公司名称和股票代码
            safe_company_name = company_name.replace(" ", "_").replace(".", "")
            if safe_company_name == "Unknown_Company" or safe_company_name == "Extracted_from_analysis":
                safe_company_name = user_query.replace(
                    " ", "_").replace("分析", "").strip()
                if not safe_company_name:
                    safe_company_name = "company"

            # 清理股票代码（移除可能的前缀）
            clean_stock_code = stock_code.replace("sh.", "").replace("sz.", "")
            safe_file_prefix = f"error_report_{safe_company_name}_{clean_stock_code}"

        report_filename = f"{safe_file_prefix}_{timestamp}.md"

        # 确保reports目录存在
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "reports")
        os.makedirs(reports_dir, exist_ok=True)

        report_path = os.path.join(reports_dir, report_filename)

        # 将错误报告写入文件
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(error_report)

        logger.info(
            f"{ERROR_ICON} SummaryAgent: Error report saved to {report_path}")
        current_data["report_path"] = report_path

        # 记录 Agent执行失败
        execution_logger.log_agent_complete(
            agent_name, current_data, time.time() - agent_start_time, False, str(e))

        return {"data": current_data, "messages": messages}


# 本地测试函数
async def test_summary_agent():
    """汇总 Agent的测试函数"""
    from src.utils.state_definition import AgentState

    # 用于测试的示例状态，包含模拟分析结果
    test_state = AgentState(
        messages=[],
        data={
            "query": "分析嘉友国际",
            "stock_code": "603871",
            "company_name": "嘉友国际",
            "fundamental_analysis": "嘉友国际基本面分析：公司主营业务为跨境物流、供应链贸易以及供应链增值服务。财务状况良好，负债率较低，现金流充裕。近年来业绩稳步增长，毛利率保持在行业较高水平。",
            "technical_analysis": "嘉友国际技术分析：短期内股价处于上升通道，突破了200日均线。RSI指标显示股票尚未达到超买区域。MACD指标呈现多头形态，成交量有所放大，支持价格继续上行。",
            "value_analysis": "嘉友国际估值分析：当前市盈率为15倍，低于行业平均水平。市净率为1.8倍，处于合理区间。与同行业公司相比，嘉友国际的估值较为合理，具有一定的投资价值。",
            "news_analysis": "嘉友国际新闻分析：近期公司发布了2023年业绩预告，预计净利润同比增长15-25%，超出市场预期。同时，公司宣布与多家国际物流巨头达成战略合作，市场反应积极。分析师普遍上调了目标价，市场情绪偏向乐观。"
        },
        metadata={}
    )

    # 运行 Agent并输出结果
    result = await summary_agent(test_state)
    print("Summary Report:")
    print(result.get("data", {}).get("final_report", "No report generated"))
    print(
        f"Report saved to: {result.get('data', {}).get('report_path', 'Not saved')}")

    return result

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_summary_agent())
