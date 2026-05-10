from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.apps.orchestrator.rag.service import RagService

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])
_service = RagService()


class RagIngestRequest(BaseModel):
    doc_key: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagSearchRequest(BaseModel):
    query: str
    k: int = 4
    min_score: float = 0.35


@router.post("/documents")
async def ingest_document(req: RagIngestRequest):
    try:
        return await _service.ingest(doc_key=req.doc_key, content=req.content, metadata=req.metadata)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/search")
async def search_documents(req: RagSearchRequest):
    try:
        hits = await _service.search(query=req.query, k=req.k, min_score=req.min_score)
        return {"count": len(hits), "hits": hits}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
