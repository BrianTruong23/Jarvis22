"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_ISSUE_LABELS: tuple[str, ...] = ("jarvis", "jarvis-co", "jarvis-cl", "jarvis-ge")


@dataclass(frozen=True)
class Config:
    github_token: str = ""
    target_repos: tuple[str, ...] = ()
    anthropic_api_key: str = ""
    poll_interval: int = 60
    issue_labels: tuple[str, ...] = DEFAULT_ISSUE_LABELS
    done_label: str = "jarvis-done"
    workspace_dir: str = "/tmp/jarvis-workspace"
    db_path: str = "jarvis.db"
    branch_prefix: str = "jarvis/issue-"
    claude_model: str = "sonnet"
    claude_max_budget: str = "5.00"
    max_issues_per_poll: int = 1
    webhook_port: int = 8080
    webhook_secret: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Config:
        raw_repos = os.environ.get("TARGET_REPO", "")
        repos = tuple(r.strip() for r in raw_repos.split(",") if r.strip())

        raw_issue_labels = os.environ.get("ISSUE_LABELS", "").strip()
        if raw_issue_labels:
            issue_labels = tuple(l.strip() for l in raw_issue_labels.split(",") if l.strip())
        else:
            single_label = os.environ.get("ISSUE_LABEL", "").strip()
            issue_labels = (single_label,) if single_label else DEFAULT_ISSUE_LABELS

        return cls(
            github_token=os.environ.get("GITHUB_TOKEN", ""),
            target_repos=repos,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            poll_interval=int(os.environ.get("POLL_INTERVAL", "60")),
            issue_labels=issue_labels,
            done_label=os.environ.get("DONE_LABEL", "jarvis-done"),
            workspace_dir=os.environ.get("WORKSPACE_DIR", "/tmp/jarvis-workspace"),
            db_path=os.environ.get("DB_PATH", "jarvis.db"),
            branch_prefix=os.environ.get("BRANCH_PREFIX", "jarvis/issue-"),
            claude_model=os.environ.get("CLAUDE_MODEL", "sonnet"),
            claude_max_budget=os.environ.get("CLAUDE_MAX_BUDGET", "5.00"),
            max_issues_per_poll=max(1, int(os.environ.get("MAX_ISSUES_PER_POLL", "1"))),
            webhook_port=int(os.environ.get("WEBHOOK_PORT", "8080")),
            webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.github_token:
            errors.append("GITHUB_TOKEN is required")
        if not self.target_repos:
            errors.append("TARGET_REPO is required (comma-separated for multiple)")
        for repo in self.target_repos:
            if "/" not in repo:
                errors.append(f"TARGET_REPO '{repo}' must be in owner/repo format (e.g. BrianTruong23/my-project)")
        if not self.issue_labels:
            errors.append("ISSUE_LABELS must contain at least one label")
        return errors
