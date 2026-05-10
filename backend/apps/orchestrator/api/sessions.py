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
