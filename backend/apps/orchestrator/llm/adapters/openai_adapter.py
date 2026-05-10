from __future__ import annotations

import json
from typing import Any

import httpx

from backend.apps.orchestrator.llm.adapters.openai_compatible_client import OpenAICompatibleClient
from backend.apps.orchestrator.llm.base_adapter import BaseLLMAdapter


class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self) -> None:
        self.client = OpenAICompatibleClient(base_url_envs=["MODEL_LLM_BASE_URL", "OPENAI_LLM_BASE_URL", "LLM_BASE_URL"])

    async def generate_json(self, *, system_prompt: str, user_prompt: str, model: str, temperature: float = 0.0) -> dict[str, Any]:
        responses_payload = {
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
            ],
            "text": {"format": {"type": "json_object"}},
            "temperature": temperature,
        }
        try:
            data = await self.client.post("/responses", responses_payload)
            out = self._parse_responses(data)
            if out is not None:
                return out
        except (httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectTimeout, json.JSONDecodeError):
            pass

        chat_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        data = await self.client.post("/chat/completions", chat_payload)
        return self._parse_chat(data)

    @staticmethod
    def _parse_responses(data: dict[str, Any]) -> dict[str, Any] | None:
        output_text = data.get("output_text")
        if output_text:
            return json.loads(output_text)
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    return json.loads(content["text"])
        return None

    @staticmethod
    def _parse_chat(data: dict[str, Any]) -> dict[str, Any]:
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("no choices")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError("empty content")
        return json.loads(content)
