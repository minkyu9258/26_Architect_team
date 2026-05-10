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
