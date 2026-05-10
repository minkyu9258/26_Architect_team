from __future__ import annotations

import httpx

from backend.apps.orchestrator.agent_provider.base import BaseAgentProvider
from backend.apps.orchestrator.config import AGENT_HTTP_TIMEOUT, AGENT_HTTP_TRUST_ENV
from backend.apps.orchestrator.core.registry import get_agent_registry
from backend.platform.shared.schemas import AgentResult, AgentTask


class HttpAgentProvider(BaseAgentProvider):
    async def execute(self, session_id: str, message: str, task: AgentTask) -> AgentResult:
        registry = get_agent_registry()
        base_url = registry.get(task.agent_id)
        if not base_url:
            return AgentResult(agent_id=task.agent_id, capability=task.capability, success=False, error="unknown agent")

        payload = {
            "session_id": session_id,
            "message": message,
            "task": task.model_dump(),
        }

        try:
            async with httpx.AsyncClient(timeout=AGENT_HTTP_TIMEOUT, trust_env=AGENT_HTTP_TRUST_ENV) as client:
                res = await client.post(f"{base_url}/execute", json=payload)
                res.raise_for_status()
                data = res.json()
            success = bool(data.get("success", True))
            output = data.get("output", {}) if isinstance(data.get("output"), dict) else {}
            error = data.get("error")
            return AgentResult(agent_id=task.agent_id, capability=task.capability, success=success, output=output, error=error)
        except Exception as exc:
            return AgentResult(agent_id=task.agent_id, capability=task.capability, success=False, error=str(exc))
