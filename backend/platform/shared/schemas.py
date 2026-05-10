from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    planning = "planning"
    progress = "progress"
    result = "result"
    error = "error"
    final = "final"


class OrchestrateRequest(BaseModel):
    message: str | None = None
    encrypted_payload: dict[str, str] | None = None
    is_encrypted: bool = False
    session_id: str | None = None


class AgentTask(BaseModel):
    agent_id: str
    capability: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    agent_id: str
    capability: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class SessionState(BaseModel):
    session_id: str
    message: str
    masked_message: str | None = None
    intent: str
    tasks: list[AgentTask]
    results: list[AgentResult] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    clarification_attempts: dict[str, int] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "running"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SSEEvent(BaseModel):
    event: EventType
    data: dict[str, Any]


class OrchestrateResponse(BaseModel):
    success: bool
    session_id: str
    intent: str
    results: list[AgentResult]
    summary: str
    needs_clarification: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    confidence: float = 1.0
    entities: dict[str, Any] = Field(default_factory=dict)
    route_source: str = "unknown"
    routing_debug: dict[str, Any] = Field(default_factory=dict)
