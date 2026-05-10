
## M. 파일별 초기 코드 템플릿 (복붙용)

아래 템플릿은 "최소 동작" 기준입니다. Gemini에게 파일별로 그대로 생성시키고, 이후 세부 고도화하면 됩니다.

## M.1 `backend/platform/shared/schemas.py`
```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    planning = "planning"
    progress = "progress"
    result = "result"
    error = "error"
    final = "final"


class OrchestrateRequest(BaseModel):
    message: str | None = None
    encrypted_payload: dict[str, str] | None = None
    is_encrypted: bool = False
    session_id: str | None = None


class AgentTask(BaseModel):
    agent_id: str
    capability: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    agent_id: str
    capability: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class SessionState(BaseModel):
    session_id: str
    message: str
    masked_message: str | None = None
    intent: str
    tasks: list[AgentTask]
    results: list[AgentResult] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    clarification_attempts: dict[str, int] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "running"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SSEEvent(BaseModel):
    event: EventType
    data: dict[str, Any]


class OrchestrateResponse(BaseModel):
    success: bool
    session_id: str
    intent: str
    results: list[AgentResult]
    summary: str
    needs_clarification: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    confidence: float = 1.0
    entities: dict[str, Any] = Field(default_factory=dict)
    route_source: str = "unknown"
    routing_debug: dict[str, Any] = Field(default_factory=dict)
```

## M.2 `backend/apps/orchestrator/config.py`
```python
import json
import os


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _json_list_env(name: str) -> list[dict[str, object]]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


APP_NAME = os.getenv("ORCHESTRATOR_APP_NAME", "mdm-ai-orchestrator")
APP_VERSION = os.getenv("ORCHESTRATOR_APP_VERSION", "0.2.0")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

AGENT_ENDPOINTS = {
    "jira_agent": os.getenv("JIRA_AGENT_URL", "http://jira-agent:8000"),
    "github_agent": os.getenv("GITHUB_AGENT_URL", "http://github-agent:8000"),
    "cloud_agent": os.getenv("CLOUD_AGENT_URL", "http://cloud-agent:8000"),
    "mdm_agent": os.getenv("MDM_AGENT_URL", "http://mdm-agent:8000"),
}
AGENT_HTTP_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "20"))
AGENT_HTTP_TRUST_ENV = _bool_env("AGENT_HTTP_TRUST_ENV", False)
CUSTOM_AGENTS = _json_list_env("CUSTOM_AGENTS_JSON")

LLM_ROLE_MODELS = {
    "intent_fallback": os.getenv("LLM_ROLE_INTENT_MODEL", "") or os.getenv("LLM_MODEL_NAME", "gpt-4.1-mini"),
    "planner": os.getenv("LLM_ROLE_PLANNER_MODEL", "") or os.getenv("LLM_MODEL_NAME", "gpt-4.1"),
    "summary": os.getenv("LLM_ROLE_SUMMARY_MODEL", "") or os.getenv("LLM_MODEL_NAME", "gpt-4.1-mini"),
}
```

## M.3 `backend/apps/orchestrator/main.py`
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.apps.orchestrator.api.chat import router as chat_router
from backend.apps.orchestrator.api.health import router as health_router
from backend.apps.orchestrator.api.orchestrate import router as orchestrate_router
from backend.apps.orchestrator.api.rag import router as rag_router
from backend.apps.orchestrator.api.sessions import router as sessions_router
from backend.apps.orchestrator.api.stream import router as stream_router
from backend.apps.orchestrator.config import APP_NAME, APP_VERSION, CORS_ORIGINS

app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(orchestrate_router)
app.include_router(stream_router)
app.include_router(sessions_router)
app.include_router(rag_router)
```

## M.4 `backend/apps/orchestrator/core/intent_router.py`
```python
from __future__ import annotations

import re

from backend.platform.shared.schemas import AgentTask


def extract_entities(message: str) -> dict[str, str]:
    out: dict[str, str] = {}
    p = re.search(r"(?:project|프로젝트)\s+([a-zA-Z0-9._-]+)", message, re.IGNORECASE)
    r = re.search(r"(?:repo|repository|레포)\s+([a-zA-Z0-9._-]+)", message, re.IGNORECASE)
    g = re.search(r"(?:region|리전)\s+([a-z0-9-]+)", message, re.IGNORECASE)
    if p:
        out["project_name"] = p.group(1)
    if r:
        out["repository_name"] = r.group(1)
    if g:
        out["region"] = g.group(1)
    return out


def analyze_intent(message: str) -> tuple[str, float, dict[str, str]]:
    text = message.lower()
    entities = extract_entities(message)
    if any(k in text for k in ["jira", "github", "project", "프로젝트"]):
        return "project_setup", 0.92, entities
    if any(k in text for k in ["mdm", "디바이스", "정책"]):
        return "mdm_ops", 0.90, entities
    if any(k in text for k in ["gcp", "cloud", "인프라", "vpc"]):
        return "infra_setup", 0.91, entities
    return "general", 0.58, entities


def detect_missing_fields(intent: str, entities: dict[str, str], message: str) -> list[str]:
    msg = message.lower()
    missing: list[str] = []
    if intent == "project_setup":
        if "project_name" not in entities and "project" not in msg and "프로젝트" not in msg:
            missing.append("project_name")
        if "repository_name" not in entities and "repo" not in msg and "repository" not in msg and "레포" not in msg:
            missing.append("repository_name")
    if intent == "infra_setup":
        if "region" not in entities and "region" not in msg and "리전" not in msg:
            missing.append("region")
    return missing


def build_tasks(message: str) -> tuple[str, list[AgentTask]]:
    text = message.lower()
    if any(k in text for k in ["jira", "github", "project", "프로젝트"]):
        return "project_setup", [
            AgentTask(agent_id="jira_agent", capability="jira.project", payload={"action": "create_project"}),
            AgentTask(agent_id="github_agent", capability="github.repo", payload={"action": "create_repo"}),
        ]
    if any(k in text for k in ["mdm", "디바이스", "정책"]):
        return "mdm_ops", [
            AgentTask(agent_id="mdm_agent", capability="mdm.policy", payload={"action": "apply_policy"}),
            AgentTask(agent_id="mdm_agent", capability="mdm.device", payload={"action": "group_devices"}),
        ]
    if any(k in text for k in ["gcp", "cloud", "인프라", "vpc"]):
        return "infra_setup", [
            AgentTask(agent_id="cloud_agent", capability="cloud.compute", payload={"action": "provision_compute"}),
            AgentTask(agent_id="cloud_agent", capability="cloud.network", payload={"action": "setup_network"}),
        ]
    return "general", []
```

## M.5 `frontend/src/components/chat/ChatComposer.vue`
```vue
<script setup>
import { ref } from 'vue'

defineProps({
  isLoading: { type: Boolean, default: false },
})

const emit = defineEmits({
  send: (message) => typeof message === 'string' && message.trim().length > 0,
  newChat: () => true,
})

const message = ref('')

function submit() {
  const value = message.value.trim()
  if (!value) return
  emit('send', value)
  message.value = ''
}
</script>

<template>
  <form class="chat-form" @submit.prevent="submit">
    <label for="message">AI Command</label>
    <textarea
      id="message"
      v-model="message"
      rows="6"
      placeholder="Jira와 GitHub 프로젝트 기본 셋업해줘"
      @keydown.enter.exact.prevent="submit"
    />
    <div class="row-actions">
      <button type="submit" :disabled="isLoading || !message.trim()">{{ isLoading ? 'Running...' : 'Run' }}</button>
      <button type="button" class="secondary-button" :disabled="isLoading" @click="emit('newChat')">새 대화</button>
    </div>
  </form>
</template>
```

## M.6 `frontend/src/pages/ConsolePage.vue`
> 이 파일은 길기 때문에 핵심 포인트만 템플릿으로 제공.

```vue
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import { createChatStream } from '@/services/chatApi'
import StreamStatus from '@/stream_view/StreamStatus.vue'
import { createStreamConnection } from '@/stream_view/services/eventSourceClient'

const isLoading = ref(false)
const status = ref('idle')
const error = ref('')
const sessionId = ref('')
const intent = ref('')
const routeSource = ref('')
const planner = ref(null)
const ragHits = ref([])
const events = ref([])
const turns = ref([])
const chatWindowEl = ref(null)
let connection = null

function addTurn(role, text, meta = '', evidence = []) {
  turns.value.push({ role, text, meta, evidence, at: new Date().toISOString() })
}

watch(() => turns.value.length, async () => {
  await nextTick()
  if (chatWindowEl.value) {
    chatWindowEl.value.scrollTop = chatWindowEl.value.scrollHeight
  }
})

const routeBadgeLabel = computed(() => {
  const route = routeSource.value.toLowerCase()
  const hasRag = ragHits.value.length > 0
  const isGeneral = intent.value.toLowerCase() === 'general'
  if ((route.includes('llm') || route === 'hitl') && isGeneral && hasRag) return 'LLM General+RAG'
  if ((route.includes('llm') || route === 'hitl') && isGeneral) return 'LLM General'
  if ((route.includes('llm') || route === 'hitl') && hasRag) return 'LLM+RAG'
  if (route.includes('rule') && hasRag) return 'RULE+RAG'
  if (route.includes('llm') || route === 'hitl') return 'LLM'
  if (route.includes('rule')) return 'RULE'
  if (hasRag) return 'RAG'
  return 'Pending'
})

async function handleSend(message) {
  if (isLoading.value) return
  isLoading.value = true
  addTurn('user', message)
  const streamInfo = await createChatStream(message, sessionId.value || null)
  sessionId.value = streamInfo.session_id

  if (connection) connection.close()
  connection = createStreamConnection(streamInfo.stream_url, {
    onEvent: (event) => {
      const parsed = JSON.parse(event.data)
      events.value = [{ type: event.type, data: parsed }, ...events.value].slice(0, 30)
      if (parsed.intent) intent.value = parsed.intent
      if (parsed.route_source) routeSource.value = parsed.route_source
      if (parsed.routing_debug?.rag?.hits) ragHits.value = parsed.routing_debug.rag.hits
      if (event.type === 'progress' && parsed.phase === 'planner_completed') planner.value = parsed.plan || null
      if (event.type === 'final') {
        addTurn('assistant', parsed.clarification_question || parsed.summary || 'Done', `${parsed.intent || ''} / ${parsed.route_source || ''}`, parsed.routing_debug?.rag?.hits || [])
        isLoading.value = false
        connection?.close()
      }
    },
    onError: () => {
      error.value = 'SSE connection failed'
      isLoading.value = false
      connection?.close()
    },
  })
}

onBeforeUnmount(() => connection?.close())
</script>
```

## M.7 `docker-compose.yml` 최소 템플릿
```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/apps/orchestrator/Dockerfile
    environment:
      CORS_ORIGINS: "*"
      LLM_PROVIDER: ${LLM_PROVIDER:-openai}
      OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://api.openai.com/v1}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      LLM_ROLE_INTENT_MODEL: ${LLM_ROLE_INTENT_MODEL:-gpt-4.1-mini}
      LLM_ROLE_PLANNER_MODEL: ${LLM_ROLE_PLANNER_MODEL:-gpt-4.1}
      LLM_ROLE_SUMMARY_MODEL: ${LLM_ROLE_SUMMARY_MODEL:-gpt-4.1-mini}
      EMBEDDING_PROVIDER: ${EMBEDDING_PROVIDER:-openai}
      EMBED_BASE_URL: ${EMBED_BASE_URL:-}
      EMBED_MODEL_NAME: ${EMBED_MODEL_NAME:-}
      EMBEDDING_DIM: ${EMBEDDING_DIM:-1024}
      VECTOR_STORE_PROVIDER: ${VECTOR_STORE_PROVIDER:-pgvector}
      VECTOR_DB_DSN: ${VECTOR_DB_DSN:-postgresql://postgres:postgres@vector-db:5432/mdm}
      RAG_ENABLED: ${RAG_ENABLED:-true}
      RAG_TOP_K: ${RAG_TOP_K:-4}
      RAG_MIN_SCORE: ${RAG_MIN_SCORE:-0.35}
      RAG_AUTO_INGEST: ${RAG_AUTO_INGEST:-true}
      RAG_INGEST_CHUNK_SIZE: ${RAG_INGEST_CHUNK_SIZE:-900}
      RAG_INGEST_CHUNK_OVERLAP: ${RAG_INGEST_CHUNK_OVERLAP:-120}
      REDIS_URL: ${REDIS_URL:-redis://redis:6379/0}
      RAG_CACHE_TTL_SEC: ${RAG_CACHE_TTL_SEC:-600}
    ports:
      - "8080:8000"
    depends_on:
      - vector-db
      - redis
      - jira-agent
      - github-agent
      - cloud-agent
      - mdm-agent

  vector-db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: mdm
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres

  redis:
    image: redis:7-alpine

  jira-agent:
    build:
      context: .
      dockerfile: backend/apps/agents/jira_agent/Dockerfile

  github-agent:
    build:
      context: .
      dockerfile: backend/apps/agents/github_agent/Dockerfile

  cloud-agent:
    build:
      context: .
      dockerfile: backend/apps/agents/cloud_agent/Dockerfile

  mdm-agent:
    build:
      context: .
      dockerfile: backend/apps/agents/mdm_agent/Dockerfile

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    environment:
      API_UPSTREAM: http://backend:8000
    ports:
      - "5174:80"
    depends_on:
      - backend
```

## M.8 `backend/apps/agents/*/main.py` 공통 템플릿
```python
from fastapi import FastAPI

app = FastAPI(title='agent', version='0.1.0')


@app.post('/execute')
async def execute(payload: dict):
    task = payload.get('task', {})
    action = task.get('payload', {}).get('action', 'unknown')
    return {
        'success': True,
        'output': {
            'message': f"agent executed {action}",
            'session_id': payload.get('session_id'),
        }
    }
```

> 실제 구현 시 agent별 message 문자열만 도메인에 맞게 바꾸면 됩니다.


---
