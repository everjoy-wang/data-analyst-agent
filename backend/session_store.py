from __future__ import annotations

from pathlib import Path


class SessionState:
    def __init__(self, file_path: Path, data_summary: str = "") -> None:
        self.file_path = file_path
        self.needs_system = True
        self.data_summary = data_summary


sessions: dict[str, SessionState] = {}
