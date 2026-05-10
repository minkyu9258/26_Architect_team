from __future__ import annotations

from abc import ABC, abstractmethod

from backend.platform.shared.schemas import AgentResult, AgentTask


class BaseAgentProvider(ABC):
    @abstractmethod
    async def execute(self, session_id: str, message: str, task: AgentTask) -> AgentResult:
        raise NotImplementedError
