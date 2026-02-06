"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    github_token: str = ""
    target_repos: tuple[str, ...] = ()
    anthropic_api_key: str = ""
    poll_interval: int = 60
    issue_label: str = "jarvis"
    done_label: str = "jarvis-done"
    workspace_dir: str = "/tmp/jarvis-workspace"
    db_path: str = "jarvis.db"
    branch_prefix: str = "jarvis/issue-"
    claude_model: str = "sonnet"
    claude_max_budget: str = "5.00"
    webhook_port: int = 8080
    webhook_secret: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Config:
        raw_repos = os.environ.get("TARGET_REPO", "")
        repos = tuple(r.strip() for r in raw_repos.split(",") if r.strip())
        return cls(
            github_token=os.environ.get("GITHUB_TOKEN", ""),
            target_repos=repos,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            poll_interval=int(os.environ.get("POLL_INTERVAL", "60")),
            issue_label=os.environ.get("ISSUE_LABEL", "jarvis"),
            done_label=os.environ.get("DONE_LABEL", "jarvis-done"),
            workspace_dir=os.environ.get("WORKSPACE_DIR", "/tmp/jarvis-workspace"),
            db_path=os.environ.get("DB_PATH", "jarvis.db"),
            branch_prefix=os.environ.get("BRANCH_PREFIX", "jarvis/issue-"),
            claude_model=os.environ.get("CLAUDE_MODEL", "sonnet"),
            claude_max_budget=os.environ.get("CLAUDE_MAX_BUDGET", "5.00"),
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
        return errors
