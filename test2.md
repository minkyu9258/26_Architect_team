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
