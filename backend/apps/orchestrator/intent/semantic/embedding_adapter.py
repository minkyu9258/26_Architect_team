from __future__ import annotations

import os

from backend.apps.orchestrator.llm.adapters.openai_compatible_client import OpenAICompatibleClient

class EmbeddingAdapter:
    def __init__(self) -> None:
        self.client = OpenAICompatibleClient(
            base_url_envs=["EMBED_BASE_URL", "OPENAI_BASE_URL"],
            api_key_envs=["EMBED_API_KEY", "OPENAI_API_KEY"]
        )
        self.model = os.getenv("EMBED_MODEL_NAME", "text-embedding-3-small")
        self.dim = int(os.getenv("EMBEDDING_DIM", "1536"))

    async def embed(self, text: str) -> list[float]:
        payload = {
            "input": text,
            "model": self.model
        }
        
        # OpenAI's text-embedding-3 and Gemini's gemini-embedding-2 models support the dimensions parameter
        if "text-embedding-3" in self.model or "gemini-embedding" in self.model:
            payload["dimensions"] = self.dim
            
        data = await self.client.post("/embeddings", payload)
        
        try:
            return data["data"][0]["embedding"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Failed to parse embedding response: {data}") from e

def create_embedding_adapter() -> EmbeddingAdapter:
    return EmbeddingAdapter()
