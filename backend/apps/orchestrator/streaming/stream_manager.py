from __future__ import annotations


class StreamManager:
    def __init__(self) -> None:
        self._events: dict[str, list[dict]] = {}

    def append(self, session_id: str, event: dict) -> None:
        self._events.setdefault(session_id, []).append(event)

    def get(self, session_id: str) -> list[dict]:
        return self._events.get(session_id, [])
