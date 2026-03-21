"""
LangGraph ReAct Agent + 可执行 Pandas 代码工具；流式事件在 main 中消费。
"""
from __future__ import annotations

import contextvars
import json
from typing import Annotated, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from config import settings
from sandbox import execute_in_sandbox

_current_data_path: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_data_path", default=None
)


def set_analysis_data_path(path: str | None) -> contextvars.Token:
    return _current_data_path.set(path)


def reset_analysis_data_path(token: contextvars.Token) -> None:
    _current_data_path.reset(token)


SYSTEM_PROMPT = """你是专业数据分析师助手。用户已上传表格文件，在沙箱中已加载为变量 `df`（pandas DataFrame）。
你可用的库与变量：pd, np, sns, plt, df, DATA_PATH（字符串路径）。matplotlib 使用非交互后端，作图后务必 plt.figure() 或正常绘图；执行结束后系统会自动保存所有图像。

规则：
1. 先简要说明分析思路，再调用工具 `execute_analysis_code` 运行代码；可多次调用。
2. 代码中禁止访问网络、禁止读写磁盘（除已提供的 df）、禁止使用 os/subprocess/open 等。
3. 需要图表时用 matplotlib/seaborn，图会单独展示给用户。
4. 工具返回 stdout/stderr 后，用自然语言（Markdown）总结洞察、异常值、趋势与建议。
5. 回答使用简体中文。"""


@tool
def execute_analysis_code(code: str) -> str:
    """在隔离子进程中执行 Python 数据分析代码。已预置 df（DataFrame）、pd、np、sns、plt、DATA_PATH。"""
    path = _current_data_path.get()
    if not path:
        return "错误：当前会话没有关联的数据文件，请让用户重新上传。"
    result = execute_in_sandbox(code, path)
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
