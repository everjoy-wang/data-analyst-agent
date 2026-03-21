"""在单次流式请求内标识当前会话，供异步 Tool 读取（避免线程池丢失上下文）。"""
from __future__ import annotations

import contextvars

current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_session_id", default=None
)
