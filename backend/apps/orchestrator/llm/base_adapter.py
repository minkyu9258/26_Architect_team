from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMAdapter(ABC):
    @abstractmethod
    async def generate_json(self, *, system_prompt: str, user_prompt: str, model: str, temperature: float = 0.0) -> dict[str, Any]:
        raise NotImplementedError
