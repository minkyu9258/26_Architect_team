
## N. 백엔드 핵심 파일 풀 템플릿 (추가)

## N.1 `backend/apps/orchestrator/llm/adapters/openai_compatible_client.py`
```python
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
```

## N.2 `backend/apps/orchestrator/llm/adapters/openai_adapter.py`
```python
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
```

## N.3 `backend/apps/orchestrator/core/agent_executor.py`
```python
from __future__ import annotations

import asyncio
import os
from typing import Any

from backend.apps.orchestrator.agent_provider.http_client import HttpAgentProvider
from backend.apps.orchestrator.common.chat_client import ChatClient
from backend.platform.shared.schemas import AgentResult, AgentTask

_agent_provider = HttpAgentProvider()
LLM_STAGE_TIMEOUT = float(os.getenv("LLM_STAGE_TIMEOUT", "6"))


async def run_task(session_id: str, message: str, task: AgentTask) -> AgentResult:
    return await _agent_provider.execute(session_id=session_id, message=message, task=task)


async def run_parallel(session_id: str, message: str, tasks: list[AgentTask]) -> list[AgentResult]:
    return await asyncio.gather(*(run_task(session_id, message, t) for t in tasks))


async def run_parallel_stream(session_id: str, message: str, tasks: list[AgentTask]):
    pending = [asyncio.create_task(run_task(session_id, message, t)) for t in tasks]
    for completed in asyncio.as_completed(pending):
        yield await completed


async def llm_fallback_intent(message: str) -> dict[str, Any]:
    client = ChatClient()
    system_prompt = (
        "You are an intent classifier for an IT admin multi-agent system. "
        "Return strict JSON only with keys: intent, confidence, entities, reason. "
        "intent must be one of [project_setup, infra_setup, mdm_ops, general]."
    )
    try:
        result = await asyncio.wait_for(
            client.generate_json(role="intent_fallback", system_prompt=system_prompt, user_prompt=message, temperature=0.0),
            timeout=LLM_STAGE_TIMEOUT,
        )
    except Exception:
        return {"intent": "general", "confidence": 0.5, "entities": {}, "reason": "llm_timeout_or_error", "raw_response": {}}
    return {
        "intent": str(result.get("intent", "general")),
        "confidence": float(result.get("confidence", 0.5)),
        "entities": result.get("entities", {}) if isinstance(result.get("entities"), dict) else {},
        "reason": str(result.get("reason", "")),
        "raw_response": result if isinstance(result, dict) else {},
    }


async def llm_fill_missing_entities(*, intent: str, message: str, entities: dict[str, str], missing: list[str]) -> dict[str, Any]:
    if not missing:
        return {"entities": entities, "inferred_entities": {}, "raw_response": {}, "called": False}
    client = ChatClient()
    system_prompt = "Extract only missing entities for the given intent. Return strict JSON object only. Allowed keys: project_name, repository_name, region."
    user_prompt = f"intent={intent}\ncurrent_entities={entities}\nmissing={missing}\nmessage={message}\nIf uncertain, return empty JSON {{}}."
    try:
        inferred = await asyncio.wait_for(
            client.generate_json(role="intent_fallback", system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.0),
            timeout=LLM_STAGE_TIMEOUT,
        )
    except Exception:
        inferred = {}
    merged = dict(entities)
    inferred_entities: dict[str, str] = {}
    if isinstance(inferred, dict):
        for key in ("project_name", "repository_name", "region"):
            value = inferred.get(key)
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()
                inferred_entities[key] = value.strip()
    return {"entities": merged, "inferred_entities": inferred_entities, "raw_response": inferred if isinstance(inferred, dict) else {}, "called": True}


async def llm_build_plan(*, message: str, intent: str, entities: dict[str, str], tasks: list[AgentTask]) -> dict[str, Any]:
    client = ChatClient()
    system_prompt = "You are a planning node for an IT multi-agent workflow. Return strict JSON with keys: plan_title, steps(array), assumptions(array), missing_inputs(array)."
    user_prompt = f"message={message}\nintent={intent}\nentities={entities}\ntasks={[t.model_dump() for t in tasks]}"
    try:
        return await asyncio.wait_for(
            client.generate_json(role="planner", system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.0),
            timeout=LLM_STAGE_TIMEOUT,
        )
    except Exception:
        return {
            "plan_title": f"{intent} execution plan",
            "steps": [f"Run {t.agent_id}:{t.capability}" for t in tasks],
            "assumptions": [],
            "missing_inputs": [],
        }


async def llm_chat_answer(message: str) -> dict[str, Any]:
    client = ChatClient()
    system_prompt = (
        "You are a concise helpful assistant for an enterprise AI orchestration console. "
        "Return strict JSON only with keys: answer, intent. "
        "intent should be one of [project_setup, infra_setup, mdm_ops, general]."
    )
    try:
        result = await asyncio.wait_for(
            client.generate_json(role="summary", system_prompt=system_prompt, user_prompt=message, temperature=0.2),
            timeout=LLM_STAGE_TIMEOUT,
        )
    except Exception:
        return {"answer": "질문을 이해했지만 현재 답변 생성에 실패했습니다. 다시 시도해 주세요.", "intent": "general"}
    answer = str(result.get("answer", "")).strip()
    if not answer:
        answer = "질문을 이해했지만 현재 답변 생성에 실패했습니다. 다시 시도해 주세요."
    return {"answer": answer, "intent": str(result.get("intent", "general"))}
```

## N.4 `backend/apps/orchestrator/rag/vector_repo.py`
```python
from __future__ import annotations

import json
import os
from typing import Any

import psycopg


class RagVectorRepo:
    def __init__(self) -> None:
        self.enabled = os.getenv("VECTOR_STORE_PROVIDER", "pgvector").lower() == "pgvector"
        self.dsn = os.getenv("VECTOR_DB_DSN", "postgresql://postgres:postgres@vector-db:5432/mdm")
        self.dim = int(os.getenv("EMBEDDING_DIM", "1024"))
        self._ready = False

    def _conn(self):
        return psycopg.connect(self.dsn)

    def ensure_schema(self) -> None:
        if not self.enabled or self._ready:
            return
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS rag_documents (
                  id BIGSERIAL PRIMARY KEY,
                  doc_key TEXT UNIQUE NOT NULL,
                  content TEXT NOT NULL,
                  metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                  embedding vector({self.dim}) NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            conn.commit()
        self._ready = True

    def upsert_document(self, *, doc_key: str, content: str, embedding: list[float], metadata: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self.ensure_schema()
        if len(embedding) != self.dim:
            raise ValueError(f"embedding dim mismatch: expected {self.dim}, got {len(embedding)}")
        vec_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rag_documents (doc_key, content, metadata, embedding)
                VALUES (%s, %s, %s::jsonb, %s::vector)
                ON CONFLICT (doc_key)
                DO UPDATE SET
                  content = EXCLUDED.content,
                  metadata = EXCLUDED.metadata,
                  embedding = EXCLUDED.embedding
                """,
                (doc_key, content, json.dumps(metadata or {}), vec_literal),
            )
            conn.commit()

    def search(self, *, embedding: list[float], k: int = 5) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self.ensure_schema()
        if len(embedding) != self.dim:
            return []
        vec_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT doc_key, content, metadata::text, 1 - (embedding <=> %s::vector) AS score
                FROM rag_documents
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_literal, vec_literal, k),
            )
            rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for doc_key, content, metadata_text, score in rows:
            out.append({
                "doc_key": doc_key,
                "content": content,
                "metadata": json.loads(metadata_text) if metadata_text else {},
                "score": float(score),
            })
        return out
```

## N.5 `backend/apps/orchestrator/rag/service.py`
```python
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
```

## N.6 `backend/apps/orchestrator/api/rag.py`
```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.apps.orchestrator.rag.service import RagService

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])
_service = RagService()


class RagIngestRequest(BaseModel):
    doc_key: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagSearchRequest(BaseModel):
    query: str
    k: int = 4
    min_score: float = 0.35


@router.post("/documents")
async def ingest_document(req: RagIngestRequest):
    try:
        return await _service.ingest(doc_key=req.doc_key, content=req.content, metadata=req.metadata)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/search")
async def search_documents(req: RagSearchRequest):
    try:
        hits = await _service.search(query=req.query, k=req.k, min_score=req.min_score)
        return {"count": len(hits), "hits": hits}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
```

## N.7 `backend/apps/orchestrator/api/orchestrate.py`
```python
from fastapi import APIRouter, HTTPException

from backend.apps.orchestrator.dependencies import get_orchestration_service
from backend.platform.shared.schemas import EventType, OrchestrateRequest

router = APIRouter(prefix="/api", tags=["orchestrator"])


@router.post("/orchestrate")
async def orchestrate(req: OrchestrateRequest):
    try:
        service = get_orchestration_service()
        final_data = None
        async for event in service.stream(req):
            if event.event == EventType.final:
                final_data = event.data
        if final_data is None:
            raise RuntimeError("No final event emitted from stream pipeline")
        return final_data
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

## N.8 `backend/apps/orchestrator/api/stream.py`
```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.apps.orchestrator.dependencies import get_orchestration_service
from backend.apps.orchestrator.streaming.sse_emitter import to_sse
from backend.platform.shared.schemas import OrchestrateRequest

router = APIRouter(prefix="/api", tags=["orchestrator"])


@router.post("/stream")
async def stream(req: OrchestrateRequest):
    service = get_orchestration_service()

    async def gen():
        async for evt in service.stream(req):
            yield to_sse(evt)

    return StreamingResponse(gen(), media_type="text/event-stream")
```

## N.9 `backend/apps/orchestrator/api/chat.py`
```python
from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.apps.orchestrator.dependencies import get_orchestration_service
from backend.apps.orchestrator.streaming.sse_emitter import to_sse
from backend.platform.shared.schemas import OrchestrateRequest

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
_stream_store: dict[str, dict[str, str]] = {}


class CreateChatStreamRequest(BaseModel):
    message: str
    session_id: str | None = None


@router.post("/streams")
async def create_stream(req: CreateChatStreamRequest):
    stream_id = str(uuid.uuid4())
    session_id = req.session_id or str(uuid.uuid4())
    _stream_store[stream_id] = {"message": req.message, "session_id": session_id}
    return {
        "stream_id": stream_id,
        "session_id": session_id,
        "stream_url": f"/api/v1/chat/streams/{stream_id}/events",
    }


@router.get("/streams/{stream_id}/events")
async def stream_events(stream_id: str):
    item = _stream_store.get(stream_id)
    if not item:
        raise HTTPException(status_code=404, detail="stream_id not found")

    service = get_orchestration_service()
    req = OrchestrateRequest(message=item["message"], session_id=item["session_id"])

    async def gen() -> AsyncIterator[str]:
        async for evt in service.stream(req):
            yield to_sse(evt)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

## N.10 `backend/apps/orchestrator/api/sessions.py`
```python
from fastapi import APIRouter, HTTPException

from backend.apps.orchestrator.dependencies import get_orchestration_service

router = APIRouter(prefix="/api", tags=["orchestrator"])


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    service = get_orchestration_service()
    state = service.get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="session not found")
    return state.model_dump()
```

## N.11 `backend/apps/orchestrator/api/health.py`
```python
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator"}
```

## N.12 `backend/apps/orchestrator/streaming/sse_emitter.py`
```python
from __future__ import annotations

import json


def to_sse(event) -> str:
    event_name = getattr(event, "event", "message")
    data = getattr(event, "data", {})
    if hasattr(event_name, "value"):
        event_name = event_name.value
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

## N.13 `backend/apps/orchestrator/dependencies.py`
```python
from backend.apps.orchestrator.core.orchestration_service import OrchestrationService
from backend.apps.orchestrator.core.session_store import SessionStore
from backend.apps.orchestrator.streaming.stream_manager import StreamManager

_sessions = SessionStore()
_streams = StreamManager()
_service = OrchestrationService(_sessions, _streams)


def get_orchestration_service() -> OrchestrationService:
    return _service
```

## N.14 `backend/apps/orchestrator/core/session_store.py`
```python
from __future__ import annotations

from backend.platform.shared.schemas import SessionState


class SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState | None:
        return self._data.get(session_id)

    def upsert(self, state: SessionState) -> None:
        self._data[state.session_id] = state
```

## N.15 `backend/apps/orchestrator/streaming/stream_manager.py`
```python
from __future__ import annotations


class StreamManager:
    def __init__(self) -> None:
        self._events: dict[str, list[dict]] = {}

    def append(self, session_id: str, event: dict) -> None:
        self._events.setdefault(session_id, []).append(event)

    def get(self, session_id: str) -> list[dict]:
        return self._events.get(session_id, [])
```

## N.16 `backend/apps/orchestrator/streaming/event_schema.py`
```python
from backend.platform.shared.schemas import SSEEvent as StreamEvent
```

## N.17 `backend/apps/orchestrator/core/registry.py`
```python
from __future__ import annotations

from backend.apps.orchestrator.config import AGENT_ENDPOINTS, CUSTOM_AGENTS


def get_agent_registry() -> dict[str, str]:
    out = dict(AGENT_ENDPOINTS)
    for item in CUSTOM_AGENTS:
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if name and url:
            out[name] = url
    return out
```

## N.18 `backend/apps/orchestrator/agent_provider/base.py`
```python
from __future__ import annotations

from abc import ABC, abstractmethod

from backend.platform.shared.schemas import AgentResult, AgentTask


class BaseAgentProvider(ABC):
    @abstractmethod
    async def execute(self, session_id: str, message: str, task: AgentTask) -> AgentResult:
        raise NotImplementedError
```

## N.19 `backend/apps/orchestrator/agent_provider/http_client.py`
```python
from __future__ import annotations

import httpx

from backend.apps.orchestrator.agent_provider.base import BaseAgentProvider
from backend.apps.orchestrator.config import AGENT_HTTP_TIMEOUT, AGENT_HTTP_TRUST_ENV
from backend.apps.orchestrator.core.registry import get_agent_registry
from backend.platform.shared.schemas import AgentResult, AgentTask


class HttpAgentProvider(BaseAgentProvider):
    async def execute(self, session_id: str, message: str, task: AgentTask) -> AgentResult:
        registry = get_agent_registry()
        base_url = registry.get(task.agent_id)
        if not base_url:
            return AgentResult(agent_id=task.agent_id, capability=task.capability, success=False, error="unknown agent")

        payload = {
            "session_id": session_id,
            "message": message,
            "task": task.model_dump(),
        }

        try:
            async with httpx.AsyncClient(timeout=AGENT_HTTP_TIMEOUT, trust_env=AGENT_HTTP_TRUST_ENV) as client:
                res = await client.post(f"{base_url}/execute", json=payload)
                res.raise_for_status()
                data = res.json()
            success = bool(data.get("success", True))
            output = data.get("output", {}) if isinstance(data.get("output"), dict) else {}
            error = data.get("error")
            return AgentResult(agent_id=task.agent_id, capability=task.capability, success=success, output=output, error=error)
        except Exception as exc:
            return AgentResult(agent_id=task.agent_id, capability=task.capability, success=False, error=str(exc))
```

## N.20 `backend/apps/orchestrator/common/chat_client.py`
```python
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
```

## N.21 `backend/apps/orchestrator/llm/base_adapter.py`
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMAdapter(ABC):
    @abstractmethod
    async def generate_json(self, *, system_prompt: str, user_prompt: str, model: str, temperature: float = 0.0) -> dict[str, Any]:
        raise NotImplementedError
```

## N.22 `backend/apps/orchestrator/llm/adapters/mock_adapter.py`
```python
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
```

## N.23 `backend/apps/orchestrator/llm/factory.py`
```python
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
```
