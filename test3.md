## N.24 `backend/apps/orchestrator/llm_gateway/gateway.py`
```python
from __future__ import annotations

from typing import Any

from backend.apps.orchestrator.config import LLM_ROLE_MODELS
from backend.apps.orchestrator.llm.factory import create_llm_adapter


class LLMGateway:
    def __init__(self) -> None:
        self.adapter = create_llm_adapter()

    async def generate_json(self, *, role: str, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> dict[str, Any]:
        model = LLM_ROLE_MODELS.get(role) or LLM_ROLE_MODELS["intent_fallback"]
        return await self.adapter.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
        )
```

## N.25 `backend/apps/orchestrator/core/orchestration_service.py`

> 매우 길기 때문에 핵심 구현 포인트를 담은 "축약 전체"입니다. Gemini에게는 이 섹션을 기준으로 전체 파일 작성 지시.

```python
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
```

## N.26 프론트 서비스 템플릿

### `frontend/src/services/chatApi.js`
```js
const API_PREFIX = '/api/v1'

export async function createChatStream(message, sessionId = null) {
  const res = await fetch(`${API_PREFIX}/chat/streams`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
  if (!res.ok) throw new Error(`Stream create failed: ${res.status}`)
  return await res.json()
}
```

### `frontend/src/stream_view/services/eventSourceClient.js`
```js
export function createStreamConnection(url, { onOpen, onEvent, onError } = {}) {
  const es = new EventSource(url)
  es.onopen = onOpen || null
  es.onerror = onError || null

  es.onmessage = (evt) => {
    onEvent && onEvent({ type: 'message', data: evt.data })
  }

  ;['progress', 'planning', 'result', 'final', 'error'].forEach((eventName) => {
    es.addEventListener(eventName, (evt) => {
      onEvent && onEvent({ type: eventName, data: evt.data })
    })
  })

  return es
}
```


---

## O. `frontend/src/pages/ConsolePage.vue` 전체 템플릿

```vue
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import ChatComposer from '@/components/chat/ChatComposer.vue'
import { createChatStream } from '@/services/chatApi'
import StreamStatus from '@/stream_view/StreamStatus.vue'
import { createStreamConnection } from '@/stream_view/services/eventSourceClient'

const isLoading = ref(false)
const error = ref('')
const status = ref('idle')
const events = ref([])
const sessionId = ref('')
const intent = ref('')
const routeSource = ref('')
const planner = ref(null)
const ragHits = ref([])
const taskCount = ref(0)
const resultCount = ref(0)
const turns = ref([])
const chatWindowEl = ref(null)
let connection = null

const topCards = computed(() => [
  { label: 'Session', value: sessionId.value || '(none)' },
  { label: 'Intent', value: intent.value || '(pending)' },
  { label: 'Route', value: routeSource.value || '(pending)' },
  { label: 'Events', value: String(events.value.length) },
  { label: 'Planned Tasks', value: String(taskCount.value) },
  { label: 'Agent Results', value: String(resultCount.value) },
])

const routeBadgeLabel = computed(() => {
  const route = routeSource.value.toLowerCase()
  const hasRag = ragHits.value.length > 0
  const isGeneral = intent.value.toLowerCase() === 'general'

  if (!route && !hasRag) return 'Pending'
  if ((route.includes('llm') || route === 'hitl') && isGeneral && !hasRag) return 'LLM General'
  if ((route.includes('llm') || route === 'hitl') && isGeneral && hasRag) return 'LLM General+RAG'
  if ((route.includes('llm') || route === 'hitl') && hasRag) return 'LLM+RAG'
  if (route.includes('llm') || route === 'hitl') return 'LLM'
  if (route.includes('rule') && hasRag) return 'RULE+RAG'
  if (route.includes('rule')) return 'RULE'
  if (hasRag) return 'RAG'
  return routeSource.value || 'Pending'
})

const routeBadgeClass = computed(() => {
  const label = routeBadgeLabel.value
  if (label.includes('LLM')) return 'is-llm'
  if (label.includes('RULE')) return 'is-rule'
  if (label.includes('RAG')) return 'is-rag'
  return 'is-pending'
})

function closeStream() {
  if (!connection) return
  connection.close()
  connection = null
}

function addTurn(role, text, meta = '', evidence = []) {
  turns.value.push({ role, text, meta, evidence, at: new Date().toISOString() })
}

function getTurnRouteLabel(turn) {
  const meta = String(turn.meta || '').toLowerCase()
  const hasRag = Array.isArray(turn.evidence) && turn.evidence.length > 0
  const isGeneral = meta.includes('general')

  if ((meta.includes('llm') || meta.includes('hitl')) && isGeneral && !hasRag) return 'LLM General'
  if ((meta.includes('llm') || meta.includes('hitl')) && isGeneral && hasRag) return 'LLM General+RAG'
  if ((meta.includes('llm') || meta.includes('hitl')) && hasRag) return 'LLM+RAG'
  if (meta.includes('llm') || meta.includes('hitl')) return 'LLM'
  if (meta.includes('rule') && hasRag) return 'RULE+RAG'
  if (meta.includes('rule')) return 'RULE'
  if (hasRag) return 'RAG'
  return turn.meta || ''
}

function newChat() {
  closeStream()
  error.value = ''
  status.value = 'idle'
  events.value = []
  sessionId.value = ''
  intent.value = ''
  routeSource.value = ''
  planner.value = null
  ragHits.value = []
  taskCount.value = 0
  resultCount.value = 0
  turns.value = []
}

function parseEvent(event) {
  try {
    return JSON.parse(event.data)
  } catch {
    return { raw: event.data }
  }
}

async function handleSend(message) {
  if (isLoading.value) return

  isLoading.value = true
  error.value = ''
  status.value = 'connecting'
  events.value = []
  planner.value = null
  ragHits.value = []
  taskCount.value = 0
  resultCount.value = 0

  addTurn('user', message)

  try {
    const streamInfo = await createChatStream(message, sessionId.value || null)
    sessionId.value = streamInfo.session_id

    closeStream()
    connection = createStreamConnection(streamInfo.stream_url, {
      onOpen: () => {
        status.value = 'connected'
      },
      onEvent: (event) => {
        const parsed = parseEvent(event)
        events.value = [{ type: event.type, data: parsed }, ...events.value].slice(0, 30)

        if (parsed.intent) intent.value = parsed.intent
        if (parsed.route_source) routeSource.value = parsed.route_source
        if (event.type === 'planning' && Array.isArray(parsed.tasks)) taskCount.value = parsed.tasks.length
        if (event.type === 'progress' && parsed.phase === 'planner_completed') planner.value = parsed.plan || null
        if (parsed.routing_debug?.rag?.hits) ragHits.value = parsed.routing_debug.rag.hits
        if (event.type === 'result') resultCount.value += 1

        if (event.type === 'progress' && parsed.message) {
          addTurn('system', parsed.message, parsed.phase || 'progress')
        }

        if (event.type === 'final') {
          const finalText = parsed.clarification_question || parsed.summary || 'Done'
          const evidence = parsed.routing_debug?.rag?.hits || []
          addTurn('assistant', finalText, `${parsed.intent || ''} / ${parsed.route_source || ''}`, evidence)
          status.value = 'done'
          isLoading.value = false
          closeStream()
        }

        if (event.type === 'error') {
          error.value = parsed.message || 'Stream error'
          addTurn('assistant', error.value, 'error')
          status.value = 'error'
          isLoading.value = false
          closeStream()
        }
      },
      onError: () => {
        status.value = 'error'
        error.value = 'SSE connection failed'
        addTurn('assistant', error.value, 'error')
        isLoading.value = false
        closeStream()
      },
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unknown error'
    addTurn('assistant', error.value, 'error')
    status.value = 'error'
    isLoading.value = false
  }
}

watch(
  () => turns.value.length,
  async () => {
    await nextTick()
    if (chatWindowEl.value) {
      chatWindowEl.value.scrollTop = chatWindowEl.value.scrollHeight
    }
  },
)

onBeforeUnmount(closeStream)
</script>

<template>
  <main class="console-shell">
    <section class="console-panel">
      <div class="console-heading">
        <p class="eyebrow">AI Agent Orchestrator</p>
        <h1>Enterprise Console</h1>
        <p class="route-badge" :class="routeBadgeClass">{{ routeBadgeLabel }}</p>
      </div>

      <div class="card-grid">
        <article v-for="item in topCards" :key="item.label" class="stat-card">
          <p class="stat-label">{{ item.label }}</p>
          <p class="stat-value">{{ item.value }}</p>
        </article>
      </div>

      <div class="console-grid">
        <div class="chat-column">
          <section ref="chatWindowEl" class="chat-window">
            <p v-if="turns.length === 0" class="summary">아직 대화가 없습니다. 아래 입력창에서 명령을 실행하세요.</p>
            <div v-for="(turn, idx) in turns" :key="idx" class="bubble-row" :class="`role-${turn.role}`">
              <div class="bubble">
                <p class="bubble-text">{{ turn.text }}</p>
                <p v-if="turn.meta" class="bubble-meta">
                  <span class="inline-route-badge">{{ getTurnRouteLabel(turn) }}</span>
                </p>
                <ul v-if="turn.evidence && turn.evidence.length" class="bubble-evidence">
                  <li v-for="(hit, hIdx) in turn.evidence" :key="`${hIdx}-${hit.doc_key}`">
                    {{ hit.doc_key }} ({{ Number(hit.score || 0).toFixed(3) }})
                  </li>
                </ul>
              </div>
            </div>
          </section>

          <section class="composer-dock">
            <ChatComposer :is-loading="isLoading" @send="handleSend" @new-chat="newChat" />
          </section>

          <section class="plan-panel" v-if="planner">
            <h2>Planner Output</h2>
            <pre>{{ planner }}</pre>
          </section>

          <section class="plan-panel" v-if="ragHits.length">
            <h2>RAG Evidence</h2>
            <ul class="rag-list">
              <li v-for="(hit, idx) in ragHits" :key="`${hit.doc_key}-${idx}`">
                <strong>{{ hit.doc_key }}</strong>
                <span>score={{ Number(hit.score || 0).toFixed(4) }}</span>
                <span>source={{ hit.metadata?.source || 'unknown' }}</span>
              </li>
            </ul>
          </section>
        </div>

        <StreamStatus :status="status" :events="events" />
      </div>
    </section>
  </main>
</template>
```


---

## P. `frontend/src/stream_view/StreamStatus.vue` 전체 템플릿

```vue
<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: 'idle' },
  events: { type: Array, default: () => [] },
})

const stages = [
  { key: 'intent_analyzing', label: 'Intent Analyzing' },
  { key: 'intent_resolved', label: 'Intent Resolved' },
  { key: 'planning', label: 'Planning' },
  { key: 'result', label: 'Agent Execution' },
  { key: 'final', label: 'Finalized' },
]

const normalizedEvents = computed(() => {
  return props.events.map((e) => {
    const data = e?.data || {}
    if (e.type === 'progress' && data.phase) {
      return { key: data.phase, label: String(data.phase).replaceAll('_', ' '), type: e.type, data }
    }
    return { key: e.type, label: e.type, type: e.type, data }
  })
})

const currentStepIndex = computed(() => {
  const keys = new Set(normalizedEvents.value.map((e) => e.key))
  let idx = -1
  if (keys.has('intent_analyzing')) idx = 0
  if (keys.has('intent_resolved')) idx = 1
  if (keys.has('planning')) idx = 2
  if (keys.has('result')) idx = 3
  if (keys.has('final')) idx = 4
  return idx
})
</script>

<template>
  <aside class="stream-panel">
    <div>
      <p class="panel-label">SSE EventSource</p>
      <h2>Stream Timeline</h2>
    </div>

    <p class="stream-state" :data-state="status">{{ status }}</p>

    <ol class="stepper">
      <li
        v-for="(stage, idx) in stages"
        :key="stage.key"
        :class="{ done: idx <= currentStepIndex, current: idx === currentStepIndex }"
      >
        <span class="dot" />
        <span class="txt">{{ stage.label }}</span>
      </li>
    </ol>

    <ul v-if="events.length" class="event-list">
      <li v-for="(entry, idx) in events" :key="idx">
        <strong>{{ entry.type }}</strong>
        <pre>{{ entry.data }}</pre>
      </li>
    </ul>

    <p v-else class="summary">No stream events yet.</p>
  </aside>
</template>
```

---

## Q. `frontend/src/styles/main.css` 전체 템플릿

```css
:root {
  color: #132238;
  background: #f3f6fb;
  font-family: "Segoe UI", "Noto Sans KR", sans-serif;
  line-height: 1.5;
}

* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; min-height: 100vh; }
button, textarea { font: inherit; }

.console-shell {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 32px 16px;
  background: linear-gradient(135deg, rgba(49, 94, 251, 0.12), transparent 42%), #f3f6fb;
}

.console-panel {
  width: min(1180px, 100%);
  padding: 32px;
  border: 1px solid #dbe3ef;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 16px 40px rgba(18, 34, 56, 0.12);
}

.console-heading { max-width: 760px; margin-bottom: 24px; }
.eyebrow { margin: 0 0 8px; color: #315efb; font-size: .78rem; font-weight: 800; text-transform: uppercase; }
h1,h2,p { margin-top: 0; }
h1 { margin-bottom: 10px; font-size: 2.4rem; }
.summary { color: #56657a; }

.route-badge {
  display: inline-block;
  margin: 6px 0 0;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 800;
  color: #1e3a8a;
  background: #dbeafe;
}
.route-badge.is-llm { color: #075985; background: #e0f2fe; }
.route-badge.is-rule { color: #1e3a8a; background: #dbeafe; }
.route-badge.is-rag { color: #14532d; background: #dcfce7; }
.route-badge.is-pending { color: #334155; background: #e2e8f0; }

.console-grid { display: grid; grid-template-columns: minmax(0,1fr) 360px; gap: 24px; align-items: start; }
.chat-form { display: grid; gap: 12px; }
label { color: #243746; font-weight: 700; }
textarea {
  width: 100%;
  min-height: 156px;
  resize: vertical;
  border: 1px solid #b8c8cf;
  border-radius: 8px;
  padding: 14px 16px;
  color: #152434;
  background: #fbfdfe;
}
textarea:focus { border-color: #315efb; outline: 3px solid rgba(49,94,251,.16); }

.row-actions { display: flex; gap: 8px; }
button {
  min-width: 120px;
  min-height: 44px;
  border: 0;
  border-radius: 8px;
  padding: 0 20px;
  color: #fff;
  background: #315efb;
  font-weight: 800;
  cursor: pointer;
}
button:disabled { background: #9db1d8; cursor: not-allowed; }
.secondary-button { border: 1px solid #c7d3e6; color: #243746; background: #fff; }

.card-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.stat-card {
  border: 1px solid #dbe6f2;
  border-radius: 10px;
  padding: 10px 12px;
  background: #f8fbff;
}

.stat-label {
  margin: 0;
  color: #5b6b80;
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
}

.stat-value {
  margin: 4px 0 0;
  color: #0f2340;
  font-size: 0.94rem;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.chat-column { display: grid; gap: 12px; }

.chat-window {
  min-height: 420px;
  max-height: 520px;
  overflow: auto;
  border: 1px solid #dbe6ea;
  border-radius: 12px;
  background: #f9fbff;
  padding: 14px;
  display: grid;
  gap: 10px;
}

.bubble-row { display: flex; }

.bubble {
  max-width: 78%;
  border-radius: 14px;
  padding: 10px 12px;
  box-shadow: 0 2px 8px rgba(16, 35, 64, 0.08);
}

.role-user { justify-content: flex-end; }
.role-user .bubble {
  background: #315efb;
  color: #fff;
  border-top-right-radius: 6px;
}

.role-assistant { justify-content: flex-start; }
.role-assistant .bubble {
  background: #ffffff;
  color: #132238;
  border: 1px solid #dbe6f2;
  border-top-left-radius: 6px;
}

.role-system { justify-content: center; }
.role-system .bubble {
  background: #eef3ff;
  color: #315efb;
  border: 1px solid #d5e1ff;
  box-shadow: none;
}

.bubble-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble-meta {
  margin: 6px 0 0;
  font-size: 0.75rem;
  opacity: 0.75;
}

.inline-route-badge {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 8px;
  color: #334155;
  background: #e2e8f0;
}

.bubble-evidence {
  margin: 8px 0 0;
  padding-left: 16px;
  font-size: 0.78rem;
  opacity: 0.9;
}

.composer-dock {
  border: 1px solid #dbe6ea;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.composer-dock .chat-form { gap: 8px; }
.composer-dock .chat-form textarea { min-height: 96px; }

.plan-panel {
  margin-top: 16px;
  border: 1px solid #dbe6ea;
  border-radius: 8px;
  padding: 12px;
  background: #f8fbfc;
}

.plan-panel h2 { margin: 0 0 8px; }

pre {
  overflow: auto;
  margin: 0;
  border-radius: 8px;
  padding: 16px;
  color: #dbeafe;
  background: #102331;
  white-space: pre-wrap;
}

.rag-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  color: #1c2f46;
}

.rag-list li { display: grid; gap: 2px; font-size: 0.88rem; }

.stream-panel {
  display: grid;
  gap: 16px;
  border: 1px solid #dbe6ea;
  border-radius: 8px;
  padding: 18px;
  background: #f8fbfc;
}

.panel-label {
  margin-bottom: 4px;
  color: #6b7280;
  font-size: .78rem;
  font-weight: 800;
  text-transform: uppercase;
}

.stream-state {
  width: fit-content;
  margin: 0;
  border-radius: 999px;
  padding: 4px 10px;
  color: #243746;
  background: #e7eef1;
  font-weight: 800;
}
.stream-state[data-state='connected'] { color: #065f46; background: #d1fae5; }
.stream-state[data-state='done'] { color: #1e3a8a; background: #dbeafe; }
.stream-state[data-state='error'] { color: #b91c1c; background: #fee2e2; }

.stepper {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}

.stepper li {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #607184;
  font-size: 0.9rem;
}

.stepper li .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #c7d3e6;
}

.stepper li.done { color: #0f2340; font-weight: 700; }
.stepper li.done .dot { background: #315efb; }
.stepper li.current .dot { box-shadow: 0 0 0 4px rgba(49,94,251,0.18); }

.event-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.event-list li {
  overflow-wrap: anywhere;
  border: 1px solid #e1eaee;
  border-radius: 8px;
  padding: 10px;
  background: #fff;
  color: #34495a;
  font-size: .9rem;
}

.event-list pre {
  margin-top: 8px;
  padding: 10px;
  border-radius: 6px;
  background: #0f172a;
  color: #e2e8f0;
}

@media (max-width: 1180px) {
  .card-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 960px) {
  .console-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .console-panel { padding: 24px 18px; }
  h1 { font-size: 2rem; }
  .row-actions { flex-direction: column; }
  button { width: 100%; }
}
```


---
