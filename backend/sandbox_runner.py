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


def _setup_chinese_font() -> None:
    """在 Windows 上自动查找可用的中文字体并设置给 matplotlib。"""
    import os

    candidates = ["Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "FangSong"]

    font_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")
    font_files = {
        "Microsoft YaHei": "msyh.ttc",
        "SimHei": "simhei.ttf",
        "SimSun": "simsun.ttc",
        "KaiTi": "simkai.ttf",
        "FangSong": "simfang.ttf",
    }

    for name in candidates:
        font_file = font_files.get(name, "")
        if font_file and os.path.isfile(os.path.join(font_dir, font_file)):
            matplotlib.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return

    matplotlib.rcParams["axes.unicode_minus"] = False


_setup_chinese_font()

_MAX_CODE_CHARS = 80_000
_MAX_OUTPUT_CHARS = 200_000


def _sanitize_code(code: str) -> str:
    """修复小模型常见的代码格式问题。"""
    code = code.strip()

    if code.startswith("```"):
        lines = code.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        code = "\n".join(lines)

    real_newlines = code.count("\n")
    escaped_newlines = code.count("\\n")
    if escaped_newlines > 0 and real_newlines <= 2:
        code = code.replace("\\n", "\n")
        code = code.replace("\\'", "'")
        code = code.replace('\\"', '"')
        code = code.replace("\\t", "\t")

    cleaned_lines = []
    for line in code.split("\n"):
        if line.strip() == "plt.show()":
            continue
        cleaned_lines.append(line)
    code = "\n".join(cleaned_lines)

    return code


_ALLOWED_IMPORTS = frozenset({
    "pandas", "numpy", "matplotlib", "matplotlib.pyplot", "seaborn",
    "math", "statistics", "collections", "itertools", "functools",
    "datetime", "re", "json", "csv", "decimal", "fractions",
    "textwrap", "string", "operator", "copy",
})

_BLOCKED_IMPORTS = frozenset({
    "IPython", "ipython", "jupyter", "notebook",
    "os", "sys", "subprocess", "shutil", "socket",
    "requests", "urllib", "http",
})


def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    root = name.split(".")[0]
    if root in _BLOCKED_IMPORTS:
        raise ImportError(f"禁止导入模块: {name}")
    if root not in _ALLOWED_IMPORTS and name not in _ALLOWED_IMPORTS:
        raise ImportError(f"不允许导入模块: {name}")
    return __builtins__["__import__"](name, *args, **kwargs) if isinstance(__builtins__, dict) else __import__(name, *args, **kwargs)


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
    bi["__import__"] = _safe_import
    bi["print"] = print
    bi["True"] = True
    bi["False"] = False
    bi["None"] = None
    return bi


def _find_header_row(path: str, ext: str) -> int | None:
    """检测真正的表头行：如果前几行大部分列是 Unnamed，说明需要跳过标题行。"""
    import pandas as pd

    try:
        if ext == ".csv":
            probe = pd.read_csv(path, nrows=5, header=None)
        else:
            probe = pd.read_excel(path, nrows=5, header=None)
    except Exception:
        return None

    for i in range(min(5, len(probe))):
        row = probe.iloc[i]
        non_null = row.dropna()
        if len(non_null) < 2:
            continue
        unique_vals = set(str(v).strip() for v in non_null)
        if len(unique_vals) >= 3 and not any(v.startswith("Unnamed") for v in unique_vals):
            return i
    return None


def _load_dataframe(path: str):
    import pandas as pd

    lower = path.lower()
    ext = ".csv" if lower.endswith(".csv") else ".xlsx"
    if not (lower.endswith(".csv") or lower.endswith((".xlsx", ".xlsm", ".xls"))):
        raise ValueError("仅支持 .csv 或 Excel（.xlsx/.xlsm/.xls）")

    header_row = _find_header_row(path, ext)
    if lower.endswith(".csv"):
        return pd.read_csv(path, header=header_row)
    return pd.read_excel(path, header=header_row)


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

    code = _sanitize_code(code)

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
