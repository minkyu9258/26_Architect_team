from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from redis.asyncio import Redis

from backend.apps.orchestrator.intent.semantic.embedding_adapter import create_embedding_adapter
from backend.apps.orchestrator.rag.vector_repo import RagVectorRepo


class RagService:
    def __init__(self) -> None:
        self.repo = RagVectorRepo()
        self.embedder = create_embedding_adapter()
        self._emb_cache: dict[str, list[float]] = {}
        self._redis: Redis | None = None
        redis_url = os.getenv("REDIS_URL", "").strip()
        self._cache_ttl = max(30, int(os.getenv("RAG_CACHE_TTL_SEC", "600")))
        if redis_url:
            try:
                self._redis = Redis.from_url(redis_url, decode_responses=True)
            except Exception:
                self._redis = None

    async def _cache_get_vec(self, key: str) -> list[float] | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(f"rag:emb:{key}")
        except Exception:
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [float(v) for v in data]
        except Exception:
            return None
        return None

    async def _cache_set_vec(self, key: str, vec: list[float]) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.setex(f"rag:emb:{key}", self._cache_ttl, json.dumps(vec))
        except Exception:
            return

    async def _embed(self, text: str) -> list[float]:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cached = self._emb_cache.get(key)
        if cached is not None:
            return cached
        redis_cached = await self._cache_get_vec(key)
        if redis_cached is not None:
            self._emb_cache[key] = redis_cached
            return redis_cached
        vec = await self.embedder.embed(text)
        self._emb_cache[key] = vec
        await self._cache_set_vec(key, vec)
        return vec

    async def ingest(self, *, doc_key: str, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        vec = await self._embed(content)
        self.repo.upsert_document(doc_key=doc_key, content=content, embedding=vec, metadata=metadata)
        return {"doc_key": doc_key, "dim": len(vec), "stored": True}

    async def search(self, *, query: str, k: int = 4, min_score: float = 0.35) -> list[dict[str, Any]]:
        vec = await self._embed(query)
        hits = self.repo.search(embedding=vec, k=k)
        return [h for h in hits if float(h.get("score", 0.0)) >= min_score]
