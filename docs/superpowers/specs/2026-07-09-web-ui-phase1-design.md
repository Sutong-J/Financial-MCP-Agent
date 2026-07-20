# Web UI Phase 1 设计文档（无账号 · 本机部署）

**项目**: Financial-MCP-Agent  
**日期**: 2026-07-09  
**状态**: 待评审  
**场景**: A — 个人/小团队内网自用  
**Phase 1 范围**: A1 — 先 Web 聊天，后加注册登录  

---

## 1. 背景与目标

### 1.1 现状

系统已具备 CLI 多轮分析能力：

```
用户输入 → SessionContext → process_turn()
                              ├─ 完整分析: LangGraph 串行工作流 (5 Agent + MCP)
                              └─ 追问: follow_up_agent (基于已有报告)
```

**已有可复用模块：**

| 模块 | 路径 | 作用 |
|------|------|------|
| 工作流 | `src/workflow.py` | LangGraph 编排 |
| 会话逻辑 | `src/run_session.py` | `process_turn()` 单轮调度 |
| 会话上下文 | `src/utils/session_context.py` | 路由 + 对话历史 + 分析快照 |
| 追问 Agent | `src/agents/follow_up_agent.py` | 多轮追问 |
| 报告 | `reports/*.md` | Markdown 报告文件 |

**CLI 局限：**

- 无 Web 界面，非技术同事难用
- 会话仅存进程内存，刷新/重启即丢失
- 进度仅 `print()` 到终端，无法推送到 UI
- 无用户隔离（Phase 2 解决）

### 1.2 Phase 1 目标

交付一个**本机可运行的 Web 聊天界面**，功能等价于当前 CLI 多轮体验：

1. 浏览器输入分析需求，展示 Markdown 报告与追问回答
2. 左侧会话列表，支持新建/切换/删除会话
3. 完整分析时展示进度（基本面 → 技术面 → 估值 → 新闻 → 汇总）
4. 会话持久化到 SQLite，关闭浏览器后可恢复
5. **不做**注册登录（Phase 2）
6. **不做** Docker（提供 `start.ps1` 本机启动脚本）

### 1.3 非目标（Phase 1 不做）

- 用户注册 / 登录 / JWT
- 多用户数据隔离
- 后台任务队列（Redis/Celery）
- 向量检索 / 长期记忆
- 报告 PDF 导出
- 公网部署 / HTTPS / 防刷

---

## 2. 总体架构

### 2.1 逻辑架构

```
┌─────────────────────────────────────────────────────────┐
│  web/ (Next.js 15, App Router)                          │
│  ┌──────────────┐  ┌──────────────────────────────────┐ │
│  │ SessionList  │  │ ChatPanel                        │ │
│  │              │  │  - MessageList (Markdown)        │ │
│  │              │  │  - ProgressBar (SSE)             │ │
│  │              │  │  - InputBox                      │ │
│  └──────────────┘  └──────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP / SSE
┌───────────────────────────▼─────────────────────────────┐
│  api/ (FastAPI)                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ REST routes │  │ SessionStore │  │ AnalysisService │ │
│  │             │→ │ (SQLite)     │← │ process_turn()  │ │
│  └─────────────┘  └──────────────┘  └────────┬────────┘ │
└──────────────────────────────────────────────┼──────────┘
                                               │
┌──────────────────────────────────────────────▼──────────┐
│  src/ (现有 Agent 核心，尽量不改)                          │
│  workflow · run_session · session_context · MCP · skills  │
└───────────────────────────────────────────────────────────┘
```

### 2.2 部署方式（Windows 本机，无 Docker）

```powershell
# scripts/start.ps1 一键启动
# 终端逻辑：
#   1. uvicorn api.main:app --port 8000
#   2. cd web && npm run dev   # 或 npm run start
# 访问 http://localhost:3000
```

| 组件 | 端口 | 说明 |
|------|------|------|
| Next.js | 3000 | 前端，API 请求代理到 8000 |
| FastAPI | 8000 | 后端 + SSE |
| SQLite | 文件 | `data/app.db` |
| 报告文件 | 文件 | `data/reports/`（从现有 `reports/` 迁移逻辑） |

### 2.3 目录结构（新增部分）

```
Financial-MCP-Agent/
├── api/                          # 新增：Web API 层
│   ├── main.py                   # FastAPI 入口
│   ├── config.py                 # 路径、DB URL
│   ├── db/
│   │   ├── database.py           # SQLAlchemy engine
│   │   └── models.py             # ORM 模型
│   ├── schemas/                  # Pydantic 请求/响应
│   ├── routes/
│   │   ├── sessions.py
│   │   └── chat.py               # SSE 流式聊天
│   └── services/
│       ├── session_store.py      # DB ↔ SessionContext 桥接
│       └── analysis_service.py   # 包装 process_turn + 进度回调
├── web/                          # 新增：Next.js 前端
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx              # 重定向到 /chat
│   │   └── chat/
│   │       ├── page.tsx          # 会话列表 + 默认会话
│   │       └── [sessionId]/page.tsx
│   ├── components/
│   │   ├── SessionSidebar.tsx
│   │   ├── ChatMessages.tsx
│   │   ├── ChatInput.tsx
│   │   ├── ProgressSteps.tsx
│   │   └── MarkdownRenderer.tsx
│   ├── lib/api.ts                # fetch 封装
│   └── next.config.ts            # /api 代理到 localhost:8000
├── data/                         # 运行时数据（gitignore）
│   ├── app.db
│   └── reports/
├── scripts/
│   └── start.ps1
└── src/                          # 现有，最小改动
    └── run_session.py            # 增加 progress_callback 参数
```

---

## 3. 数据模型

### 3.1 SQLite 表设计（Phase 1，无 user_id）

```sql
-- 聊天会话
CREATE TABLE chat_sessions (
    id            TEXT PRIMARY KEY,          -- UUID
    title         TEXT NOT NULL DEFAULT '新对话',
    company_name  TEXT,
    stock_code    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- 消息（用户 + 助手）
CREATE TABLE chat_messages (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role          TEXT NOT NULL,             -- 'user' | 'assistant'
    content       TEXT NOT NULL,
    message_type  TEXT NOT NULL DEFAULT 'text',  -- 'text' | 'report' | 'follow_up'
    created_at    TEXT NOT NULL
);

-- 分析快照（供追问恢复 SessionContext）
CREATE TABLE analysis_snapshots (
    session_id    TEXT PRIMARY KEY REFERENCES chat_sessions(id) ON DELETE CASCADE,
    state_json    TEXT NOT NULL,             -- last_state.data 序列化 JSON
    report_path   TEXT,
    updated_at    TEXT NOT NULL
);
```

**设计说明：**

- `chat_messages` 存展示用文本；完整分析时 assistant 消息存**短摘要**（如「已完成贵州茅台完整分析」），完整报告存 `state_json.final_report`，避免对话历史 token 膨胀（与 CLI 问题对齐）。
- `analysis_snapshots.state_json` 保存 `fundamental_analysis`、`final_report` 等，用于 Web 重启后恢复追问能力。
- Phase 2 加 `users` 表，给 `chat_sessions` 增加 `user_id` 外键即可，无需推翻 schema。

### 3.2 SessionContext 桥接

```
DB load session
    → 从 chat_messages 重建 chat_history（assistant 用摘要）
    → 从 analysis_snapshots 恢复 last_state.data
    → 构造 SessionContext 实例

process_turn 完成
    → 写入 chat_messages
    → upsert analysis_snapshots
    → 更新 chat_sessions.title / company_name / stock_code
```

---

## 4. API 设计

Base URL: `http://localhost:8000/api`

### 4.1 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/sessions` | 列表，按 `updated_at` 降序 |
| `POST` | `/sessions` | 创建空会话，返回 `{ id, title, ... }` |
| `GET` | `/sessions/{id}` | 会话详情 + 消息列表 |
| `PATCH` | `/sessions/{id}` | 修改标题 |
| `DELETE` | `/sessions/{id}` | 删除会话及关联数据 |

### 4.2 聊天（SSE 流式）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/sessions/{id}/chat` | Body: `{ "message": "分析贵州茅台 600519" }` |

**响应：** `Content-Type: text/event-stream`

SSE 事件类型：

| event | data 示例 | 时机 |
|-------|-----------|------|
| `progress` | `{"step":"fundamental","label":"基本面分析中..."}` | 各 Agent 开始 |
| `message` | `{"role":"assistant","content":"...","type":"report"}` | 分析/追问完成 |
| `done` | `{"session_id":"...","report_path":"..."}` | 本轮结束 |
| `error` | `{"message":"..."}` | 异常 |

**Phase 1 同步模型：** 客户端 POST 后保持连接直到分析完成（约 3–8 分钟）。小团队内网可接受；Phase 3 再拆后台 Job。

### 4.3 报告

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/sessions/{id}/report` | 返回最新 `final_report` Markdown |

### 4.4 CORS

开发阶段允许 `http://localhost:3000`；生产本机部署同源代理，无需额外 CORS。

---

## 5. 后端改造点（最小侵入）

### 5.1 `run_session.py`

增加可选进度回调，替代/补充 `print()`：

```python
ProgressCallback = Callable[[str, str], None]  # (step_key, label)

async def process_turn(
    app,
    session: SessionContext,
    user_query: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> AgentState | None:
    ...
```

### 5.2 `workflow.py` / Agent 节点

**方案（推荐）：** 在 `analysis_service.py` 层包装，不修改 LangGraph 图结构。

`run_full_workflow` 改为分步 invoke 或监听节点：

```python
STEPS = [
    ("fundamental_analyst", "基本面分析"),
    ("technical_analyst", "技术面分析"),
    ("value_analyst", "估值分析"),
    ("news_analyst", "新闻分析"),
    ("summarizer", "生成报告"),
]
```

Phase 1 实现：**手动串行调用各 agent 函数**（与 workflow 边一致），每步前 emit `progress`。LangGraph `app.ainvoke` 保留给 CLI 使用，Web 走 `run_full_workflow_with_progress()`。

### 5.3 助手消息摘要策略

| 类型 | 存入 `chat_messages.content` | 存入 `analysis_snapshots` |
|------|------------------------------|---------------------------|
| 完整分析 | 「✅ 已完成 {公司} 完整分析，共 N 字」 | 完整 `final_report` + 四份子分析 |
| 追问 | 完整追问回答（通常较短） | 更新 `follow_up_reply`，保留原报告 |

---

## 6. 前端设计

### 6.1 页面布局

```
┌────────────────────────────────────────────────────────┐
│  🏦 金融分析智能体                          [+ 新对话]  │
├──────────────┬─────────────────────────────────────────┤
│ 会话列表      │  聊天区域                                │
│              │  ┌─────────────────────────────────────┐ │
│ · 贵州茅台    │  │ 👤 分析贵州茅台 600519               │ │
│ · 比亚迪追问  │  │ 🤖 [Markdown 报告渲染]               │ │
│ · 新对话      │  │ 👤 估值偏贵吗                        │ │
│              │  │ 🤖 [追问回答]                        │ │
│              │  └─────────────────────────────────────┘ │
│              │  [进度条: 基本面 ✓ 技术面 ● 估值 ○ ...]   │
│              │  ┌─────────────────────────────────────┐ │
│              │  │ 输入分析需求或追问...          [发送] │ │
│              │  └─────────────────────────────────────┘ │
└──────────────┴─────────────────────────────────────────┘
```

### 6.2 技术选型

| 项 | 选择 | 理由 |
|----|------|------|
| 框架 | Next.js 15 (App Router) | React 生态、SSR 可选、部署简单 |
| 样式 | Tailwind CSS | 快速出 UI |
| Markdown | `react-markdown` + `remark-gfm` | 报告表格渲染 |
| SSE 客户端 | 原生 `EventSource` 或 `fetch` + ReadableStream | POST SSE 用 fetch |
| 状态 | React `useState` + `useEffect` | Phase 1 无需 Redux |

### 6.3 关键交互

1. 打开 `/chat` → 若无会话则自动 `POST /sessions`
2. 发送消息 → `POST /sessions/{id}/chat`，监听 SSE `progress` 更新步骤条
3. 收到 `message` 事件 → 追加到消息列表，Markdown 渲染
4. 分析进行中禁用输入框，显示「分析中，约需 3–5 分钟」
5. 切换会话 → 加载历史消息，清空进度条

---

## 7. 记忆分层（Web 版）

| 层级 | Phase 1 实现 | 存储 |
|------|-------------|------|
| 短期（对话） | 最近消息 + SSE 当前轮 | 内存 + `chat_messages` |
| 会话（分析快照） | 四份子分析 + final_report | `analysis_snapshots.state_json` |
| 长期 | **不做** | Phase 4 |

与 CLI 改进一致：**对话历史不存完整报告正文**，追问依赖 `analysis_snapshots`。

---

## 8. 错误处理

| 场景 | 行为 |
|------|------|
| LLM API 失败 | SSE `error` 事件，消息列表显示错误卡片 |
| MCP / Baostock 失败 | 沿用 Agent 现有 error 字段，汇总 Agent 标注部分失败 |
| 分析超时（>15min） | 前端提示重试；后端 uvicorn timeout 设为 900s |
| 会话不存在 | HTTP 404 |
| 并发两路分析 | Phase 1 **全局锁**：同时只允许 1 个完整分析（MCP 限制） |

---

## 9. 启动与配置

### 9.1 环境变量

沿用现有 `.env`（LLM API、Baostock），新增：

```env
# api/config.py 读取
DATABASE_URL=sqlite:///./data/app.db
REPORTS_DIR=./data/reports
API_HOST=0.0.0.0
API_PORT=8000
```

### 9.2 `scripts/start.ps1`

```powershell
# 1. 检查 conda env agent
# 2. 初始化 data/ 目录
# 3. 启动 uvicorn（后台 Job）
# 4. 启动 next dev
# 5. 打开浏览器 http://localhost:3000
```

### 9.3 依赖

**Python（追加到 requirements.txt）：**

```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
sqlalchemy>=2.0.0
aiosqlite>=0.20.0
sse-starlette>=2.0.0
```

**Node（web/package.json）：**

```
next, react, react-dom, tailwindcss, react-markdown, remark-gfm
```

---

## 10. Phase 2 预留（注册登录，本文档不实现）

| 变更 | 说明 |
|------|------|
| `users` 表 | id, email, password_hash, created_at |
| `chat_sessions.user_id` | 外键，所有查询加 `WHERE user_id = ?` |
| `/auth/register`, `/auth/login` | JWT HttpOnly Cookie |
| 前端 `/login`, `/register` | 路由守卫 |
| 数据迁移 | 现有无 user_id 会话归属到首个注册用户或丢弃 |

---

## 11. 测试计划

| 项 | 验证方式 |
|----|---------|
| 创建会话 | API + UI 手动 |
| 完整分析 | 「分析贵州茅台 600519」→ 进度 5 步 → Markdown 报告 |
| 追问 | 「估值偏贵吗」→ 秒级响应，不调 MCP |
| 会话持久化 | 重启后端 → 打开旧会话 → 可继续追问 |
| 新股票 | 「重新分析比亚迪 002594」→ 触发完整分析 |
| 并发锁 | 两 Tab 同时分析 → 第二个排队或提示忙碌 |

---

## 12. 里程碑

| 阶段 | 交付物 | 预估 |
|------|--------|------|
| M1 | FastAPI 骨架 + SQLite + Session CRUD | 2 天 |
| M2 | `analysis_service` + SSE + 进度 | 2 天 |
| M3 | Next.js 聊天 UI + Markdown | 2 天 |
| M4 | 联调 + start.ps1 + 文档 | 1 天 |

**合计约 1 周**（单人开发）

---

## 13. 决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 部署 | 本机脚本，无 Docker | 用户明确不需要 Docker |
| Phase 1 账号 | 无 | A1：先验证 UI 与 Agent 集成 |
| 数据库 | SQLite | 零安装，小团队够用 |
| 前后端 | FastAPI + Next.js | 最大化复用 Python Agent 代码 |
| 长任务 | SSE 同步 | Phase 1 简单；小团队可接受 |
| MCP 并发 | 全局单任务锁 | 与现有串行 workflow 一致 |

---

## 14. 待用户确认

- [ ] 整体架构与目录结构
- [ ] Phase 1 API / 数据模型
- [ ] 前端布局与交互
- [ ] 确认后开始编写实现计划（writing-plans）
