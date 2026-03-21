"""
在子进程中调用 sandbox_runner.py，实现与主进程隔离；超时后终止子进程。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_RUNNER = Path(__file__).resolve().parent / "sandbox_runner.py"
_DEFAULT_TIMEOUT_SEC = 90


def execute_in_sandbox(code: str, data_path: str, timeout_sec: float = _DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    payload = json.dumps({"code": code, "data_path": data_path}, ensure_ascii=False)
    cmd = [sys.executable, str(_RUNNER)]
    try:
        proc = subprocess.run(
            cmd,
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            cwd=str(_RUNNER.parent),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"执行超时（>{timeout_sec}s），已终止子进程。",
            "stdout": "",
            "stderr": "",
            "figures": [],
        }

    if proc.returncode != 0 and not proc.stdout.strip():
        return {
            "ok": False,
            "error": f"子进程异常退出 code={proc.returncode}\n{proc.stderr}",
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "figures": [],
        }

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": f"无法解析子进程输出: {proc.stdout[:500]}\nstderr: {proc.stderr[:500]}",
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "figures": [],
        }
