# Gemini Code Assist용 구현 명세서 (재현용 상세판)

이 문서는 Gemini Code Assist가 **이 프로젝트를 거의 그대로 재현**할 수 있도록 작성한 상세 구현 명세입니다.

목표: Gemini가 이 문서만 보고도 다음을 구현할 수 있어야 합니다.
- FastAPI 오케스트레이터 백엔드
- Vue 3 + SSE 프론트엔드 콘솔
- Rule/LLM/HITL 라우팅
- RAG(pgvector) + Redis 캐시
- Docker Compose 실행

---

## A. 작업 원칙 (Gemini에 먼저 전달)

아래 프롬프트를 Gemini에 먼저 입력하세요.

```text
You are implementing a production-like AI Orchestration Console.
Follow the specification exactly.

Hard constraints:
1) Keep API contracts and field names exactly as provided.
2) Use Python FastAPI backend and Vue 3 frontend.
3) Use SSE for stream events.
4) For general intent, do not execute agent tasks; return llm_chat response.
5) Include route_source and routing_debug in final responses.
6) Implement RAG with pgvector and optional Redis embedding cache.
7) Keep code modular and environment-variable driven.

When editing files:
- Return full file content.
- Do not rename endpoints.
- Do not change response field names.
- Add concise comments only where necessary.
```

---

## B. 최종 파일 트리

아래 구조를 기준으로 구현합니다.

```text
26_Architect_Team_work-main/
├── docker-compose.yml
├── .env
├── README.md
├── backend/
│   ├── platform/
│   │   └── shared/
│   │       └── schemas.py
│   └── apps/
│       ├── agents/
│       │   ├── jira_agent/main.py
│       │   ├── github_agent/main.py
│       │   ├── cloud_agent/main.py
│       │   └── mdm_agent/main.py
│       └── orchestrator/
│           ├── Dockerfile
│           ├── requirements.txt
│           ├── main.py
│           ├── config.py
│           ├── dependencies.py
│           ├── lifecycle.py
│           ├── api/
│           │   ├── chat.py
│           │   ├── orchestrate.py
│           │   ├── stream.py
│           │   ├── sessions.py
│           │   ├── health.py
│           │   └── rag.py
│           ├── common/
│           │   └── chat_client.py
│           ├── core/
│           │   ├── intent_router.py
│           │   ├── agent_executor.py
│           │   ├── orchestration_service.py
│           │   ├── session_store.py
│           │   └── registry.py
│           ├── agent_provider/
│           │   ├── base.py
│           │   └── http_client.py
│           ├── llm/
│           │   ├── base_adapter.py
│           │   ├── factory.py
│           │   └── adapters/
│           │       ├── mock_adapter.py
│           │       ├── openai_adapter.py
│           │       └── openai_compatible_client.py
│           ├── llm_gateway/
│           │   └── gateway.py
│           ├── intent/
│           │   ├── preprocessor.py
│           │   ├── fallback/
│           │   │   ├── feedback_store.py
│           │   │   └── llm_fallback_router.py
│           │   ├── rule/
│           │   │   ├── rule_loader.py
│           │   │   ├── rule_router.py
│           │   │   └── rules.yaml
│           │   └── semantic/
│           │       ├── embedding_adapter.py
│           │       ├── embedding_cache.py
│           │       └── vector_store.py
│           ├── rag/
│           │   ├── vector_repo.py
│           │   └── service.py
│           ├── streaming/
│           │   ├── event_schema.py
│           │   ├── sse_emitter.py
│           │   └── stream_manager.py
│           └── security/
│               └── crypto.py
└── frontend/
    ├── Dockerfile
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.js
        ├── App.vue
        ├── pages/
        │   └── ConsolePage.vue
        ├── components/
        │   └── chat/
        │       └── ChatComposer.vue
        ├── services/
        │   └── chatApi.js
        ├── stream_view/
        │   ├── StreamStatus.vue
        │   └── services/
        │       └── eventSourceClient.js
        └── styles/
            └── main.css
```

---

## C. API 계약 (절대 변경 금지)

## C.1 `POST /api/orchestrate`
Request:
```json
{
  "message": "Jira와 GitHub 프로젝트 기본 셋업해줘",
  "session_id": "optional",
  "is_encrypted": false,
  "encrypted_payload": null
}
```

Response (예시):
```json
{
  "success": true,
  "session_id": "uuid",
  "intent": "project_setup",
  "results": [],
  "summary": "...",
  "needs_clarification": true,
  "missing_fields": ["repository_name"],
  "clarification_question": "레포지토리 이름을 알려주세요.",
  "confidence": 0.95,
  "entities": {},
  "route_source": "rule+llm_assist",
  "routing_debug": {
    "intent": "project_setup",
    "intent_source": "llm_fallback",
    "llm_fallback": {},
    "llm_assist": {},
    "planner": {},
    "rag": {
      "enabled": true,
      "count": 1,
      "hits": [
        {"doc_key": "...", "score": 0.81, "metadata": {"source": "manual"}}
      ]
    }
  }
}
```

## C.2 `POST /api/stream` (SSE)
- 이벤트 타입: `progress`, `planning`, `result`, `final`, `error`
- 최종 `final`의 data는 orchestrate와 동일 스키마

## C.3 `POST /api/v1/chat/streams`
Request:
```json
{"message":"...","session_id":"optional"}
```
Response:
```json
{
  "stream_id": "uuid",
  "session_id": "uuid",
  "stream_url": "/api/v1/chat/streams/{stream_id}/events"
}
```

## C.4 `GET /api/v1/chat/streams/{stream_id}/events`
- `text/event-stream`으로 stream 전달

## C.5 `POST /api/v1/rag/documents`
```json
{"doc_key":"setup-guide-1","content":"...","metadata":{"source":"manual"}}
```

## C.6 `POST /api/v1/rag/search`
```json
{"query":"Jira setup", "k":4, "min_score":0.35}
```

## D. Backend 구현 상세

## D.1 `backend/platform/shared/schemas.py`
Pydantic 모델 정의:
- `EventType`: `planning|progress|result|error|final`
- `OrchestrateRequest`
- `AgentTask`
- `AgentResult`
- `SessionState`
- `SSEEvent`
- `OrchestrateResponse`

필드명은 C 섹션 계약과 동일.

## D.2 `config.py`
필수 env:
- `APP_NAME`, `APP_VERSION`, `CORS_ORIGINS`
- `LLM_ROLE_MODELS = {intent_fallback, planner, summary}`
- `AGENT_ENDPOINTS`
- `AGENT_HTTP_TIMEOUT`, `AGENT_HTTP_TRUST_ENV`
- `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`

## D.3 `main.py`
- FastAPI 생성
- CORS 미들웨어
- 라우터 include 순서:
  1. health
  2. chat
  3. orchestrate
  4. stream
  5. sessions
  6. rag

## D.4 `core/intent_router.py`
### 함수
1) `extract_entities(message)`
- regex로 추출:
  - `project_name`: `(project|프로젝트) <name>`
  - `repository_name`: `(repo|repository|레포) <name>`
  - `region`: `(region|리전) <name>`

2) `analyze_intent(message)`
- 키워드 기반 반환:
  - project: jira/github/project/프로젝트
  - mdm: mdm/디바이스/정책
  - infra: gcp/cloud/인프라/vpc
  - else: general

3) `detect_missing_fields(intent, entities, message)`
- `project_setup`: project_name, repository_name
- `infra_setup`: region

4) `build_tasks(message)`
- project_setup: jira.project(create_project), github.repo(create_repo)
- infra_setup: cloud.compute, cloud.network
- mdm_ops: mdm.policy, mdm.device
- `general`: 빈 list (`[]`) **반드시**

## D.5 `core/agent_executor.py`
필수 함수:
- `run_task`, `run_parallel`, `run_parallel_stream`
- `llm_fallback_intent`
- `llm_fill_missing_entities`
- `llm_build_plan`
- `llm_chat_answer`

`llm_chat_answer` 스펙:
- system prompt로 JSON 강제
- 반환 키: `answer`, `intent`
- timeout 시 fallback 답변 문자열 반환

## D.6 `core/orchestration_service.py` (핵심)

### 흐름

1) `_prepare_context(request)`
- 메시지 resolve
- session 조회
- 이전 상태가 clarification이면 멀티턴 결합
- rule intent 분석
- missing이면 llm fallback
- 여전히 missing이면 llm assist
- history 업데이트

2) RAG 컨텍스트 주입
- `RAG_ENABLED=true`면 `RagService.search`
- `routing_debug.rag` 채움
- hit 있을 때 message에 `[RAG_CONTEXT]` 문자열 append

3) clarification 처리
- missing 남으면 `needs_clarification=true`
- 질문 생성 `_clarification_question`
- session 저장
- `RAG_AUTO_INGEST=true`면 clarification 턴도 ingest

4) `general` 처리
- `if intent == general and tasks == []`:
  - `llm_chat_answer`
  - `route_source = llm_chat`
  - `planner = {skipped: true, reason: general_chat}`

5) 일반 task 처리
- planner 생성
- agent 병렬 실행
- summary 생성

6) `_build_summary`
- 단순 task count 문구 금지
- agent별 요약 문구 생성:
  - `- jira_agent (jira.project) 실행 완료: key=value...`

### 필수 route_source 규칙
- `rule`
- `rule->llm_fallback`
- `rule+llm_assist`
- `hitl`
- `llm_chat`

## D.7 `rag/vector_repo.py`
- pgvector extension/table 생성
- table: `rag_documents`
  - `doc_key unique`
  - `content`
  - `metadata jsonb`
  - `embedding vector(EMBEDDING_DIM)`

- `upsert_document`
- `search` (cosine 유사도)

## D.8 `rag/service.py`
- embed adapter 사용
- 캐시 계층:
  1. in-memory dict
  2. `REDIS_URL` 있으면 redis get/setex
- search 시 `min_score` 필터

## D.9 Auto ingest chunking
`orchestration_service.py`에 구현:
- `RAG_INGEST_CHUNK_SIZE`
- `RAG_INGEST_CHUNK_OVERLAP`
- `_split_text_chunks()`
- `_ingest_chunked_document()`

metadata에 포함:
- `source=chat_session`
- `session_id`
- `intent`
- `route_source`
- `status`
- `chunk_index`, `chunk_total`

---
## E. LLM 계층 상세

## E.1 `llm/adapters/openai_compatible_client.py`
- base_url 우선순위:
  - 모델별 env -> OPENAI_BASE_URL/LLM_BASE_URL
- header: api key 있으면 Bearer
- timeout/retry 적용
- `LLM_BYPASS_PROXY=true`면 `trust_env=False`

## E.2 `llm/adapters/openai_adapter.py`
- `/responses` 먼저 시도
- 실패 시 `/chat/completions` fallback
- 결과는 JSON dict로 반환

## E.3 `llm/factory.py`
- provider:
  - `openai` or `openai_compat` -> OpenAIAdapter
  - else -> MockAdapter

## E.4 `llm_gateway/gateway.py`
- role별 모델 분기:
  - intent_fallback
  - planner
  - summary

---

## F. Frontend 구현 상세

## F.1 `src/main.js`, `src/App.vue`
- `main.js`에서 `createApp(App).mount('#root')`
- `App.vue`는 `<ConsolePage />`

## F.2 `src/services/chatApi.js`
함수:
- `createChatStream(message, sessionId)`
  - `POST /api/v1/chat/streams`

## F.3 `src/stream_view/services/eventSourceClient.js`
함수:
- `createStreamConnection(url, {onOpen,onEvent,onError})`
- 이벤트 리스닝:
  - `progress`, `planning`, `result`, `final`, `error`

## F.4 `src/components/chat/ChatComposer.vue`
요구사항:
- Enter 전송
- Shift+Enter 줄바꿈
- 새 대화 버튼

핵심:
```vue
@keydown.enter.exact.prevent="submit"
```

## F.5 `src/pages/ConsolePage.vue` (핵심)
상태:
- `sessionId`, `intent`, `routeSource`
- `planner`, `ragHits`
- `turns` (chat bubble)
- `events`

동작:
1. send -> `createChatStream`
2. stream 연결
3. event 처리
- `progress`: 상태/메시지 반영
- `planning`: task count
- `result`: result count 증가
- `final`: assistant 메시지 + evidence 추가

4. auto-scroll
```js
watch(() => turns.value.length, async () => {
  await nextTick()
  chatWindowEl.value.scrollTop = chatWindowEl.value.scrollHeight
})
```

5. route badge 계산 로직
- 일반대화(LLM general):
  - `LLM General`
  - `LLM General+RAG`
- 기타:
  - `LLM`, `RULE`, `RAG`, `LLM+RAG`, `RULE+RAG`

## F.6 `src/stream_view/StreamStatus.vue`
- 단계 표시(stepper)
- 최근 SSE events 표시

## F.7 `src/styles/main.css`
필수 스타일 블록:
- shell, panel, cards
- chat bubble(user/assistant/system)
- route badge
- planner panel
- rag list
- stream panel/stepper

---

## G. Docker/환경 구성

## G.1 `backend/apps/orchestrator/requirements.txt`
최소:
- fastapi
- uvicorn
- pydantic
- httpx
- psycopg[binary]
- redis
- python-dotenv
- PyYAML
- cryptography

## G.2 `docker-compose.yml`
서비스:
- backend (8000 내부, 8080 외부)
- frontend (80 내부, 5174 외부)
- vector-db (pgvector)
- redis
- jira-agent/github-agent/cloud-agent/mdm-agent

backend env 필수:
- LLM/Embedding/RAG/Redis 관련 모든 env

## G.3 `.env` 샘플
```env
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://<vllm-host>:<port>/v1
OPENAI_API_KEY=
LLM_ROLE_INTENT_MODEL=<model>
LLM_ROLE_PLANNER_MODEL=<model>
LLM_ROLE_SUMMARY_MODEL=<model>

EMBEDDING_PROVIDER=openai
EMBED_BASE_URL=http://<embed-host>:<port>/v1
EMBED_MODEL_NAME=<embed-model>
EMBEDDING_DIM=<actual-dim>

VECTOR_STORE_PROVIDER=pgvector
VECTOR_DB_DSN=postgresql://postgres:postgres@vector-db:5432/mdm

RAG_ENABLED=true
RAG_TOP_K=4
RAG_MIN_SCORE=0.35
RAG_AUTO_INGEST=true
RAG_INGEST_CHUNK_SIZE=900
RAG_INGEST_CHUNK_OVERLAP=120

REDIS_URL=redis://redis:6379/0
RAG_CACHE_TTL_SEC=600

LLM_HTTP_TIMEOUT=20
LLM_HTTP_MAX_RETRIES=0
LLM_BYPASS_PROXY=true
```

중요:
- `EMBEDDING_DIM`은 서버 실제 임베딩 벡터 차원과 동일해야 함.

---

## H. Gemini 단계별 작업 스크립트

아래를 Gemini에 순서대로 넣으세요.

## Step 1: 백엔드 뼈대
```text
Create backend FastAPI app with routes: /api/orchestrate, /api/stream, /api/sessions/{id}, /api/health, /api/v1/rag/documents, /api/v1/rag/search, and /api/v1/chat/streams.
Implement Pydantic schemas exactly as specified.
Return full contents for all created files.
```

## Step 2: intent + orchestration
```text
Implement intent_router and orchestration_service with:
- rule intent
- llm fallback
- llm assist
- hitl clarification
- session-based multi-turn
- route_source and routing_debug fields
General intent must produce llm_chat response with no agent tasks.
```

## Step 3: LLM adapter
```text
Implement OpenAI-compatible adapter with /responses first and /chat/completions fallback.
Use role-based model selection in gateway.
```

## Step 4: RAG
```text
Implement pgvector repo and rag service.
Add rag ingest/search endpoints.
Inject rag context into orchestration planning input.
Add auto-ingest chunking for session turns.
```

## Step 5: Frontend
```text
Implement Vue ConsolePage with chat bubbles, SSE stream handling, planner panel, rag evidence panel, and route badges.
Support Enter-to-send, Shift+Enter newline, and auto-scroll.
```

## Step 6: Compose + verify
```text
Implement docker-compose for backend/frontend/redis/vector-db/agents.
Provide exact commands to run and verify all key scenarios.
```

---

## I. 검증 시나리오 (필수)

```bash
docker compose up -d --build
curl -s http://localhost:8080/api/health
```

### I.1 일반대화
```bash
curl -s -X POST http://localhost:8080/api/orchestrate \
  -H 'Content-Type: application/json' \
  -d '{"message":"너는 누구니"}'
```
기대:
- `intent=general`
- `route_source=llm_chat`
- summary에 일반 답변

### I.2 프로젝트 셋업
```bash
curl -s -X POST http://localhost:8080/api/orchestrate \
  -H 'Content-Type: application/json' \
  -d '{"message":"Jira와 GitHub 프로젝트 기본 셋업해줘"}'
```
기대:
- missing이면 clarification
- 충분하면 agent 실행 summary

### I.3 RAG 수동
```bash
curl -s -X POST http://localhost:8080/api/v1/rag/documents \
  -H 'Content-Type: application/json' \
  -d '{"doc_key":"setup-guide-1","content":"Jira와 GitHub setup 가이드","metadata":{"source":"manual"}}'

curl -s -X POST http://localhost:8080/api/v1/rag/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Jira GitHub setup","k":3,"min_score":0.1}'
```

### I.4 Redis 캐시
```bash
docker exec <redis-container> redis-cli --scan | head
```
기대:
- `rag:emb:*` key 존재

---

## J. 완료 기준 (Definition of Done)

1. 모든 필수 API 동작
2. `general`이 task 실행되지 않고 `llm_chat`
3. `route_source`, `routing_debug` 필드 정확
4. RAG hit가 응답/화면에 표시
5. Enter 전송 + auto scroll 동작
6. Docker Compose로 즉시 재현 가능

---

## K. 트러블슈팅

### K.1 `httpx.ReadTimeout`
- timeout 축소/재시도 조정
- proxy/no_proxy 확인
- LLM endpoint 헬스 점검

### K.2 `embedding dim mismatch`
- `EMBEDDING_DIM`을 실제 반환 차원으로 수정
- 필요 시 rag table 재생성

### K.3 SSE 안보임
- stream endpoint 경로 확인
- EventSource event type 매핑 확인
- nginx proxy buffering 비활성화 확인

---

## L. Gemini에게 마지막 품질 점검 요청 문구

```text
Before finalizing, run a self-check against this spec:
- API contracts exact?
- general -> llm_chat only?
- route_source/routing_debug present?
- rag evidence exposed?
- frontend enter/shift-enter/autoscroll implemented?
- docker compose starts all services?
Return a checklist with pass/fail per item.
```


---

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
## R. DevOps_Support LLM/Embedding 연결 방법 (docker compose 기준)

대상:
- LLM: `gemma-2-2b-it` (`2b_it_v2.gguf`)
- Embedding: `BAAI/bge-m3`
- 참조 차트 경로: `~/project/2026/team_architect/26_Architect_Team_work_DevOps_Support/charts/architect-chatbot-api`

차트 기본 포트(확인됨):
- LLM service port: `8080`
- Embedding service port: `8081`

### R.1 핵심 원칙

`26_Architect_Team_work-main`의 `backend` 컨테이너가 접근 가능한 URL을 `.env`에 넣어야 한다.

- 가능: 실제 노드 IP, LB 도메인, `host.docker.internal`(환경 지원 시)
- 주의: `localhost`는 컨테이너 내부 localhost라서 대부분 실패

### R.2 `.env` 설정 예시

`/home/sds/project/2026/team_architect/26_Architect_Team_work-main/.env`

```env
# LLM
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://<LLM접속주소>:8080/v1
OPENAI_API_KEY=

# role model (반드시 /v1/models 결과의 id로 설정)
LLM_ROLE_INTENT_MODEL=<LLM_MODEL_ID>
LLM_ROLE_PLANNER_MODEL=<LLM_MODEL_ID>
LLM_ROLE_SUMMARY_MODEL=<LLM_MODEL_ID>

# Embedding
EMBEDDING_PROVIDER=openai
EMBED_BASE_URL=http://<EMBED접속주소>:8081/v1
EMBED_MODEL_NAME=BAAI/bge-m3

# bge-m3 일반 차원
EMBEDDING_DIM=1024

# RAG
RAG_ENABLED=true
VECTOR_STORE_PROVIDER=pgvector
VECTOR_DB_DSN=postgresql://postgres:postgres@vector-db:5432/mdm
```

### R.3 모델 ID 확인 방법

LLM 모델명은 추측하지 말고 반드시 조회해서 넣는다.

```bash
curl -s http://<LLM접속주소>:8080/v1/models
```

응답의 `data[].id` 값을 `LLM_ROLE_*_MODEL`에 동일하게 넣는다.

### R.4 컨테이너 내부 네트워크 확인

`backend` 컨테이너 내부에서 직접 호출이 되는지 먼저 확인한다.

```bash
docker exec -it 26_architect_team_work-main-backend-1 sh -lc "wget -qO- http://<LLM접속주소>:8080/v1/models | head"
docker exec -it 26_architect_team_work-main-backend-1 sh -lc "wget -qO- http://<EMBED접속주소>:8081/v1/models | head"
```

위 명령이 실패하면 URL/방화벽/라우팅 문제이므로 앱 설정 문제가 아니다.

### R.5 docker compose 재기동

```bash
cd /home/sds/project/2026/team_architect/26_Architect_Team_work-main
docker compose up -d --build
```

### R.6 최소 동작 점검

```bash
# health
curl -s http://localhost:8080/api/health

# general llm chat
curl -s -X POST http://localhost:8080/api/orchestrate \
  -H 'Content-Type: application/json' \
  -d '{"message":"너는 누구니"}'

# rag ingest/search
curl -s -X POST http://localhost:8080/api/v1/rag/documents \
  -H 'Content-Type: application/json' \
  -d '{"doc_key":"setup-guide-1","content":"Jira GitHub setup guide","metadata":{"source":"manual"}}'

curl -s -X POST http://localhost:8080/api/v1/rag/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Jira GitHub setup","k":3,"min_score":0.1}'
```

### R.7 자주 나는 오류와 해결

1) `httpx.ConnectTimeout` / `httpx.ReadTimeout`
- 원인: URL 불가, 프록시/방화벽, LLM 서버 과부하
- 조치:
  - `LLM_HTTP_TIMEOUT` 값 증가
  - `LLM_HTTP_MAX_RETRIES` 조정
  - 프록시 사용 시 `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `LLM_BYPASS_PROXY` 점검

2) `embedding dim mismatch`
- 원인: `EMBEDDING_DIM`과 실제 임베딩 차원 불일치
- 조치:
  - 실제 차원 확인 후 `.env` 수정
  - 필요 시 `rag_documents` 테이블 재생성

3) general 질문이 task로 실행됨
- 원인: `intent_router.build_tasks()`에서 general이 빈 배열이 아님
- 조치:
  - general은 반드시 `[]` 반환
  - orchestrator에서 `intent=general and tasks empty -> llm_chat` 분기 확인
