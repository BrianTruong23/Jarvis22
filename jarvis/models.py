"""Data models for Jarvis22."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Trigger(str, Enum):
    POLL = "poll"
    CLI = "cli"
    WEBHOOK = "webhook"


@dataclass
class IssueContext:
    number: int
    title: str
    body: str
    repo: str = ""
    labels: list[str] = field(default_factory=list)


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
    created_at: str | None = None
    updated_at: str | None = None
