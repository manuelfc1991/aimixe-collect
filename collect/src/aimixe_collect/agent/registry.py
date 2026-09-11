"""Pick the agent provider from configuration."""
from __future__ import annotations

import shlex
import shutil
from typing import Any

from .base import AgentProvider
from .cli_agent import CliAgent, load_agent_configs
from .rule_based import RuleBasedAgent


def build_agent(agent_config: dict[str, Any]) -> AgentProvider:
    provider = str(agent_config.get("provider", "rule_based") or "rule_based")
    if provider == "rule_based":
        return RuleBasedAgent(max_queries=int(agent_config.get("max_queries", 24)))
    custom = agent_config.get("cli") or {}
    if provider == "custom" or (custom.get("command") and provider not in load_agent_configs()):
        cfg = dict(custom, name=provider if provider != "custom" else custom.get("name", "custom"))
        return CliAgent(cfg, RuleBasedAgent(max_queries=int(agent_config.get("max_queries", 24))))
    known = load_agent_configs().get(provider)
    if known is None:
        raise ValueError(f"unknown agent provider {provider!r}; known: rule_based, " + ", ".join(load_agent_configs()))
    cfg = dict(known)
    cfg.update({k: v for k, v in custom.items() if k != "name"})
    return CliAgent(cfg, RuleBasedAgent(max_queries=int(agent_config.get("max_queries", 24))))


def installed_agents() -> list[tuple[str, bool, str]]:
    """(name, installed, description) for every known CLI tool."""
    out = []
    for name, cfg in load_agent_configs().items():
        exe = shlex.split(cfg["command"])[0]
        out.append((name, shutil.which(exe) is not None, cfg.get("what", "")))
    return out
