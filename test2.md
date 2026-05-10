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
