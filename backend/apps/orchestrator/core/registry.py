from __future__ import annotations

from backend.apps.orchestrator.config import AGENT_ENDPOINTS, CUSTOM_AGENTS


def get_agent_registry() -> dict[str, str]:
    out = dict(AGENT_ENDPOINTS)
    for item in CUSTOM_AGENTS:
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if name and url:
            out[name] = url
    return out
