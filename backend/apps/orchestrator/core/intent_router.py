from __future__ import annotations

import re

from backend.platform.shared.schemas import AgentTask


def extract_entities(message: str) -> dict[str, str]:
    out: dict[str, str] = {}
    p = re.search(r"(?:project|프로젝트)\s+([a-zA-Z0-9._-]+)", message, re.IGNORECASE)
    r = re.search(r"(?:repo|repository|레포)\s+([a-zA-Z0-9._-]+)", message, re.IGNORECASE)
    g = re.search(r"(?:region|리전)\s+([a-z0-9-]+)", message, re.IGNORECASE)
    if p:
        out["project_name"] = p.group(1)
    if r:
        out["repository_name"] = r.group(1)
    if g:
        out["region"] = g.group(1)
    return out


def analyze_intent(message: str) -> tuple[str, float, dict[str, str]]:
    text = message.lower()
    entities = extract_entities(message)
    if any(k in text for k in ["jira", "github", "project", "프로젝트"]):
        return "project_setup", 0.92, entities
    if any(k in text for k in ["mdm", "디바이스", "정책"]):
        return "mdm_ops", 0.90, entities
    if any(k in text for k in ["gcp", "cloud", "인프라", "vpc"]):
        return "infra_setup", 0.91, entities
    return "general", 0.58, entities


def detect_missing_fields(intent: str, entities: dict[str, str], message: str) -> list[str]:
    msg = message.lower()
    missing: list[str] = []
    if intent == "project_setup":
        if "project_name" not in entities and "project" not in msg and "프로젝트" not in msg:
            missing.append("project_name")
        if "repository_name" not in entities and "repo" not in msg and "repository" not in msg and "레포" not in msg:
            missing.append("repository_name")
    if intent == "infra_setup":
        if "region" not in entities and "region" not in msg and "리전" not in msg:
            missing.append("region")
    return missing


def build_tasks(message: str) -> tuple[str, list[AgentTask]]:
    text = message.lower()
    if any(k in text for k in ["jira", "github", "project", "프로젝트"]):
        return "project_setup", [
            AgentTask(agent_id="jira_agent", capability="jira.project", payload={"action": "create_project"}),
            AgentTask(agent_id="github_agent", capability="github.repo", payload={"action": "create_repo"}),
        ]
    if any(k in text for k in ["mdm", "디바이스", "정책"]):
        return "mdm_ops", [
            AgentTask(agent_id="mdm_agent", capability="mdm.policy", payload={"action": "apply_policy"}),
            AgentTask(agent_id="mdm_agent", capability="mdm.device", payload={"action": "group_devices"}),
        ]
    if any(k in text for k in ["gcp", "cloud", "인프라", "vpc"]):
        return "infra_setup", [
            AgentTask(agent_id="cloud_agent", capability="cloud.compute", payload={"action": "provision_compute"}),
            AgentTask(agent_id="cloud_agent", capability="cloud.network", payload={"action": "setup_network"}),
        ]
    return "general", []
