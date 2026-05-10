from __future__ import annotations

import os

class EmbeddingAdapter:
    async def embed(self, text: str) -> list[float]:
        # Return a mock vector of length EMBEDDING_DIM
        dim = int(os.getenv("EMBEDDING_DIM", "1024"))
        return [0.1] * dim

def create_embedding_adapter() -> EmbeddingAdapter:
    return EmbeddingAdapter()
