from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx


class OpenAICompatibleClient:
    def __init__(self, *, base_url_envs: list[str] | None = None) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "") or os.getenv("DGA_LLM_API_KEY", "")
        base_url = ""
        for key in base_url_envs or []:
            value = os.getenv(key, "")
            if value:
                base_url = value
                break
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "") or os.getenv("LLM_BASE_URL", "") or "https://api.openai.com/v1"
        self.timeout = float(os.getenv("LLM_HTTP_TIMEOUT", "120"))
        self.max_retries = int(os.getenv("LLM_HTTP_MAX_RETRIES", "2"))
        self.trust_env = os.getenv("HTTPX_TRUST_ENV", "true").lower() in {"1", "true", "yes", "on"}
        self.bypass_proxy = os.getenv("LLM_BYPASS_PROXY", "false").lower() in {"1", "true", "yes", "on"}

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        timeout = httpx.Timeout(connect=10.0, read=self.timeout, write=30.0, pool=30.0)
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout, trust_env=(False if self.bypass_proxy else self.trust_env)) as client:
                    res = await client.post(f"{self.base_url}{path}", headers=self._headers(), json=payload)
                    res.raise_for_status()
                    return res.json()
            except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(0.6 * (attempt + 1))
        if last_exc:
            raise last_exc
        raise RuntimeError("request failed")
