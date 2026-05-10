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
