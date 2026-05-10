from __future__ import annotations

from typing import Any

from backend.apps.orchestrator.config import LLM_ROLE_MODELS
from backend.apps.orchestrator.llm.factory import create_llm_adapter


class LLMGateway:
    def __init__(self) -> None:
        self.adapter = create_llm_adapter()

    async def generate_json(self, *, role: str, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> dict[str, Any]:
        model = LLM_ROLE_MODELS.get(role) or LLM_ROLE_MODELS["intent_fallback"]
        return await self.adapter.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
        )
