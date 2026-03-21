"""
在独立子进程中运行；通过 stdin 接收 JSON，stdout 输出 JSON 结果。
禁止网络与文件写（除内存缓冲）；仅暴露白名单模块与受限 builtins。
"""
from __future__ import annotations

import base64
import io
import json
import sys
import traceback
from typing import Any

# 必须在 import pyplot 之前
import matplotlib

matplotlib.use("Agg")

_MAX_CODE_CHARS = 80_000
_MAX_OUTPUT_CHARS = 200_000


def _limited_builtins() -> dict[str, Any]:
    bi: dict[str, Any] = {}
    safe = (
        "abs",
        "all",
        "any",
        "bin",
        "bool",
        "chr",
        "dict",
        "divmod",
        "enumerate",
        "filter",
        "float",
        "format",
        "frozenset",
        "hash",
        "hex",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "oct",
        "ord",
        "pow",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
        "zip",
    )
    import builtins

    for name in safe:
        bi[name] = getattr(builtins, name)
    bi["print"] = print
    bi["True"] = True
    bi["False"] = False
    bi["None"] = None
    return bi


def _load_dataframe(path: str):
    import pandas as pd

    lower = path.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(path)
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(path)
    raise ValueError("仅支持 .csv 或 Excel（.xlsx/.xlsm/.xls）")


def _collect_figures_b64() -> list[str]:
    import matplotlib.pyplot as plt

    out: list[str] = []
    for num in plt.get_fignums():
        fig = plt.figure(num)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=120)
        out.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    plt.close("all")
    return out


def run_job(payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("code") or ""
    data_path = payload.get("data_path") or ""
    if len(code) > _MAX_CODE_CHARS:
        return {"ok": False, "error": "代码过长", "stdout": "", "stderr": "", "figures": []}
    if not data_path:
        return {"ok": False, "error": "缺少 data_path", "stdout": "", "stderr": "", "figures": []}

    import numpy as np
    import pandas as pd
    import seaborn as sns

    import matplotlib.pyplot as plt

    df = _load_dataframe(data_path)

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf

    g: dict[str, Any] = {
        "__builtins__": _limited_builtins(),
        "pd": pd,
        "np": np,
        "sns": sns,
        "plt": plt,
        "df": df,
        "DATA_PATH": data_path,
    }

    try:
        compiled = compile(code, "<analysis>", "exec")
        exec(compiled, g, g)
        figures = _collect_figures_b64()
        stdout_text = stdout_buf.getvalue()
        stderr_text = stderr_buf.getvalue()
        if len(stdout_text) > _MAX_OUTPUT_CHARS:
            stdout_text = stdout_text[:_MAX_OUTPUT_CHARS] + "\n...[截断]"
        if len(stderr_text) > _MAX_OUTPUT_CHARS:
            stderr_text = stderr_text[:_MAX_OUTPUT_CHARS] + "\n...[截断]"
        return {
            "ok": True,
            "error": "",
            "stdout": stdout_text,
            "stderr": stderr_text,
            "figures": figures,
        }
    except BaseException as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "figures": _collect_figures_b64(),
        }
    finally:
        sys.stdout = old_out
        sys.stderr = old_err


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"JSON 无效: {e}", "stdout": "", "stderr": "", "figures": []}))
        return
    result = run_job(payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
