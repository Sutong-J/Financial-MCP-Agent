# Skills + Harness 工程设计文档

**项目**: Financial-MCP-Agent  
**日期**: 2026-07-05  
**状态**: 待评审  
**作者**: AI Agent（与用户协作）

---

## 1. 背景与目标

### 1.1 现状

Financial-MCP-Agent 是一个基于 LangGraph 的多 Agent 金融分析系统，当前架构为：

```
用户查询 → LangGraph 工作流 → [4 个分析 Agent 并行] → Summary Agent → 报告
                                    ↓
                              MCP 工具（A 股数据）
```

**已有能力：**

| 组件 | 位置 | 作用 |
|------|------|------|
| LangGraph 工作流 | `src/main.py` | 并行编排 4 个分析 Agent + 汇总 |
| 5 个 Agent | `src/agents/*.py` | 基本面 / 技术 / 估值 / 新闻 / 汇总 |
| MCP 工具层 | `a-share-mcp-is-just-i-need/` | 20+ 个 A 股数据工具 |
| 执行日志 | `src/utils/execution_logger.py` | 记录 agent / LLM / tool 交互 |
| AgentState | `src/utils/state_definition.py` | 跨 Agent 状态传递 |

**现存问题：**

1. **Prompt 硬编码**：每个 Agent 的分析指令（约 15–30 行）直接写在 `.py` 文件中，调整分析逻辑需要改代码。
2. **工具约束靠文字**：如「不要使用 crawl_news」仅写在 prompt 里，LLM 仍可能违规调用。
3. **无输出验证**：Agent 返回什么就用什么，不检查报告是否包含必要指标或章节。
4. **无失败恢复**：出错只记录 error，不自动重试或降级。
5. **无系统评测**：各 Agent 有零散的 `test_*()` 函数，无法批量对比 Skill/模型版本。

### 1.2 目标

引入两层抽象，在不替换 MCP 的前提下提升系统的可维护性、可靠性和可评测性：

| 层 | 职责 | 类比 |
|----|------|------|
| **Skill** | 每个 Agent 的分析指令、约束、输出格式 | 操作手册（脑） |
| **Harness** | 运行时编排、工具过滤、验证、重试、评测 | 操作系统（身体） |

### 1.3 非目标（本阶段不做）

- 不替换或重构 MCP Server（`a-share-mcp-is-just-i-need`）
- 不引入新的 LLM 提供商或模型
- 不做 Cursor IDE Skills 互通（仅借鉴 SKILL.md 格式）
- 不实现 Harness-Bench 级别的完整 benchmark 平台（Phase 3 做轻量版）
- 不改动 `summary_agent` 的本地 FinR1 模型路径逻辑（仅抽 prompt）

---

## 2. 概念定义

### 2.1 Skill

Skill 是纯文本指令文件，告诉 Agent **怎么做分析**，不执行任何代码。

- 文件格式：Markdown + YAML frontmatter（借鉴 Cursor Skills）
- 位置：`Financial-MCP-Agent/skills/{agent_name}/SKILL.md`
- 运行时：由 `skill_loader.py` 读取，渲染变量后注入 `SystemMessage` / `HumanMessage`

### 2.2 Harness

Harness 是包裹 LLM + Skill + MCP 的**运行时底座**，负责：

| Harness 平面 | 本项目对应 | 现状 |
|-------------|-----------|------|
| **Loop**（循环控制） | LangGraph 工作流 | ✅ 已有 |
| **Context**（上下文） | Skill 加载 + 变量渲染 | ❌ 待建 |
| **Action**（动作） | MCP 工具 + 工具过滤 | ⚠️ MCP 有，过滤无 |
| **State**（状态） | AgentState + ExecutionLogger | ✅ 已有 |
| **Assurance**（保障） | Verifier + RetryPolicy | ❌ 待建 |
| **Operations**（运维） | Episode Package + Eval + Replay | ⚠️ 日志有，评测无 |

### 2.3 三者关系

```
Skill（怎么做）  +  MCP（能做什么）  →  在 Harness（怎么跑、怎么验）中执行
```

---

## 3. 架构设计

### 3.1 目录结构

```
Financial-MCP-Agent/
├── skills/                              # Skill 层（新增）
│   ├── fundamental_agent/
│   │   └── SKILL.md
│   ├── technical_agent/
│   │   └── SKILL.md
│   ├── value_agent/
│   │   └── SKILL.md
│   ├── news_agent/
│   │   └── SKILL.md
│   └── summary_agent/
│       └── SKILL.md
│
├── harness/                             # Harness 层（新增）
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── skill_loader.py              # 加载、解析、渲染 SKILL.md
│   │   ├── tool_filter.py               # 按 allowed/forbidden 过滤 MCP 工具
│   │   ├── agent_runner.py              # 统一的 ReAct Agent 执行入口
│   │   ├── verifier.py                  # 规则验证器
│   │   ├── retry_policy.py              # 失败重试策略
│   │   └── episode.py                   # Episode Package 数据结构
│   └── eval/
│       ├── __init__.py
│       ├── benchmark_cases.json         # 评测用例
│       ├── graders.py                   # 自动评分器
│       └── run_eval.py                  # 批量评测入口
│
├── src/                                 # 现有代码（瘦身）
│   ├── agents/                          # 各 Agent 改为调用 harness
│   ├── main.py                          # 不变（工作流编排）
│   ├── tools/                           # 不变（MCP 客户端）
│   └── utils/                           # 不变（日志、状态）
│
└── docs/superpowers/specs/              # 设计文档（本文件）
```

### 3.2 数据流

```
用户查询
    │
    ▼
main.py: LangGraph 工作流启动
    │
    ▼
agent_runner.run(agent_name, state)
    │
    ├─ skill_loader.load("fundamental_agent")
    │     → 读取 skills/fundamental_agent/SKILL.md
    │     → 渲染变量: {company_name}, {stock_code}, {current_date}, ...
    │
    ├─ tool_filter.apply(mcp_tools, skill.allowed_tools, skill.forbidden_tools)
    │     → 返回过滤后的工具列表
    │
    ├─ create_react_agent(llm, filtered_tools)
    │     → SystemMessage(skill.system_prompt)
    │     → HumanMessage(skill.user_prompt)
    │     → 执行 ReAct 循环
    │
    ├─ verifier.check(result, skill.verification_rules)
    │     → 通过 → 返回结果
    │     → 不通过 → retry_policy.retry(...)
    │
    └─ episode.record(execution_id, traces, verification_report)
          → 写入 logs/{execution_id}/
    │
    ▼
返回 AgentState（与现有接口兼容）
```

### 3.3 与现有代码的集成点

| 现有文件 | 改动方式 | 改动量 |
|---------|---------|--------|
| `src/agents/fundamental_agent.py` | 删除内联 `agent_input`，改为调用 `agent_runner.run()` | 中 |
| `src/agents/technical_agent.py` | 同上 | 中 |
| `src/agents/value_agent.py` | 同上 | 中 |
| `src/agents/news_agent.py` | 同上 | 中 |
| `src/agents/summary_agent.py` | 抽取 `system_prompt` / `user_prompt` 到 SKILL.md | 中 |
| `src/main.py` | **不改**（工作流编排不变） | 无 |
| `src/utils/execution_logger.py` | 扩展：支持记录 verification_result | 小 |
| `src/tools/mcp_client.py` | **不改** | 无 |
| `a-share-mcp-is-just-i-need/` | **不改** | 无 |

---

## 4. Skill 规范

### 4.1 文件格式

```markdown
---
name: fundamental_agent
description: 基本面分析 - 财务报表、盈利能力、偿债能力
version: "1.0"
allowed_tools:
  - get_stock_basic_info
  - get_profit_data
  - get_balance_data
  - get_cash_flow_data
  - get_growth_data
  - get_operation_data
  - get_dupont_data
  - get_dividend_data
  - get_stock_industry
  - get_latest_trading_date
forbidden_tools:
  - crawl_news
temperature: 0.3
max_tokens: 6000
max_retries: 2
verification:
  must_contain:
    - ROE
    - 毛利率
    - 资产负债率
  must_not_call:
    - crawl_news
  min_output_length: 500
---

# 基本面分析专家

你是一位专业的 A 股基本面分析师。

## 分析步骤

1. 获取公司基本信息和行业背景
2. 获取最新财务报表数据（资产负债表、利润表、现金流量表）
3. 分析盈利能力指标（毛利率、净利率、ROE 等）
4. 分析成长能力指标（收入增长率、利润增长率等）
5. 分析运营效率指标（应收周转率、存货周转率等）
6. 分析偿债能力指标（资产负债率、流动比率等）
7. 查询历史分红情况
8. 提供基本面综合评估和投资价值分析

## 约束

- 专注于财务数据和基本面指标，不要使用 crawl_news 工具
- 使用工具获取实际数据，不要基于假设编造
- 如果某些数据无法获取，尝试不同时间周期或工具组合

## 用户请求模板

请分析 {company_name}（股票代码：{stock_code}）的基本面情况。

当前时间：{current_time_info}
当前日期：{current_date}
```

### 4.2 Frontmatter 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | Agent 名称，与目录名一致 |
| `description` | string | ✅ | 简短描述 |
| `version` | string | ❌ | Skill 版本号，用于评测对比 |
| `allowed_tools` | list[string] | ❌ | 工具白名单；为空则允许全部 |
| `forbidden_tools` | list[string] | ❌ | 工具黑名单 |
| `temperature` | float | ❌ | LLM 温度，默认 0.3 |
| `max_tokens` | int | ❌ | 最大 token，默认 6000 |
| `max_retries` | int | ❌ | 验证失败后最大重试次数，默认 1 |
| `verification` | object | ❌ | 验证规则（见 5.2） |

### 4.3 变量渲染

Skill 正文和「用户请求模板」支持以下占位符，由 `skill_loader.py` 在运行时替换：

| 变量 | 来源 | 示例 |
|------|------|------|
| `{company_name}` | `state.data.company_name` | 贵州茅台 |
| `{stock_code}` | `state.data.stock_code` | sh.600519 |
| `{current_time_info}` | `state.data.current_time_info` | 2026年07月05日 ... |
| `{current_date}` | `state.data.current_date` | 2026-07-05 |
| `{user_query}` | `state.data.query` | 分析茅台 |

### 4.4 五个 Agent 的 Skill 规划

| Agent | allowed_tools 核心 | forbidden_tools | verification 要点 |
|-------|-------------------|-----------------|-------------------|
| `fundamental_agent` | 财报类 7 个 + 基本信息 + 行业 | `crawl_news` | 含 ROE、毛利率、资产负债率 |
| `technical_agent` | K 线 + 基本信息 + 分析工具 | `crawl_news` | 含 支撑位、阻力位、趋势 |
| `value_agent` | 基本信息 + 分红 + 财报 + 行业 | `crawl_news` | 含 市盈率、市净率 |
| `news_agent` | `crawl_news` + 基本信息 | 财报类工具 | 含 情感分析、风险评估 |
| `summary_agent` | 无（不调 MCP） | 全部 | 含 8 个报告章节标题 |

---

## 5. Harness 核心模块

### 5.1 skill_loader.py

```python
@dataclass
class Skill:
    name: str
    description: str
    version: str
    system_prompt: str          # frontmatter 之后的 Markdown 正文
    user_prompt_template: str # 「用户请求模板」段落
    allowed_tools: list[str]
    forbidden_tools: list[str]
    temperature: float
    max_tokens: int
    max_retries: int
    verification: dict

def load_skill(agent_name: str) -> Skill: ...
def render_skill(skill: Skill, variables: dict) -> Skill: ...
```

**行为：**
- 从 `skills/{agent_name}/SKILL.md` 读取文件
- 用 `python-frontmatter` 或手动解析 YAML frontmatter
- 将正文作为 `system_prompt`
- 提取「用户请求模板」段落，渲染变量后作为 `user_prompt`
- 缓存已加载的 Skill（进程内单例）

### 5.2 verifier.py

```python
@dataclass
class VerificationResult:
    passed: bool
    checks: list[dict]   # [{name, passed, detail}]

def verify(output: str, tool_calls: list[str], rules: dict) -> VerificationResult: ...
```

**支持的规则：**

| 规则 | 类型 | 检查方式 |
|------|------|---------|
| `must_contain` | list[string] | 输出文本包含所有关键词 |
| `must_not_contain` | list[string] | 输出文本不包含任何关键词 |
| `must_not_call` | list[string] | 工具调用记录中未出现禁止工具 |
| `must_call` | list[string] | 工具调用记录中至少调用过一次 |
| `min_output_length` | int | 输出字符数 ≥ 阈值 |
| `must_have_sections` | list[string] | 输出包含所有 Markdown 章节标题（summary 专用） |

全部为**确定性规则检查**，不依赖 LLM judge（Phase 3 可选扩展）。

### 5.3 retry_policy.py

```python
def should_retry(verification: VerificationResult, attempt: int, max_retries: int) -> bool: ...
def build_retry_prompt(original_prompt: str, verification: VerificationResult) -> str: ...
```

**重试策略：**
- 验证不通过且 `attempt < max_retries` 时重试
- 重试时在 user_prompt 末尾追加失败原因：
  ```
  [系统提示] 上次分析未通过验证，原因：
  - 缺少关键词: ROE
  - 违规调用了工具: crawl_news
  请修正后重新分析。
  ```
- 重试使用相同 Skill 和过滤后的工具，不切换模型
- 所有重试记录写入 Episode Package

### 5.4 tool_filter.py

```python
def filter_tools(
    all_tools: list,
    allowed: list[str] | None,
    forbidden: list[str] | None
) -> list: ...
```

**逻辑：**
1. 若 `allowed_tools` 非空 → 只保留白名单中的工具
2. 若 `forbidden_tools` 非空 → 移除黑名单中的工具
3. 两者同时存在时：先白名单过滤，再黑名单排除
4. 若过滤后工具列表为空 → 记录 warning，回退到全部工具（不阻断执行）

### 5.5 agent_runner.py

统一的 Agent 执行入口，替代各 Agent 文件中重复的 ReAct 执行逻辑：

```python
async def run_agent(
    agent_name: str,
    state: AgentState,
    *,
    use_verification: bool = True,
    use_retry: bool = True,
) -> AgentState:
    """
    1. load_skill(agent_name)
    2. render_skill(variables from state.data)
    3. get_mcp_tools() → filter_tools()
    4. create_react_agent(llm, filtered_tools)
    5. invoke with SystemMessage + HumanMessage
    6. verify → retry if needed
    7. update state.data with result
    8. log via execution_logger
    9. return updated AgentState
    """
```

**各 Agent 文件瘦身为：**

```python
async def fundamental_agent(state: AgentState) -> AgentState:
    return await run_agent("fundamental_agent", state)
```

### 5.6 episode.py

```python
@dataclass
class EpisodePackage:
    execution_id: str
    agent_name: str
    skill_version: str
    input_state: dict
    output_state: dict
    tool_calls: list[dict]
    llm_interactions: list[dict]
    verification_result: VerificationResult | None
    retry_count: int
    total_execution_time: float
    success: bool
```

写入 `logs/{execution_id}/episodes/{agent_name}_episode.json`，与现有日志结构并存。

---

## 6. 评测框架（Phase 3）

### 6.1 benchmark_cases.json

```json
[
  {
    "id": "maotai_fundamental",
    "agent": "fundamental_agent",
    "input": {
      "query": "分析贵州茅台的基本面",
      "stock_code": "sh.600519",
      "company_name": "贵州茅台"
    },
    "expect": {
      "must_contain": ["ROE", "毛利率", "净利润"],
      "must_not_call": ["crawl_news"],
      "min_output_length": 500
    }
  },
  {
    "id": "maotai_full_pipeline",
    "agent": "main",
    "input": {
      "query": "分析贵州茅台",
      "stock_code": "sh.600519",
      "company_name": "贵州茅台"
    },
    "expect": {
      "must_have_sections": ["执行摘要", "基本面分析", "技术分析", "投资建议"],
      "all_agents_success": true
    }
  }
]
```

### 6.2 graders.py

```python
@dataclass
class GradeResult:
    case_id: str
    agent: str
    skill_version: str
    passed: bool
    score: float          # 0.0 - 1.0
    check_details: list[dict]
    execution_time: float

def grade(case: dict, episode: EpisodePackage) -> GradeResult: ...
```

评分规则：每个 `expect` 检查项通过得 1 分，总分 = 通过数 / 总检查数。

### 6.3 run_eval.py

```bash
# 运行全部评测
python -m harness.eval.run_eval

# 只评测某个 Agent
python -m harness.eval.run_eval --agent fundamental_agent

# 对比两个 Skill 版本
python -m harness.eval.run_eval --skill-version 1.0 vs 1.1
```

输出：`logs/eval_{timestamp}/eval_report.json` + 控制台摘要。

---

## 7. 实施计划

### Phase 1: Skill 基础设施（预计 1-2 天）

| 任务 | 产出 |
|------|------|
| 实现 `skill_loader.py` | 加载、解析、渲染 SKILL.md |
| 创建 5 个 SKILL.md | 从现有 prompt 迁移 |
| 实现 `tool_filter.py` | 工具白名单/黑名单过滤 |
| 实现 `agent_runner.py` | 统一 ReAct 执行入口 |
| 改造 5 个 Agent 文件 | 调用 `agent_runner.run()` |
| 验证：手动跑一次完整分析 | 输出与改造前一致 |

**验收标准：**
- 5 个 Agent 的 prompt 全部来自 SKILL.md，`.py` 文件中无内联 prompt
- 修改 SKILL.md 后重新运行，输出反映变更
- 现有 `main.py` 工作流无需改动即可正常运行

### Phase 2: Harness 保障层（预计 1-2 天）

| 任务 | 产出 |
|------|------|
| 实现 `verifier.py` | 5 种确定性验证规则 |
| 实现 `retry_policy.py` | 验证失败自动重试 |
| 实现 `episode.py` | Episode Package 记录 |
| 扩展 `execution_logger.py` | 记录 verification_result |
| 在 SKILL.md 中配置 verification 规则 | 每个 Agent 有过验证规则 |
| 验证：故意让 Agent 违规，确认重试生效 | 日志中有 retry 记录 |

**验收标准：**
- fundamental_agent 违规调用 crawl_news 时，工具被过滤（不会实际调用）
- 输出缺少 must_contain 关键词时，自动重试且重试 prompt 包含失败原因
- 每次 Agent 执行产出 `episodes/{agent}_episode.json`

### Phase 3: 评测框架（预计 1 天）

| 任务 | 产出 |
|------|------|
| 编写 `benchmark_cases.json` | 至少 5 个评测用例 |
| 实现 `graders.py` | 自动评分 |
| 实现 `run_eval.py` | 批量评测 CLI |
| 跑一次完整评测 | eval_report.json |

**验收标准：**
- `python -m harness.eval.run_eval` 可批量运行并输出评分报告
- 修改 Skill 版本后重跑，评分可对比

### Phase 4: 回放与文档（预计 0.5 天，可选）

| 任务 | 产出 |
|------|------|
| 实现 `replay_from_log.py` | 从 logs 复现执行 |
| 更新项目 README | 说明 Skill/Harness 用法 |

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Skill 渲染变量缺失 | Agent 收到未替换的 `{company_name}` | `skill_loader` 在渲染前校验所有必需变量，缺失则报错 |
| 工具白名单过窄 | Agent 无法获取必要数据 | 白名单为空时默认允许全部；过滤后为空时回退 |
| 验证规则过严 | 频繁重试，增加延迟和 token 消耗 | `max_retries` 默认 1；规则可 per-agent 配置 |
| 改造 Agent 文件引入 bug | 分析结果质量下降 | Phase 1 验收时对比改造前后输出；保留 git 历史 |
| MCP 路径硬编码 | Windows 环境无法启动 MCP | 本次不改动；后续将 `mcp_config.py` 路径改为相对路径或环境变量 |

---

## 9. 依赖

### 新增 Python 依赖

```
python-frontmatter>=1.0.0    # 解析 SKILL.md frontmatter
pyyaml>=6.0                  # YAML 解析（frontmatter 依赖）
```

添加到 `requirements.txt`，不引入重量级新框架。

### 环境变量

无新增。沿用现有 `.env` 配置：

```
OPENAI_COMPATIBLE_API_KEY
OPENAI_COMPATIBLE_BASE_URL
OPENAI_COMPATIBLE_MODEL
USE_LOCAL_MODEL
```

---

## 10. 开放问题

以下问题在实施前需确认：

1. **MCP 路径**：`mcp_config.py` 中硬编码了 `/root/code/Finance/...` 路径，Windows 环境需要改为相对路径。是否在 Phase 1 一并修复？
2. **Summary Agent 双模型**：`summary_agent` 支持 API 和本地 FinR1 两种模式（`USE_LOCAL_MODEL`），Skill 是否需要为两种模式各写一份？
3. **评测用例来源**：benchmark_cases.json 中的股票是否固定为茅台/嘉友国际等已有测试标的？
4. **Skill 版本管理**：是否需要 git tag 或 changelog 来追踪 Skill 版本变更？

---

## 11. 成功指标

| 指标 | 目标 |
|------|------|
| Prompt 外部化率 | 100%（5/5 Agent prompt 来自 SKILL.md） |
| 工具违规率 | 0%（forbidden_tools 被实际过滤） |
| 验证覆盖率 | 4/4 分析 Agent 有 verification 规则 |
| 评测用例数 | ≥ 5 个 |
| 改造前后输出一致性 | 同输入同模型，结构基本一致 |
| 现有工作流兼容性 | `main.py` 零改动可运行 |
