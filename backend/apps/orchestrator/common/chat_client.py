from __future__ import annotations

from typing import Any

from backend.apps.orchestrator.llm_gateway.gateway import LLMGateway


class ChatClient:
    def __init__(self) -> None:
        self._gateway = LLMGateway()

    async def generate_json(self, *, role: str, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> dict[str, Any]:
        return await self._gateway.generate_json(
            role=role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
        )
