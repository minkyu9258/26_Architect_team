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
