# Gemini Code Assist 재현 가이드


이 문서는 **현재 `26_Architect_Team_work-main` 프로젝트를 Gemini Code Assist로 유사하게 재현**하기 위한 실행 가이드입니다.


## 1) 목표 아키텍처


- Frontend: Vue 3 + Vite + SSE(EventSource) 기반 채팅 UI


- Backend: FastAPI 오케스트레이터


- Routing:


  - rule 기반 intent 1차 분류


  - 필요 시 LLM fallback / assist


  - general 대화는 `llm_chat` 직접 응답


- HITL:


  - 필수 엔티티 부족 시 clarification 질문


  - 같은 `session_id` 멀티턴 이어받기


- RAG:


  - pgvector 저장/검색


  - Redis 임베딩 캐시(optional)


  - routing_debug에 RAG evidence 노출


- Local 실행: docker compose


---


## 2) Gemini에게 먼저 줄 "상위 지시 프롬프트"


아래를 Gemini Code Assist에 먼저 입력하세요.


```text


You are helping me recreate an AI Agent Orchestration Console project.


Use Python FastAPI for backend and Vue 3 + Vite for frontend.


Requirements:


1) Backend endpoints:


- POST /api/orchestrate


- POST /api/stream (SSE)


- GET /api/sessions/{session_id}


- GET /api/health


- POST /api/v1/rag/documents


- POST /api/v1/rag/search


2) Intent flow:


- rule-based intent first


- if missing/uncertain, call LLM fallback


- if entities missing, ask clarification question (HITL)


- maintain session context by session_id for multi-turn


- if general intent, no agent task; call LLM chat answer directly


3) Route/debug output fields:


- route_source


- routing_debug.intent_source


- routing_debug.llm_fallback / llm_assist / planner / rag


4) RAG:


- pgvector table for documents


- embedding via OpenAI-compatible endpoint


- Redis cache for embeddings if REDIS_URL exists


- auto-ingest session turns with chunking


5) Frontend:


- center chat layout, bottom composer


- Enter to send, Shift+Enter newline


- auto-scroll to latest message


- show route badge: LLM, LLM General, RULE, RAG (+ combinations)


- show planner output panel


- show RAG evidence panel and per-assistant message evidence list


6) Infra:


- docker-compose includes backend, frontend, vector-db(pgvector), redis, and mock/simple agents


- environment-variable driven configuration for LLM/Embedding endpoints and model names


Keep code modular and production-oriented.


```


---


## 3) 구현 순서(권장)


Gemini에게 한 번에 전부 시키지 말고 아래 순서로 단계 실행하세요.


1. 프로젝트 스캐폴딩


- backend FastAPI 앱 엔트리


- frontend Vue 앱 엔트리


- docker-compose 뼈대


2. backend core 구현


- intent router (rule/llm fallback/hitl)


- session store


- orchestration service


- stream 이벤트


3. LLM adapter 공통화


- OpenAI-compatible client 1개


- role model 분기(`intent_fallback`, `planner`, `summary`)


4. RAG 구현


- pgvector repo + rag service


- rag ingest/search API


- orchestration에 rag context 주입


- auto ingest chunking


5. frontend 콘솔 구현


- chat composer + stream viewer


- route badge/상태 카드


- planner/rag evidence 패널


- Enter send + auto scroll


6. 마무리


- README 정리


- .env 샘플 정리


- compose 기준 통합 테스트


---


## 4) Gemini에게 파일 단위로 요청할 프롬프트 템플릿


아래 템플릿으로 파일별 생성/수정 요청하세요.


```text


Implement/modify file: <PATH>


Constraints:


- keep existing interfaces compatible


- no unnecessary dependencies


- return full file content


Expected behavior:


- <구체 요구사항>


After implementation, provide:


1) what changed


2) why


3) quick test command


```


예시:


```text


Implement/modify file: backend/apps/orchestrator/core/orchestration_service.py


Expected behavior:


- prepare context with rule -> llm_fallback -> llm_assist


- if missing fields remain, return needs_clarification response


- if intent general and no tasks, call llm_chat and return route_source=llm_chat


- inject rag context into planner input


- append routing_debug for rag/planner/llm


```


---


## 5) 환경변수 기준(개발 테스트)


```env


LLM_PROVIDER=openai


OPENAI_BASE_URL=http://<vllm-host>:<port>/v1


OPENAI_API_KEY=


LLM_ROLE_INTENT_MODEL=<intent-model>


LLM_ROLE_PLANNER_MODEL=<planner-model>


LLM_ROLE_SUMMARY_MODEL=<summary-model>


EMBEDDING_PROVIDER=openai


EMBED_BASE_URL=http://<embed-host>:<port>/v1


EMBED_MODEL_NAME=<embedding-model>


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


주의:


- `EMBEDDING_DIM`은 실제 임베딩 응답 차원과 반드시 일치해야 합니다.


---


## 6) docker compose 검증 시나리오


```bash


docker compose up -d --build


```


1) 헬스체크


```bash


curl -s http://localhost:8080/api/health


```


2) 일반 대화(LLM General)


```bash


curl -s -X POST http://localhost:8080/api/orchestrate \


  -H 'Content-Type: application/json' \


  -d '{"message":"너는 누구니"}'


```


기대값:


- `intent=general`


- `route_source=llm_chat`


- `summary`에 자연어 답변


3) 프로젝트 셋업(HITL)


```bash


curl -s -X POST http://localhost:8080/api/orchestrate \


  -H 'Content-Type: application/json' \


  -d '{"message":"Jira와 GitHub 프로젝트 기본 셋업해줘"}'


```


기대값:


- 부족 엔티티 있으면 `needs_clarification=true`


4) RAG 수동 적재/검색


```bash


curl -s -X POST http://localhost:8080/api/v1/rag/documents \


  -H 'Content-Type: application/json' \


  -d '{"doc_key":"setup-guide-1","content":"...","metadata":{"source":"manual"}}'


curl -s -X POST http://localhost:8080/api/v1/rag/search \


  -H 'Content-Type: application/json' \


  -d '{"query":"Jira GitHub setup","k":3,"min_score":0.1}'


```


---


## 7) 프론트 동작 체크리스트


- Enter 전송 / Shift+Enter 줄바꿈


- 새 메시지 시 자동 하단 스크롤


- route badge:


  - `LLM General`, `LLM`, `RULE`, `RAG`, `LLM+RAG`, `RULE+RAG`


- planner panel 노출


- rag evidence panel 노출


- assistant 버블 하단 evidence 노출


---


## 8) Gemini 작업 품질을 높이는 팁


- 한 번에 큰 리팩터링 요청하지 말고 "파일 단위"로 쪼개기


- 각 단계마다 `build/test command`를 반드시 요청


- "기존 인터페이스 유지"를 매번 명시


- 실패 로그를 그대로 붙여서 재요청


  - 예: `httpx.ReadTimeout`, `embedding dim mismatch`


---


## 9) 최소 재현 파일 우선순위


우선 구현해야 하는 핵심 파일(예시):


- backend


  - `backend/apps/orchestrator/main.py`


  - `backend/apps/orchestrator/api/{chat,orchestrate,stream,sessions,health,rag}.py`


  - `backend/apps/orchestrator/core/{orchestration_service,agent_executor,intent_router,session_store,registry}.py`


  - `backend/apps/orchestrator/llm/{factory,base_adapter}.py`


  - `backend/apps/orchestrator/llm/adapters/{openai_adapter,openai_compatible_client,mock_adapter}.py`


  - `backend/apps/orchestrator/rag/{service,vector_repo}.py`


- frontend


  - `frontend/src/main.js`


  - `frontend/src/App.vue`


  - `frontend/src/pages/ConsolePage.vue`


  - `frontend/src/components/chat/ChatComposer.vue`


  - `frontend/src/stream_view/StreamStatus.vue`


  - `frontend/src/services/chatApi.js`


  - `frontend/src/stream_view/services/eventSourceClient.js`


  - `frontend/src/styles/main.css`


---


## 10) 완료 기준(Definition of Done)


- `/api/orchestrate`, `/api/stream` 정상


- general 질문이 작업 태스크로 가지 않고 LLM 답변 반환


- project_setup에서 HITL 멀티턴 동작


- route_source / routing_debug 화면에서 식별 가능


- RAG ingest/search 동작


- docker compose로 로컬 재현 가능
