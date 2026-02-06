"""Claude Code CLI subprocess spawning."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from jarvis.config import Config
from jarvis.models import IssueContext

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are solving a GitHub issue. Read the issue carefully and implement the requested changes.

IMPORTANT RULES:
- Do NOT run git commands (no git add, commit, push, etc). The orchestrator handles git.
- Do NOT create pull requests.
- Focus on writing/modifying code to solve the issue.
- If you need to create new files, do so.
- If tests exist, make sure they still pass after your changes.
"""


def build_prompt(issue: IssueContext) -> str:
    return f"""\
GitHub Issue #{issue.number}: {issue.title}

{issue.body}

Solve this issue. Remember: do NOT run any git commands."""


def run_agent(config: Config, issue: IssueContext, work_dir: Path) -> str:
    prompt = build_prompt(issue)
    cmd = [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--model", config.claude_model,
        "--max-turns", "30",
    ]

    log.info("Spawning Claude Code for issue #%d in %s", issue.number, work_dir)
    log.debug("Prompt: %s", prompt[:200])

    # Inherit the current environment so Claude Code can use existing auth
    # (OAuth login via `claude login` for Claude Plus subscribers).
    # ANTHROPIC_API_KEY is passed through if set, but is not required.
    env = os.environ.copy()
    if config.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = config.anthropic_api_key

    result = subprocess.run(
        cmd,
        input=prompt,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )

    output = result.stdout
    if result.returncode != 0:
        error_msg = result.stderr or "Unknown error"
        log.error("Claude Code failed (exit %d): %s", result.returncode, error_msg[:500])
        raise RuntimeError(f"Claude Code exited with code {result.returncode}: {error_msg}")

    log.info("Claude Code completed for issue #%d (%d chars output)", issue.number, len(output))
    return output
