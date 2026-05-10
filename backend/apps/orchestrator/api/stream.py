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
