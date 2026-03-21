from __future__ import annotations

from pathlib import Path


class SessionState:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.needs_system = True


sessions: dict[str, SessionState] = {}
