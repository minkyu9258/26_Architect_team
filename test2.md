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

