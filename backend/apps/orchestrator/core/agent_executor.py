from __future__ import annotations

import asyncio
import os
from typing import Any

from backend.apps.orchestrator.agent_provider.http_client import HttpAgentProvider
from backend.apps.orchestrator.common.chat_client import ChatClient
from backend.platform.shared.schemas import AgentResult, AgentTask

_agent_provider = HttpAgentProvider()
LLM_STAGE_TIMEOUT = float(os.getenv("LLM_STAGE_TIMEOUT", "6"))


async def run_task(session_id: str, message: str, task: AgentTask) -> AgentResult:
    return await _agent_provider.execute(session_id=session_id, message=message, task=task)


async def run_parallel(session_id: str, message: str, tasks: list[AgentTask]) -> list[AgentResult]:
    return await asyncio.gather(*(run_task(session_id, message, t) for t in tasks))


async def run_parallel_stream(session_id: str, message: str, tasks: list[AgentTask]):
    pending = [asyncio.create_task(run_task(session_id, message, t)) for t in tasks]
    for completed in asyncio.as_completed(pending):
        yield await completed


async def llm_fallback_intent(message: str) -> dict[str, Any]:
    client = ChatClient()
    system_prompt = (
        "You are an intent classifier for an IT admin multi-agent system. "
        "Return strict JSON only with keys: intent, confidence, entities, reason. "
        "intent must be one of [project_setup, infra_setup, mdm_ops, general]."
    )
    try:
        result = await asyncio.wait_for(
            client.generate_json(role="intent_fallback", system_prompt=system_prompt, user_prompt=message, temperature=0.0),
            timeout=LLM_STAGE_TIMEOUT,
        )
    except Exception:
        return {"intent": "general", "confidence": 0.5, "entities": {}, "reason": "llm_timeout_or_error", "raw_response": {}}
    return {
        "intent": str(result.get("intent", "general")),
        "confidence": float(result.get("confidence", 0.5)),
        "entities": result.get("entities", {}) if isinstance(result.get("entities"), dict) else {},
        "reason": str(result.get("reason", "")),
        "raw_response": result if isinstance(result, dict) else {},
    }


async def llm_fill_missing_entities(*, intent: str, message: str, entities: dict[str, str], missing: list[str]) -> dict[str, Any]:
    if not missing:
        return {"entities": entities, "inferred_entities": {}, "raw_response": {}, "called": False}
    client = ChatClient()
    system_prompt = "Extract only missing entities for the given intent. Return strict JSON object only. Allowed keys: project_name, repository_name, region."
    user_prompt = f"intent={intent}\ncurrent_entities={entities}\nmissing={missing}\nmessage={message}\nIf uncertain, return empty JSON {{}}."
    try:
        inferred = await asyncio.wait_for(
            client.generate_json(role="intent_fallback", system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.0),
            timeout=LLM_STAGE_TIMEOUT,
        )
    except Exception:
        inferred = {}
    merged = dict(entities)
    inferred_entities: dict[str, str] = {}
    if isinstance(inferred, dict):
        for key in ("project_name", "repository_name", "region"):
            value = inferred.get(key)
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()
                inferred_entities[key] = value.strip()
    return {"entities": merged, "inferred_entities": inferred_entities, "raw_response": inferred if isinstance(inferred, dict) else {}, "called": True}


async def llm_build_plan(*, message: str, intent: str, entities: dict[str, str], tasks: list[AgentTask]) -> dict[str, Any]:
    client = ChatClient()
    system_prompt = "You are a planning node for an IT multi-agent workflow. Return strict JSON with keys: plan_title, steps(array), assumptions(array), missing_inputs(array)."
    user_prompt = f"message={message}\nintent={intent}\nentities={entities}\ntasks={[t.model_dump() for t in tasks]}"
    try:
        return await asyncio.wait_for(
            client.generate_json(role="planner", system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.0),
            timeout=LLM_STAGE_TIMEOUT,
        )
    except Exception:
        return {
            "plan_title": f"{intent} execution plan",
            "steps": [f"Run {t.agent_id}:{t.capability}" for t in tasks],
            "assumptions": [],
            "missing_inputs": [],
        }


async def llm_chat_answer(message: str) -> dict[str, Any]:
    client = ChatClient()
    system_prompt = (
        "You are a concise helpful assistant for an enterprise AI orchestration console. "
        "Return strict JSON only with keys: answer, intent. "
        "intent should be one of [project_setup, infra_setup, mdm_ops, general]."
    )
    try:
        result = await asyncio.wait_for(
            client.generate_json(role="summary", system_prompt=system_prompt, user_prompt=message, temperature=0.2),
            timeout=LLM_STAGE_TIMEOUT,
        )
    except Exception:
        return {"answer": "질문을 이해했지만 현재 답변 생성에 실패했습니다. 다시 시도해 주세요.", "intent": "general"}
    answer = str(result.get("answer", "")).strip()
    if not answer:
        answer = "질문을 이해했지만 현재 답변 생성에 실패했습니다. 다시 시도해 주세요."
    return {"answer": answer, "intent": str(result.get("intent", "general"))}
