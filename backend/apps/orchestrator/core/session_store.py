from __future__ import annotations

from backend.platform.shared.schemas import SessionState


class SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState | None:
        return self._data.get(session_id)

    def upsert(self, state: SessionState) -> None:
        self._data[state.session_id] = state
