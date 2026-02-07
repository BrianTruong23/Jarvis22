"""Claude Code / Codex CLI subprocess spawning with fallback."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from pathlib import Path

from jarvis.config import Config
from jarvis.models import AgentResult, IssueContext

log = logging.getLogger(__name__)


class RateLimitError(RuntimeError):
    """Raised when Claude hits a rate limit."""


class AgentTimeoutError(RuntimeError):
    """Raised when an agent exceeds its time budget."""

    def __init__(self, partial_output: str, agent_name: str, elapsed: float) -> None:
        self.partial_output = partial_output
        self.agent_name = agent_name
        self.elapsed = elapsed
        super().__init__(f"{agent_name} timed out after {elapsed:.0f}s")


SYSTEM_PROMPT = """\
You are solving a GitHub issue. Read the issue carefully and implement the requested changes.

IMPORTANT RULES:
- Do NOT run git commands (no git add, commit, push, etc). The orchestrator handles git.
- Do NOT create pull requests.
- Do NOT merge to main.
- Focus on writing/modifying code to solve the issue.
- If you need to create new files, do so.
- Always run tests after your changes, or explain why tests cannot be run.
- If you are blocked and cannot proceed, output a line starting with "BLOCKED:" followed by one precise question. Do NOT guess.
- Keep changes minimal and focused on the issue.
"""


def build_prompt(issue: IssueContext) -> str:
    return f"""\
GitHub Issue #{issue.number}: {issue.title}

{issue.body}

Solve this issue. Remember: do NOT run any git commands. Run tests if possible."""


def _run_claude(config: Config, issue: IssueContext, work_dir: Path) -> AgentResult:
    """Run Claude Code CLI with JSON output for token tracking."""
    prompt = build_prompt(issue)
    cmd = [
        "claude",
        "--print",
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--model", config.claude_model,
        "--max-turns", "30",
    ]
    log.info("Trying Claude in %s", work_dir)
    result = subprocess.run(
        cmd,
        input=prompt,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude exited with code {result.returncode}: {result.stderr or 'Unknown error'}")
    return result.stdout

    log.info("Spawning Claude Code for issue #%d in %s", issue.number, work_dir)

    env = os.environ.copy()
    if config.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = config.anthropic_api_key

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=config.issue_timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or "") if isinstance(e.stdout, str) else (e.stdout or b"").decode(errors="replace")
        raise AgentTimeoutError(partial, "claude", config.issue_timeout)

    stderr = result.stderr or ""

    # Detect rate limits
    if result.returncode != 0:
        stderr_lower = stderr.lower()
        if "rate limit" in stderr_lower or "429" in stderr_lower or "too many requests" in stderr_lower:
            log.warning("Claude hit rate limit: %s", stderr[:300])
            raise RateLimitError(f"Claude rate limited: {stderr[:300]}")
        error_msg = stderr or "Unknown error"
        log.error("Claude Code failed (exit %d): %s", result.returncode, error_msg[:500])
        raise RuntimeError(f"Claude Code exited with code {result.returncode}: {error_msg}")

    # Parse JSON output for token tracking
    raw_output = result.stdout
    output_text = raw_output
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0

    try:
        data = json.loads(raw_output)
        # Claude --output-format json returns { result: str, ... usage info }
        if isinstance(data, dict):
            output_text = data.get("result", raw_output)
            usage = data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            total_tokens = input_tokens + output_tokens
    except (json.JSONDecodeError, TypeError):
        output_text = raw_output

    log.info("Claude completed for issue #%d (%d tokens used)", issue.number, total_tokens)

    return AgentResult(
        output=output_text,
        agent_name="claude",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Codex exited with code {result.returncode}: {result.stderr or 'Unknown error'}")
    return result.stdout


def _run_codex(config: Config, issue: IssueContext, work_dir: Path) -> AgentResult:
    """Run Codex CLI as fallback agent."""
    prompt = build_prompt(issue)
    binary_parts = shlex.split(config.codex_binary)
    cmd = binary_parts + [
        "exec",
        "--full-auto",
        "--model", config.codex_model,
        "--cd", str(work_dir),
        prompt,
    ]

    log.info("Spawning Codex for issue #%d in %s", issue.number, work_dir)

    env = os.environ.copy()

    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=config.issue_timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or "") if isinstance(e.stdout, str) else (e.stdout or b"").decode(errors="replace")
        raise AgentTimeoutError(partial, "codex", config.issue_timeout)

    output = result.stdout
    if result.returncode != 0:
        error_msg = result.stderr or "Unknown error"
        log.error("Codex failed (exit %d): %s", result.returncode, error_msg[:500])
        raise RuntimeError(f"Codex exited with code {result.returncode}: {error_msg}")

    log.info("Codex completed for issue #%d (%d chars output)", issue.number, len(output))

    return AgentResult(
        output=output,
        agent_name="codex",
    )


def run_agent(config: Config, issue: IssueContext, work_dir: Path) -> AgentResult:
    """Try Claude first; on rate limit, fall back to Codex."""
    try:
        return _run_claude(config, issue, work_dir)
    except RateLimitError:
        log.warning("Claude rate-limited, falling back to Codex for issue #%d", issue.number)
        return _run_codex(config, issue, work_dir)
