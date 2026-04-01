# 智能数据分析师（Data Analyst Agent）

用户上传 **CSV / Excel**，后端使用 **FastAPI + LangGraph（LangChain）** 驱动 ReAct Agent，通过 **子进程沙箱** 执行模型生成的 **Pandas / Matplotlib** 代码；**SSE 流式**推送思考与代码片段；前端 **React** 渲染 **Markdown**、**代码高亮** 与 **Base64 PNG 图表**。

## 架构说明

| 组件 | 说明 |
|------|------|
| `backend/sandbox_runner.py` | 独立进程内 `exec`，受限 `__builtins__`，仅暴露 `pd/np/sns/plt/df` 等 |
| `backend/sandbox.py` | `subprocess.run` + 超时，与主进程隔离 |
| `backend/agent_core.py` | `create_react_agent` + 异步工具 `execute_analysis_code` |
| `backend/main.py` | 上传、`/api/chat/stream` SSE、`MemorySaver` 多轮对话 |
| `frontend` | Vite + React，`react-markdown` + `react-syntax-highlighter` |

**安全提示**：子进程沙箱可降低误用风险，但无法等同于完整容器隔离；勿将本服务暴露到公网且不审查模型输出。

## 环境准备

1. **Python 3.11+**（推荐）
2. **Node.js 18+**
3. **OpenAI API Key**（或兼容 OpenAI 协议的 Base URL）

复制后端环境变量：

```bash
cd G:\xiangmu\data-analyst-agent\backend
copy .env.example .env
# 编辑 .env，填写 OPENAI_API_KEY
```

安装依赖：

```bash
pip install -r requirements.txt
cd ..\frontend
npm install --include=dev
```

说明：若环境变量 `NODE_ENV=production`，`npm install` 会跳过开发依赖，导致缺少 `vite` / `typescript`。请使用 `npm install --include=dev`，或在安装前取消该变量。

若 `pip` 因网络/SSL 失败，请配置镜像或代理后重试。

## 启动

**终端 1 — 后端**

```bash
cd G:\xiangmu\data-analyst-agent\backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**终端 2 — 前端**

```bash
cd G:\xiangmu\data-analyst-agent\frontend
npm run dev
```

浏览器打开 `http://localhost:5173`。前端通过 Vite 代理访问 `http://127.0.0.1:8000/api`。

健康检查：`GET http://127.0.0.1:8000/api/health`（`llm_configured` 表示是否检测到 API Key）。

## 使用方式

1. 点击 **选择文件**，上传 `.csv` 或 `.xlsx` / `.xls` / `.xlsm`。
2. 在输入框描述分析需求（例如：「按类别汇总销售额并画柱状图」）。
3. 流式区域会依次出现：**模型输出**、**生成的 Python 代码**、**工具 JSON 返回摘要**、**图表 PNG**。

## SSE 事件类型（前端可扩展）

- `start`：会话开始
- `llm_token`：模型增量文本
- `tool_code`：即将执行的代码
- `tool_result`：工具返回（截断）
- `figures`：`images` 为 Base64 PNG 数组
- `done`：本轮结束
- `error`：异常信息

## 目录结构

```
data-analyst-agent/
  backend/
    main.py
    agent_core.py
    sandbox.py
    sandbox_runner.py
    session_store.py
    session_context.py
    config.py
    requirements.txt
    .env.example
  frontend/
    src/App.tsx
    package.json
    vite.config.ts
  README.md
```


