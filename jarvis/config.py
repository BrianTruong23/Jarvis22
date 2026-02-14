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

    # Labeling
    issue_label: str = "jarvis"
    ready_label: str = "jarvis-ready"
    done_label: str = "jarvis-done"
    needs_human_label: str = "jarvis-needs-human"

    # Model routing labels
    model_label_claude: str = "jarvis-cl"
    model_label_codex: str = "jarvis-co"
    model_label_gemini: str = "jarvis-gem"

    workspace_dir: str = "/tmp/jarvis-workspace"
    db_path: str = "jarvis.db"
    branch_prefix: str = "jarvis/issue-"

    # Agent models
    claude_model: str = "sonnet"
    codex_model: str = ""
    gemini_model: str = ""

    # Reviewer loop
    review_rounds: int = 2
    reviewer_backend_order: str = "gemini,claude,codex"

    # Optional test command run by Jarvis (not by the LLM)
    test_cmd: str = ""
    test_timeout_s: int = 900

    webhook_port: int = 8080
    webhook_secret: str = ""
    log_level: str = "INFO"
    session_timeout: int = 7200
    issue_timeout: int = 1800
    max_diff_files: int = 40
    max_diff_loc: int = 1000
    max_tokens_per_run: int = 180000
    token_warning_buffer: int = 5000
    codex_binary: str = "node /usr/lib/node_modules/@openai/codex/bin/codex.js"
    codex_model: str = "o4-mini"
    reports_dir: str = "reports"
    jarvis_repo_dir: str = ""
    publish: bool = False
    ready_label: str = "ready"

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
            ready_label=os.environ.get("READY_LABEL", "jarvis-ready"),
            done_label=os.environ.get("DONE_LABEL", "jarvis-done"),
            needs_human_label=os.environ.get("NEEDS_HUMAN_LABEL", "jarvis-needs-human"),

            model_label_claude=os.environ.get("MODEL_LABEL_CLAUDE", "jarvis-cl"),
            model_label_codex=os.environ.get("MODEL_LABEL_CODEX", "jarvis-co"),
            model_label_gemini=os.environ.get("MODEL_LABEL_GEMINI", "jarvis-gem"),

            workspace_dir=os.environ.get("WORKSPACE_DIR", "/tmp/jarvis-workspace"),
            db_path=os.environ.get("DB_PATH", "jarvis.db"),
            branch_prefix=os.environ.get("BRANCH_PREFIX", "jarvis/issue-"),

            claude_model=os.environ.get("CLAUDE_MODEL", "sonnet"),
            codex_model=os.environ.get("CODEX_MODEL", ""),
            gemini_model=os.environ.get("GEMINI_MODEL", ""),

            review_rounds=int(os.environ.get("REVIEW_ROUNDS", "2")),
            reviewer_backend_order=os.environ.get("REVIEWER_BACKEND_ORDER", "gemini,claude,codex"),

            test_cmd=os.environ.get("TEST_CMD", ""),
            test_timeout_s=int(os.environ.get("TEST_TIMEOUT_S", "900")),

            webhook_port=int(os.environ.get("WEBHOOK_PORT", "8080")),
            webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            session_timeout=int(os.environ.get("SESSION_TIMEOUT", "7200")),
            issue_timeout=int(os.environ.get("ISSUE_TIMEOUT", "1800")),
            max_diff_files=int(os.environ.get("MAX_DIFF_FILES", "40")),
            max_diff_loc=int(os.environ.get("MAX_DIFF_LOC", "1000")),
            max_tokens_per_run=int(os.environ.get("MAX_TOKENS_PER_RUN", "180000")),
            token_warning_buffer=int(os.environ.get("TOKEN_WARNING_BUFFER", "5000")),
            codex_binary=os.environ.get("CODEX_BINARY", "node /usr/lib/node_modules/@openai/codex/bin/codex.js"),
            codex_model=os.environ.get("CODEX_MODEL", "o4-mini"),
            reports_dir=os.environ.get("REPORTS_DIR", "reports"),
            jarvis_repo_dir=os.environ.get("JARVIS_REPO_DIR", ""),
            publish=os.environ.get("PUBLISH", "").lower() in ("true", "1", "yes"),
            ready_label=os.environ.get("READY_LABEL", "ready"),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.github_token:
            errors.append("GITHUB_TOKEN is required")
        if not self.target_repos:
            errors.append("TARGET_REPO is required (comma-separated for multiple)")
        for repo in self.target_repos:
            if "/" not in repo:
                errors.append(
                    f"TARGET_REPO '{repo}' must be in owner/repo format (e.g. BrianTruong23/my-project)"
                )
        return errors
