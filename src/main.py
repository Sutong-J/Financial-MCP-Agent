"""
金融分析智能体系统主程序 (Financial Analysis AI Agent System Main Program)

本文件是金融分析智能体系统的核心入口点，实现了以下主要功能：

1. 多智能体工作流管理：使用 LangGraph 构建四路并行分析 + 汇总工作流
2. 命令行界面：支持单次命令与多轮交互式追问
3. 自然语言处理：自动识别和提取股票代码、公司名称
4. 日志系统：完整的执行日志记录和错误处理
5. 报告生成：生成综合性的金融分析报告

工作流程：
start_node → [fundamental_analyst, technical_analyst, value_analyst, news_analyst 并行] → summarizer → END
"""

# ============================================================================
# 导入必要的模块和依赖
# ============================================================================

# 在导入其他模块之前设置环境变量，抑制无用输出
import os
import sys

# 设置环境变量来抑制transformers和其他库的冗余输出
os.environ["TRANSFORMERS_VERBOSITY"] = "error"  # 只显示错误信息
os.environ["TOKENIZERS_PARALLELISM"] = "false"  # 禁用tokenizer并行化警告
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"  # 减少CUDA相关输出
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"  # 减少内存分配信息

# 设置日志级别，抑制第三方库的INFO级别输出
import logging
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("accelerate").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

# 日志和状态管理相关导入
from src.utils.logging_config import setup_logger, SUCCESS_ICON, ERROR_ICON, WAIT_ICON
from src.utils.execution_logger import initialize_execution_logger, finalize_execution_logger, get_execution_logger

from src.run_session import EXIT_COMMANDS, process_turn
from src.utils.session_context import SessionContext
from src.workflow import build_workflow

# 环境变量和系统相关导入
from dotenv import load_dotenv
import argparse
import asyncio

# ============================================================================
# 初始化和配置
# ============================================================================

# 设置日志记录器
logger = setup_logger(__name__)

# 添加项目根目录到Python路径，确保模块导入正常工作
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# 加载环境变量（从.env文件）
load_dotenv(override=True)

# 调试：打印关键环境变量以验证配置
logger.info(f"Environment Variables Loaded:")
logger.info(
    f"  OPENAI_COMPATIBLE_MODEL: {os.getenv('OPENAI_COMPATIBLE_MODEL', 'Not Set')}")
logger.info(
    f"  OPENAI_COMPATIBLE_BASE_URL: {os.getenv('OPENAI_COMPATIBLE_BASE_URL', 'Not Set')}")
logger.info(
    f"  OPENAI_COMPATIBLE_API_KEY: {'*' * 20 if os.getenv('OPENAI_COMPATIBLE_API_KEY') else 'Not Set'}")

# 重新设置日志记录器（确保正确配置）
logger = setup_logger(__name__)


async def main():
    """
    主函数：金融分析智能体系统的核心执行逻辑
    
    功能包括：
    1. 初始化执行日志系统
    2. 构建LangGraph工作流
    3. 处理命令行参数和用户输入（支持多轮追问）
    4. 首轮执行完整分析，后续轮次基于已有报告快速回答
    """
    
    # 初始化执行日志系统
    execution_logger = initialize_execution_logger()
    logger.info(
        f"{SUCCESS_ICON} 执行日志系统已初始化，日志目录: {execution_logger.execution_dir}")

    try:
        # ============================================================================
        # 1. 命令行界面
        # ============================================================================
        
        # 创建命令行参数解析器
        parser = argparse.ArgumentParser(description="Financial Agent CLI")
        parser.add_argument(
            "--command",
            type=str,
            required=False,  # 改为非必需，支持交互式输入
            help="The user query for financial analysis (e.g., '分析嘉友国际')"
        )
        parser.add_argument(
            "--interactive",
            action="store_true",
            help="Enable multi-turn follow-up after the first query (default when no --command)",
        )
        args = parser.parse_args()

        multi_turn = args.interactive or not args.command

        # 处理用户查询输入
        if args.command:
            user_query = args.command
        else:
            print("\n")
            print(
                "╔══════════════════════════════════════════════════════════════════════════════╗")
            print(
                "║                                                                              ║")
            print(
                "║      ███████╗██╗███╗   ██╗ █████╗ ███╗   ██╗ ██████╗██╗ █████╗ ██╗          ║")
            print(
                "║      ██╔════╝██║████╗  ██║██╔══██╗████╗  ██║██╔════╝██║██╔══██╗██║          ║")
            print(
                "║      █████╗  ██║██╔██╗ ██║███████║██╔██╗ ██║██║     ██║███████║██║          ║")
            print(
                "║      ██╔══╝  ██║██║╚██╗██║██╔══██║██║╚██╗██║██║     ██║██╔══██║██║          ║")
            print(
                "║      ██║     ██║██║ ╚████║██║  ██║██║ ╚████║╚██████╗██║██║  ██║███████╗      ║")
            print(
                "║      ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚═╝╚═╝  ╚═╝╚══════╝      ║")
            print(
                "║                                                                              ║")
            print(
                "║                █████╗  ██████╗ ███████╗███╗   ██╗████████╗                  ║")
            print(
                "║               ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝                  ║")
            print(
                "║               ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║                     ║")
            print(
                "║               ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║                     ║")
            print(
                "║               ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║                     ║")
            print(
                "║               ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝                     ║")
            print(
                "║                                                                              ║")
            print("║                          🏦 金融分析智能体系统                              ║")
            print(
                "║                     Financial Analysis AI Agent System                      ║")
            print(
                "║                                                                              ║")
            print(
                "║    ┌─────────────────────────────────────────────────────────────────┐     ║")
            print("║    │  📊 基本面分析  │  📈 技术分析  │  💰 估值分析  │  📰 新闻分析  │  🤖 智能总结  │    ║")
            print(
                "║    └─────────────────────────────────────────────────────────────────┘     ║")
            print(
                "║                                                                              ║")
            print(
                "╚══════════════════════════════════════════════════════════════════════════════╝")
            print("\n🔹 本系统可以对A股公司进行全面分析，包括：")
            print("  • 基本面分析 - 财务状况、盈利能力和行业地位")
            print("  • 技术面分析 - 价格趋势、交易量和技术指标")
            print("  • 估值分析 - 市盈率、市净率等估值水平")
            print("  • 新闻分析 - 新闻情感分析和风险评估")
            print("\n🔹 支持多种自然语言查询方式：")
            print("  • 分析嘉友国际")
            print("  • 帮我看看比亚迪这只股票怎么样")
            print("  • 我想了解一下腾讯的投资价值")
            print("  • 603871 这个股票值得买吗？")
            print("  • 给我分析一下宁德时代的财务状况")
            print("\n🔹 您可以用任何自然语言描述您的分析需求")
            print("🔹 系统会自动识别股票名称和代码，并进行全面分析")
            print("\n🔹 支持多轮追问：首轮完整分析后，可继续提问（输入 exit 退出）")
            print("\n" + "─" * 78 + "\n")

            user_query = input("💬 请输入您的分析需求: ")

            while not user_query.strip():
                print(f"{ERROR_ICON} 输入不能为空，请重新输入！")
                user_query = input("请输入您的分析需求: ")

        session = SessionContext()
        app = build_workflow()

        while True:
            execution_logger.log_agent_start("main", {"user_query": user_query})
            await process_turn(app, session, user_query)

            if not multi_turn:
                break

            print("\n" + "─" * 78)
            print("💡 可继续追问，例如：「估值偏贵吗」「和刚才比风险在哪」「重新分析比亚迪 002594」")
            user_query = input("\n💬 继续追问（exit 退出）: ").strip()
            if not user_query or user_query.lower() in EXIT_COMMANDS:
                print(f"{SUCCESS_ICON} 会话结束。")
                break

        finalize_execution_logger(success=True)
        print(f"{SUCCESS_ICON} 执行日志已保存到: {execution_logger.execution_dir}")

    except Exception as e:
        # ============================================================================
        # 8. 错误处理
        # ============================================================================
        
        print(f"\n{ERROR_ICON} 工作流执行期间发生错误: {e}")
        logger.error(f"Error during workflow execution: {e}", exc_info=True)

        # 记录错误并完成执行日志
        finalize_execution_logger(success=False, error=str(e))
        print(f"{ERROR_ICON} 错误日志已保存到: {get_execution_logger().execution_dir}")


# ============================================================================
# 程序入口点
# ============================================================================

if __name__ == "__main__":
    # 使用asyncio运行主函数
    asyncio.run(main())
