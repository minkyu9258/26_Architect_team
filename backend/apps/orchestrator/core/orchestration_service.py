from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator

from backend.apps.orchestrator.core.agent_executor import (
    llm_build_plan,
    llm_chat_answer,
    llm_fallback_intent,
    llm_fill_missing_entities,
    run_parallel,
    run_parallel_stream,
)
from backend.apps.orchestrator.core.intent_router import analyze_intent, build_tasks, detect_missing_fields, extract_entities
from backend.apps.orchestrator.core.session_store import SessionStore
from backend.apps.orchestrator.rag.service import RagService
from backend.apps.orchestrator.streaming.event_schema import StreamEvent
from backend.apps.orchestrator.streaming.stream_manager import StreamManager
from backend.platform.shared.schemas import AgentResult, AgentTask, EventType, OrchestrateRequest, OrchestrateResponse, SessionState


@dataclass
class PreparedContext:
    session_id: str
    message: str
    combined_message: str
    state: SessionState
    intent: str
    confidence: float
    entities: dict[str, Any]
    tasks: list[AgentTask]
    route_source: str
    routing_debug: dict[str, Any]


class OrchestrationService:
    def __init__(self, session_store: SessionStore, stream_manager: StreamManager) -> None:
        self._sessions = session_store
        self._streams = stream_manager
        self._rag_enabled = os.getenv("RAG_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
        self._rag_top_k = max(1, int(os.getenv("RAG_TOP_K", "4")))
        self._rag_min_score = float(os.getenv("RAG_MIN_SCORE", "0.35"))
        self._rag_auto_ingest = os.getenv("RAG_AUTO_INGEST", "true").lower() in {"1", "true", "yes", "on"}
        self._rag_chunk_size = max(300, int(os.getenv("RAG_INGEST_CHUNK_SIZE", "900")))
        self._rag_chunk_overlap = max(0, int(os.getenv("RAG_INGEST_CHUNK_OVERLAP", "120")))
        self._rag_service = RagService() if self._rag_enabled else None

    def _mask_sensitive(self, message: str) -> str:
        masked = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "***@***", message)
        return re.sub(r"(?i)(password|secret|token|api[_ -]?key)\s*[:=]?\s*\S+", r"\1=***", masked)

    def _resolve_message(self, request: OrchestrateRequest) -> str:
        if request.message and request.message.strip():
            return request.message.strip()
        raise ValueError("message is required")

    async def _build_rag_context(self, message: str, routing_debug: dict[str, Any]) -> str:
        if not self._rag_enabled or self._rag_service is None:
            routing_debug["rag"] = {"enabled": False, "count": 0, "hits": []}
            return ""
        hits = await self._rag_service.search(query=message, k=self._rag_top_k, min_score=self._rag_min_score)
        routing_debug["rag"] = {
            "enabled": True,
            "count": len(hits),
            "hits": [{"doc_key": h.get("doc_key"), "score": h.get("score"), "metadata": h.get("metadata", {})} for h in hits],
        }
        if not hits:
            return ""
        lines = []
        for i, h in enumerate(hits, 1):
            source = h.get("metadata", {}).get("source", "unknown")
            lines.append(f"[{i}] key={h.get('doc_key')} source={source} score={float(h.get('score', 0.0)):.4f}\n{str(h.get('content', ''))[:600]}")
        return "\n\n".join(lines)

    async def _prepare_context(self, request: OrchestrateRequest) -> tuple[PreparedContext | None, OrchestrateResponse | None]:
        session_id = request.session_id or str(uuid.uuid4())
        message = self._resolve_message(request)
        prev = self._sessions.get(session_id)

        if prev and prev.status == "needs_clarification":
            combined_message = f"{prev.message}\n{message}"
            intent = prev.intent
            confidence = 0.9
            route_source = "hitl"
            entities = dict(prev.entities)
            entities.update(extract_entities(message))
            tasks = list(prev.tasks)
        else:
            combined_message = message
            intent, confidence, entities = analyze_intent(combined_message)
            route_source = "rule"
            _, tasks = build_tasks(combined_message)

        missing = detect_missing_fields(intent, entities, combined_message)
        routing_debug = {"intent": intent, "intent_source": "rule", "confidence": confidence}

        if missing:
            fb = await llm_fallback_intent(combined_message)
            intent = str(fb.get("intent", intent))
            confidence = float(fb.get("confidence", confidence))
            entities = {**entities, **(fb.get("entities", {}) if isinstance(fb.get("entities"), dict) else {})}
            route_source = "rule->llm_fallback"
            routing_debug["intent_source"] = "llm_fallback"
            routing_debug["llm_fallback"] = fb
            _, tasks = build_tasks(combined_message)
            missing = detect_missing_fields(intent, entities, combined_message)

        if missing:
            assist = await llm_fill_missing_entities(intent=intent, message=combined_message, entities=entities, missing=missing)
            entities = assist.get("entities", entities)
            new_missing = detect_missing_fields(intent, entities, combined_message)
            routing_debug["llm_assist"] = {
                "called": assist.get("called", False),
                "missing_before": missing,
                "missing_after": new_missing,
                "inferred_entities": assist.get("inferred_entities", {}),
                "raw_response": assist.get("raw_response", {}),
            }
            missing = new_missing
            if route_source.startswith("rule"):
                route_source = "rule+llm_assist"

        rag_context = await self._build_rag_context(combined_message, routing_debug)
        if rag_context:
            combined_message = f"{combined_message}\n\n[RAG_CONTEXT]\n{rag_context}"

        state = SessionState(
            session_id=session_id,
            message=combined_message,
            masked_message=self._mask_sensitive(combined_message),
            intent=intent,
            tasks=tasks,
            entities=entities,
            missing_fields=missing,
            clarification_attempts=dict(prev.clarification_attempts) if prev else {},
            history=list(prev.history) if prev else [],
        )

        if missing:
            state.status = "needs_clarification"
            q = "레포지토리 이름을 알려주세요." if "repository_name" in missing else "추가 입력이 필요합니다."
            self._sessions.upsert(state)
            return None, OrchestrateResponse(
                success=True,
                session_id=session_id,
                intent=intent,
                results=[],
                summary="Additional input is required.",
                needs_clarification=True,
                missing_fields=[missing[0]],
                clarification_question=q,
                confidence=confidence,
                entities=entities,
                route_source=route_source,
                routing_debug=routing_debug,
            )

        state.status = "running"
        self._sessions.upsert(state)
        return PreparedContext(session_id, message, combined_message, state, intent, confidence, entities, tasks, route_source, routing_debug), None

    async def _build_plan(self, context: PreparedContext) -> dict[str, Any]:
        plan = await llm_build_plan(message=context.combined_message, intent=context.intent, entities=context.entities, tasks=context.tasks)
        context.routing_debug["planner"] = plan
        return plan

    def _build_summary(self, intent: str, results: list[AgentResult]) -> str:
        if not results:
            return f"'{intent}' 의 실행 결과가 없습니다."
        lines = []
        for it in results:
            if it.success:
                lines.append(f"- {it.agent_id} ({it.capability}) 실행 완료: {it.output}")
            else:
                lines.append(f"- {it.agent_id} ({it.capability}) 실행 실패: {it.error or 'unknown error'}")
        return "\n".join(lines)

    async def _finalize_general_chat(self, context: PreparedContext) -> OrchestrateResponse:
        chat = await llm_chat_answer(context.message)
        answer = str(chat.get("answer", "")).strip() or "답변이 비어 있습니다."
        context.routing_debug["llm_chat"] = chat
        context.routing_debug["planner"] = {"skipped": True, "reason": "general_chat"}
        context.state.status = "completed"
        context.state.updated_at = datetime.utcnow()
        self._sessions.upsert(context.state)
        return OrchestrateResponse(
            success=True,
            session_id=context.session_id,
            intent="general",
            results=[],
            summary=answer,
            confidence=context.confidence,
            entities=context.entities,
            route_source="llm_chat",
            routing_debug=context.routing_debug,
        )

    async def _finalize_state(self, context: PreparedContext, results: list[AgentResult]) -> OrchestrateResponse:
        context.state.results = results
        context.state.status = "completed"
        context.state.updated_at = datetime.utcnow()
        self._sessions.upsert(context.state)
        return OrchestrateResponse(
            success=True,
            session_id=context.session_id,
            intent=context.intent,
            results=results,
            summary=self._build_summary(context.intent, results),
            confidence=context.confidence,
            entities=context.entities,
            route_source=context.route_source,
            routing_debug=context.routing_debug,
        )

    async def stream(self, request: OrchestrateRequest) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(event=EventType.progress, data={"phase": "intent_analyzing", "message": "Intent/Rule/LLM 경로 분석 중"})
        context, clarification = await self._prepare_context(request)
        if clarification:
            yield StreamEvent(event=EventType.final, data=clarification.model_dump())
            return

        assert context is not None
        if context.intent == "general" and not context.tasks:
            response = await self._finalize_general_chat(context)
            yield StreamEvent(event=EventType.final, data=response.model_dump())
            return

        yield StreamEvent(event=EventType.progress, data={"phase": "intent_resolved", "intent": context.intent, "route_source": context.route_source, "routing_debug": context.routing_debug})
        yield StreamEvent(event=EventType.planning, data={"intent": context.intent, "route_source": context.route_source, "tasks": [t.model_dump() for t in context.tasks], "routing_debug": context.routing_debug})

        plan = await self._build_plan(context)
        yield StreamEvent(event=EventType.progress, data={"phase": "planner_completed", "plan": plan, "routing_debug": context.routing_debug})

        results: list[AgentResult] = []
        async for item in run_parallel_stream(context.session_id, context.combined_message, context.tasks):
            results.append(item)
            yield StreamEvent(event=EventType.result, data={
                "session_id": context.session_id,
                "intent": context.intent,
                "route_source": context.route_source,
                "agent_id": item.agent_id,
                "capability": item.capability,
                "success": item.success,
                "output": item.output,
                "error": item.error,
            })

        response = await self._finalize_state(context, results)
        yield StreamEvent(event=EventType.final, data=response.model_dump())

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)
