from __future__ import annotations

import os

from backend.apps.orchestrator.llm.adapters.mock_adapter import MockAdapter
from backend.apps.orchestrator.llm.adapters.openai_adapter import OpenAIAdapter
from backend.apps.orchestrator.llm.base_adapter import BaseLLMAdapter


def create_llm_adapter() -> BaseLLMAdapter:
    provider = (os.getenv("LLM_PROVIDER", "") or os.getenv("PROVIDER", "mock")).lower()
    if provider in {"openai", "openai_compat", "openai-compatible"}:
        return OpenAIAdapter()
    return MockAdapter()
