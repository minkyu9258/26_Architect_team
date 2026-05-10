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
