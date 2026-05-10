import json
import os


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _json_list_env(name: str) -> list[dict[str, object]]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


APP_NAME = os.getenv("ORCHESTRATOR_APP_NAME", "mdm-ai-orchestrator")
APP_VERSION = os.getenv("ORCHESTRATOR_APP_VERSION", "0.2.0")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

AGENT_ENDPOINTS = {
    "jira_agent": os.getenv("JIRA_AGENT_URL", "http://jira-agent:8000"),
    "github_agent": os.getenv("GITHUB_AGENT_URL", "http://github-agent:8000"),
    "cloud_agent": os.getenv("CLOUD_AGENT_URL", "http://cloud-agent:8000"),
    "mdm_agent": os.getenv("MDM_AGENT_URL", "http://mdm-agent:8000"),
}
AGENT_HTTP_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "20"))
AGENT_HTTP_TRUST_ENV = _bool_env("AGENT_HTTP_TRUST_ENV", False)
CUSTOM_AGENTS = _json_list_env("CUSTOM_AGENTS_JSON")

LLM_ROLE_MODELS = {
    "intent_fallback": os.getenv("LLM_ROLE_INTENT_MODEL", "") or os.getenv("LLM_MODEL_NAME", "gpt-4.1-mini"),
    "planner": os.getenv("LLM_ROLE_PLANNER_MODEL", "") or os.getenv("LLM_MODEL_NAME", "gpt-4.1"),
    "summary": os.getenv("LLM_ROLE_SUMMARY_MODEL", "") or os.getenv("LLM_MODEL_NAME", "gpt-4.1-mini"),
}
