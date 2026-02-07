"""Data models for Jarvis22."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"


class Trigger(str, Enum):
    POLL = "poll"
    CLI = "cli"
    WEBHOOK = "webhook"


class ModelChoice(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"


# Label -> model mapping
MODEL_LABELS: dict[str, ModelChoice] = {
    "jarvis-cl": ModelChoice.CLAUDE,
    "jarvis-co": ModelChoice.CODEX,
    "jarvis-gem": ModelChoice.GEMINI,
}

# Labels that trigger immediate pickup (not waiting for CRON)
IMMEDIATE_LABELS: set[str] = {"jarvis ready", "jarvis-cl", "jarvis-co", "jarvis-gem"}

# Default fallback order when no model label is specified
DEFAULT_MODEL_ORDER: list[ModelChoice] = [
    ModelChoice.CLAUDE,
    ModelChoice.CODEX,
    ModelChoice.GEMINI,
]


class AllModelsExhausted(Exception):
    """Raised when all models in the fallback chain have failed."""
    pass


def resolve_model_order(labels: list[str]) -> list[ModelChoice]:
    """Return ordered list of models to try based on issue labels."""
    specified = [MODEL_LABELS[l] for l in labels if l in MODEL_LABELS]
    if not specified:
        return list(DEFAULT_MODEL_ORDER)
    remaining = [m for m in DEFAULT_MODEL_ORDER if m not in specified]
    return specified + remaining


def should_pickup_immediately(labels: list[str]) -> bool:
    """Return True if the issue should be picked up immediately (not just on CRON)."""
    return bool(set(labels) & IMMEDIATE_LABELS)


@dataclass
class IssueContext:
    number: int
    title: str
    body: str
    repo: str = ""
    labels: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    output: str
    agent_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    timed_out: bool = False
    rate_limited: bool = False


@dataclass
class Run:
    id: int | None
    issue_number: int
    issue_title: str
    status: RunStatus
    trigger: Trigger
    repo: str = ""
    branch: str | None = None
    pr_url: str | None = None
    error: str | None = None
    agent_output: str | None = None
    agent_name: str | None = None
    tokens_used: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
