"""
LangGraph ReAct Agent + 可执行 Pandas 代码工具；流式事件在 main 中消费。
"""
from __future__ import annotations

import contextvars
import json
import threading
from typing import Annotated, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from config import settings
from sandbox import execute_in_sandbox
from session_context import current_session_id

_current_data_path: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_data_path", default=None
)
_pending_figures: dict[str, list[str]] = {}
_pending_figures_lock = threading.Lock()


def set_analysis_data_path(path: str | None) -> contextvars.Token:
    return _current_data_path.set(path)


def reset_analysis_data_path(token: contextvars.Token) -> None:
    _current_data_path.reset(token)


def pop_pending_figures_for_thread(thread_id: str) -> list[str]:
    with _pending_figures_lock:
        return _pending_figures.pop(thread_id, [])


SYSTEM_PROMPT = """你是专业数据分析师助手。用户已上传表格文件，在沙箱中已加载为变量 `df`（pandas DataFrame）。

沙箱中已预加载以下变量，可直接使用，**不要写 import 语句**：
- `pd` (pandas)、`np` (numpy)、`sns` (seaborn)、`plt` (matplotlib.pyplot)
- `df` (用户上传的 DataFrame)、`DATA_PATH` (文件路径字符串)

规则：
1. 第一次收到用户消息时，消息里会附带【当前数据概况】，包含列名、类型和样本。**务必根据真实列名编写代码，不要猜测列名**。
2. 先简要说明分析思路，再调用工具 `execute_analysis_code` 运行代码；可多次调用。
3. **重要**：代码中直接使用 pd、np、plt、sns、df，不要写 import 语句。禁止使用 IPython、display()、Jupyter 相关的任何方法。输出数据请用 print()。
4. 代码中禁止访问网络、禁止读写磁盘（除已提供的 df）、禁止使用 os/subprocess/open 等。
5. **每次分析必须同时生成图表**，不能只输出文字统计。把统计代码和绑图代码写在同一个 execute_analysis_code 调用里。

6. **维度筛选规则（非常重要）**：
   - 只对唯一值 ≤ 15 个的分类列做图表，超过 15 个唯一值的列（如"问题现象描述"、"责任人"等长文本或高基数列）**跳过，不要出图**
   - 如果确实需要分析高基数列，只取 Top 10 展示

7. **图表类型选择（不要全用柱状图）**：
   - 分类 ≤ 5 个：用**饼图**（plt.pie），显示百分比标签
   - 分类 6~15 个：用**水平柱状图**（plt.barh），避免 X 轴文字拥挤
   - 时间趋势数据：用**折线图**（plt.plot）
   - 两个分类交叉对比：用 seaborn **堆叠柱状图**或**热力图**（sns.heatmap）
   - 数值分布：用**箱线图**（plt.boxplot）或**直方图**（plt.hist）

8. 图表规范：
   - 中文字体已全局配置好，不需要再设置 rcParams
   - 柱状图/水平柱状图上标注数值
   - 始终调用 `plt.tight_layout()` 防止标签被裁切
   - 每张图的大小用 `figsize=(10, 6)` 以上
   - 多个维度时用 `plt.subplot()` 画在一张大图里，子图之间留够间距

9. 如果用户只说"帮我分析"而没有指定具体维度，应该：
   - 自动识别数据中唯一值 ≤ 15 个的分类列
   - 对每个关键维度做频次统计，根据上面的规则选择合适的图表类型
   - 最后用 Markdown 格式分点总结核心发现和建议

10. 工具返回 stdout/stderr 后，用结构清晰的 Markdown 总结：
    - 用 `###` 分节标题
    - 用表格或有序列表呈现关键数据
    - 给出 **核心发现** 和 **改进建议**

11. 回答使用简体中文。
12. 生成代码时，代码必须是可直接执行的多行 Python 代码，不要把所有代码压成一行。"""


@tool
def execute_analysis_code(code: str) -> str:
    """在隔离子进程中执行 Python 数据分析代码。已预置 df（DataFrame）、pd、np、sns、plt、DATA_PATH。"""
    path = _current_data_path.get()
    if not path:
        return "错误：当前会话没有关联的数据文件，请让用户重新上传。"
    result = execute_in_sandbox(code, path)
    figures = result.get("figures") or []
    if figures:
        session_id = current_session_id.get()
        if session_id:
            with _pending_figures_lock:
                _pending_figures[session_id] = list(figures)
    # 不把大图塞进模型上下文；图表由 SSE 单独推送
    slim = {k: v for k, v in result.items() if k != "figures"}
    slim["figure_count"] = len(result.get("figures") or [])
    return json.dumps(slim, ensure_ascii=False)


def _build_llm() -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": 0.2,
        "streaming": True,
    }
    if settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    if "qwen3" in settings.llm_model.lower():
        kwargs["extra_body"] = {"enable_thinking": False}
    return ChatOpenAI(**kwargs)


_llm = _build_llm()

# 单例图；数据路径按请求通过 ContextVar 注入
_agent_graph = create_react_agent(
    _llm,
    tools=[execute_analysis_code],
    prompt=SYSTEM_PROMPT,
)


def get_agent_graph():
    return _agent_graph


def build_initial_messages(user_text: str) -> dict[str, list[BaseMessage]]:
    return {"messages": [HumanMessage(content=user_text)]}
