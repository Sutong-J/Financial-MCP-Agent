# Financial MCP Agent

一个面向中国 A 股的多智能体金融分析项目。系统通过 LangGraph 并行调度基本面、技术面、估值和新闻四类分析智能体，使用 MCP 服务获取市场数据，最后生成统一的综合分析报告。项目同时提供 Web 界面、命令行入口、会话管理、RAG 检索及智能体评测工具。

> 本项目仅用于学习、研究和辅助分析，不构成任何投资建议。金融市场存在风险，请独立判断并自行承担决策结果。

## 主要功能

- 多智能体并行分析：基本面、技术面、估值、新闻分析完成后由总结智能体汇总
- A 股数据工具：基于 BaoStock 的行情、财务报表、指数、宏观数据和市场概览查询
- 自然语言交互：支持股票名称、代码及自然语言分析需求
- Web 应用：用户注册、登录、会话管理、流式进度展示和 Markdown 报告
- 命令行模式：支持单次分析和连续追问
- RAG：支持 Chroma 本地检索，以及可选的 Elasticsearch 混合检索与重排
- 评测框架：包含智能体、技能和 RAG 的测试及基准样例
- 模型实验：包含新闻情感和风险模型的数据处理、LoRA 训练与测试脚本

## 工作流程

```text
用户问题
   │
   ├── 基本面分析 ──┐
   ├── 技术面分析 ──┤
   ├── 估值分析 ────┼── 综合总结 ── 分析报告
   └── 新闻分析 ────┘
          │
          └── MCP A 股数据服务（BaoStock 等）
```

## 技术栈

- 后端：Python、FastAPI、LangGraph、SQLAlchemy、SSE
- 智能体与模型：OpenAI 兼容 API、LangChain、Transformers、PEFT
- 数据工具：MCP、BaoStock
- 前端：Next.js 15、React 19、TypeScript、Tailwind CSS
- 数据存储：SQLite、Chroma；可选 Elasticsearch

## 项目结构

```text
Finance/
├── Financial-MCP-Agent/          # 智能体、API、Web 前端和评测框架
│   ├── api/                      # FastAPI 接口、认证、会话与数据库
│   ├── src/
│   │   ├── agents/               # 各分析智能体
│   │   ├── rag/                  # RAG 检索、分块、路由和重排
│   │   ├── tools/                # MCP 客户端及模型配置
│   │   └── workflow.py           # LangGraph 工作流
│   ├── skills/                   # 各智能体的技能说明
│   ├── harness/                  # 测试与评测框架
│   ├── web/                      # Next.js 前端
│   ├── scripts/start.ps1         # Windows 一键启动脚本
│   └── .env.example              # 环境变量示例
├── a-share-mcp-is-just-i-need/   # A 股 MCP 数据服务
├── nasdaq_news_sentiment/        # 新闻情感实验数据与 Notebook
├── risk_nasdaq/                  # 风险建模实验数据与 Notebook
├── data_process.py               # 新闻数据清洗与去重
├── download.py                   # Qwen3-8B 下载脚本
├── train_qwen_sentiment.py       # 情感模型训练
├── train_qwen_risk.py            # 风险模型训练
├── test_qwen_sentiment.py        # 情感模型测试
├── test_risk_model.py            # 风险模型测试
└── requirements.txt              # Python 依赖
```

## 环境要求

- Windows 10/11（项目提供 PowerShell 启动脚本）
- Python 3.12（MCP 锁文件声明的版本要求）
- Node.js 20 或更高版本
- npm
- [uv](https://docs.astral.sh/uv/)
- 可访问的 OpenAI 兼容模型 API

如果需要运行本地 Qwen 模型训练，建议准备支持 CUDA 的 NVIDIA GPU 和足够的显存、内存及磁盘空间。

## 快速开始

### 1. 安装 Python 依赖

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果需要 Elasticsearch 混合检索及重排：

```powershell
pip install -r .\Financial-MCP-Agent\requirements-rag.txt
```

### 2. 配置环境变量

```powershell
Copy-Item .\Financial-MCP-Agent\.env.example .\Financial-MCP-Agent\.env
```

编辑 `Financial-MCP-Agent/.env`，至少填写模型 API Key：

```dotenv
OPENAI_COMPATIBLE_API_KEY=your_api_key
OPENAI_COMPATIBLE_BASE_URL=https://your-api-endpoint.example/v1
OPENAI_COMPATIBLE_MODEL=your_model_name
USE_LOCAL_MODEL=api

RAG_BACKEND=chroma

# 生产环境务必设置为随机强密钥
JWT_SECRET=replace_with_a_long_random_secret
JWT_EXPIRE_DAYS=7
```

不要提交 `.env` 或任何真实密钥。

### 3. 启动 Web 应用

进入主应用目录并运行启动脚本：

```powershell
Set-Location .\Financial-MCP-Agent
.\scripts\start.ps1
```

脚本会启动：

- Web 页面：<http://localhost:3000/login>
- 后端 API：<http://127.0.0.1:8000>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

首次使用时，在 Web 页面注册本地账号，然后新建会话并输入例如“分析贵州茅台”或“分析 600519 的基本面与估值”。本地账号和会话默认保存在 `Financial-MCP-Agent/data/app.db`。

> `start.ps1` 会结束占用 3000 和 8000 端口的现有进程，请先确认这两个端口没有运行其他重要服务。

## 手动启动

需要分别调试前后端时，可打开两个终端。

后端：

```powershell
Set-Location .\Financial-MCP-Agent
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

前端：

```powershell
Set-Location .\Financial-MCP-Agent\web
npm install
npm run dev
```

前端默认访问 `http://127.0.0.1:8000/api`。如后端地址不同，可在 `Financial-MCP-Agent/web/.env.local` 中设置：

```dotenv
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api
```

## 命令行使用

在 `Financial-MCP-Agent` 目录中运行交互模式：

```powershell
python -m src.main
```

执行单次分析：

```powershell
python -m src.main --command "分析贵州茅台 600519"
```

显式启用连续追问：

```powershell
python -m src.main --interactive
```

执行日志和生成的报告会写入运行时数据目录；这些文件已被 Git 忽略。

## RAG 配置

默认使用 Chroma：

```dotenv
RAG_BACKEND=chroma
```

使用 Elasticsearch 时，先安装 `requirements-rag.txt`，然后配置：

```dotenv
RAG_BACKEND=elasticsearch
ES_URL=https://your-elasticsearch-endpoint
ES_API_KEY=your_elasticsearch_api_key
ES_INDEX=finance_rag_chunks

RAG_ENABLED=true
RAG_HYBRID_ENABLED=true
RAG_RERANK_ENABLED=true
RAG_CANDIDATE_K=20
```

相关检查脚本位于 `Financial-MCP-Agent/scripts/`。

## 测试与评测

在 `Financial-MCP-Agent` 目录执行：

```powershell
python -m pytest
python -m harness.eval.run_eval
python -m harness.eval.run_rag_eval --dry-run
```

如需只检查股票名称与代码提取：

```powershell
python test_extraction.py
```

部分测试会调用外部行情或模型服务，需要正确的网络连接和环境变量。

## 模型训练实验

根目录中的实验脚本用于 Qwen 新闻情感与风险模型训练，不是启动 Web 应用的必要步骤：

```powershell
python download.py
python train_qwen_sentiment.py
python train_qwen_risk.py
python test_qwen_sentiment.py
python test_risk_model.py
```

运行前请检查脚本中的数据路径、模型路径和训练参数。`download.py` 默认下载 `Qwen/Qwen3-8B`，模型体积较大；训练脚本对 GPU 资源要求较高。

## 常见问题

### MCP 服务无法启动

确认 `uv` 已安装且可在终端直接执行，并保持 `Financial-MCP-Agent` 与 `a-share-mcp-is-just-i-need` 为当前目录结构中的同级目录。主应用会按此相对位置查找 MCP 服务。

### 前端无法连接后端

先访问健康检查地址确认后端可用，再检查 `NEXT_PUBLIC_API_BASE`。默认后端端口为 8000，前端端口为 3000。

### 无法获取行情数据

BaoStock 和新闻工具依赖网络服务。请检查网络、数据源可用性以及股票代码格式；非交易日的最新数据日期可能早于当天。

### 中文显示乱码

建议将终端和源码统一使用 UTF-8。在 PowerShell 中可先执行：

```powershell
chcp 65001
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## 安全说明

- 不要在代码、截图或提交记录中暴露 API Key、Elasticsearch 密钥和 JWT 密钥
- 当前默认使用本地 SQLite，生产部署前应补充数据库备份、HTTPS、密钥管理和访问控制
- 生产环境不要使用默认的 JWT 开发密钥
- 金融分析结果可能存在延迟、缺失或模型幻觉，重要结论应通过权威数据源复核

## License

当前仓库未提供明确的开源许可证。如需分发、商用或二次发布，请先确认代码及所使用数据源、模型和第三方依赖各自的许可条款。
