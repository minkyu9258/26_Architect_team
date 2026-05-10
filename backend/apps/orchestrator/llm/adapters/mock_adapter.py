from __future__ import annotations

from typing import Any

from backend.apps.orchestrator.llm.base_adapter import BaseLLMAdapter


class MockAdapter(BaseLLMAdapter):
    async def generate_json(self, *, system_prompt: str, user_prompt: str, model: str, temperature: float = 0.0) -> dict[str, Any]:
        _ = system_prompt, model, temperature
        return {
            "intent": "general",
            "confidence": 0.5,
            "entities": {},
            "reason": "mock",
            "answer": f"[mock] {user_prompt[:120]}",
            "plan_title": "mock plan",
            "steps": [],
            "assumptions": [],
            "missing_inputs": [],
        }
