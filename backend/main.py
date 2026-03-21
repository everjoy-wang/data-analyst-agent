from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agent_core import SYSTEM_PROMPT, get_agent_graph, pop_pending_figures_for_thread
from config import settings
from session_context import current_session_id
from session_store import SessionState, sessions

app = FastAPI(title="Data Analyst Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_ROOT = Path(__file__).resolve().parent / settings.upload_dir
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _extract_text_from_chunk(chunk: Any) -> str:
    if chunk is None:
        return ""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
        return "".join(parts)
    return ""


class ChatBody(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1, max_length=12000)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    name = file.filename or "data.csv"
    ext = Path(name).suffix.lower()
    if ext not in {".csv", ".xlsx", ".xlsm", ".xls"}:
        raise HTTPException(400, "仅支持 .csv 或 Excel（.xlsx/.xlsm/.xls）")

    sid = uuid.uuid4().hex
    session_dir = UPLOAD_ROOT / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    dest = session_dir / f"data{ext}"
    raw = await file.read()
    dest.write_bytes(raw)

    preview: dict[str, Any] = {}
    try:
        if ext == ".csv":
            df = pd.read_csv(dest, nrows=8)
        else:
            df = pd.read_excel(dest, nrows=8)
        preview = {
            "columns": list(df.columns.astype(str)),
            "row_count_hint": int(len(df)),
            "sample_rows": df.head(5).to_dict(orient="records"),
        }
    except Exception as e:
        preview = {"error": f"预览解析失败: {e}"}

    sessions[sid] = SessionState(dest.resolve())
    return {"session_id": sid, "filename": name, "preview": preview}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatBody) -> StreamingResponse:
    st = sessions.get(body.session_id)
    if not st:
        raise HTTPException(404, "会话不存在或已失效，请重新上传文件")

    graph = get_agent_graph()
    config: dict[str, Any] = {"configurable": {"thread_id": body.session_id}}

    if st.needs_system:
        messages: list[BaseMessage] = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=body.message),
        ]
        st.needs_system = False
    else:
        messages = [HumanMessage(content=body.message)]

    sid = body.session_id

    async def gen() -> AsyncIterator[str]:
        ctx_tok = current_session_id.set(sid)
        try:
            yield _sse({"type": "start", "session_id": sid})
            async for event in graph.astream_events(
                {"messages": messages},
                config=config,
                version="v2",
            ):
                et = event.get("event")
                data = event.get("data") or {}

                if et == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    text = _extract_text_from_chunk(chunk)
                    if text:
                        yield _sse({"type": "llm_token", "text": text})

                elif et == "on_tool_start":
                    name = event.get("name")
                    if name == "execute_analysis_code":
                        inp = data.get("input") or {}
                        code = inp.get("code") if isinstance(inp, dict) else None
                        if code is None and isinstance(inp, str):
                            code = inp
                        yield _sse(
                            {
                                "type": "tool_code",
                                "name": name,
                                "code": code or "",
                            }
                        )

                elif et == "on_tool_end":
                    name = event.get("name")
                    if name == "execute_analysis_code":
                        figs = pop_pending_figures_for_thread(sid)
                        if figs:
                            yield _sse({"type": "figures", "images": figs})
                        out = data.get("output")
                        out_s = getattr(out, "content", None) if out is not None else None
                        if out_s is None:
                            out_s = str(out) if out is not None else ""
                        yield _sse({"type": "tool_result", "text": str(out_s)[:8000]})

            yield _sse({"type": "done"})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
        finally:
            current_session_id.reset(ctx_tok)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm_configured": "yes" if settings.openai_api_key else "no"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
