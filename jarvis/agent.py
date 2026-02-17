"""Coding agent subprocess orchestration with model fallback.

Jarvis22 uses two roles per issue:
- implementer: makes code changes
- reviewer: reviews diff + test output and requests changes

Both roles can be routed to different backends (claude/codex/gemini).
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from jarvis.config import Config
from jarvis.models import IssueContext

log = logging.getLogger(__name__)

IMPLEMENTER_SYSTEM_PROMPT = """\
You are solving a GitHub issue. Read the issue carefully and implement the requested changes.

IMPORTANT RULES:
- Do NOT run git commands (no git add, commit, push, etc). The orchestrator handles git.
- Do NOT create pull requests.
- Focus on writing/modifying code to solve the issue.
- If you need to create new files, do so.
- If tests exist, make sure they still pass after your changes.
"""

REVIEWER_SYSTEM_PROMPT = """\
You are a code reviewer.

You will be given:
- the GitHub issue
- a git diff (and diffstat)
- optional test output

Your job:
- decide if the change is acceptable
- if not acceptable, request concrete changes

Output format MUST be:
VERDICT: APPROVE | CHANGES_REQUESTED
SUMMARY: <1-4 sentences>
NOTES:
- <bullets>
TESTING:
- <bullets>
"""


class AgentUnavailableError(RuntimeError):
    """Temporary capacity/limit/auth availability error; try next backend or retry later."""


UNAVAILABLE_PATTERNS = (
    "rate limit",
    "quota",
    "usage limit",
    "credit",
    "insufficient",
    "429",
    "temporarily unavailable",
    "try again later",
    "overloaded",
    "max turns",
    "max-turns",
    "timeout",
    "timed out",
    "pass --to",
)


def _is_unavailable_error(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in UNAVAILABLE_PATTERNS)


def _run_cmd(name: str, cmd: list[str], prompt: str, work_dir: Path, env: dict[str, str], timeout: int = 900) -> str:
    log.info("Spawning %s in %s", name, work_dir)
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise AgentUnavailableError(f"{name} unavailable: timeout after {timeout}s") from e

    output = result.stdout or ""
    stderr = result.stderr or ""
    combined = f"{output}\n{stderr}".strip()

    # Some CLIs return exit=0 but print limit/turn exhaustion.
    if _is_unavailable_error(combined):
        raise AgentUnavailableError(f"{name} unavailable: {stderr[:300] or output[:300]}")

    if result.returncode != 0:
        raise RuntimeError(f"{name} exited with code {result.returncode}: {stderr[:500] or output[:500]}")

    return output


def implementer_prompt(issue: IssueContext, extra_instructions: str = "") -> str:
    labels_text = ", ".join(issue.labels) if issue.labels else "(none)"
    extra = f"\n\nAdditional instructions:\n{extra_instructions.strip()}" if extra_instructions.strip() else ""
    return f"""\
{IMPLEMENTER_SYSTEM_PROMPT}

GitHub Issue #{issue.number}: {issue.title}

Repo: {issue.repo}
Labels: {labels_text}

{issue.body}{extra}

Solve this issue. Remember: do NOT run any git commands."""


def reviewer_prompt(issue: IssueContext, diffstat: str, diff: str, test_output: str = "") -> str:
    labels_text = ", ".join(issue.labels) if issue.labels else "(none)"
    test_block = ""
    if test_output.strip():
        test_block = f"\n\nTEST OUTPUT (most recent):\n{test_output.strip()}"

    return f"""\
{REVIEWER_SYSTEM_PROMPT}

GitHub Issue #{issue.number}: {issue.title}

Repo: {issue.repo}
Labels: {labels_text}

ISSUE BODY:\n{issue.body}

DIFFSTAT:\n{diffstat}

DIFF:\n{diff}{test_block}
"""


def backend_order(config: Config, issue: IssueContext) -> list[str]:
    labels = {l.lower() for l in issue.labels}

    preferred = ""
    if config.model_label_claude.lower() in labels:
        preferred = "claude"
    elif config.model_label_codex.lower() in labels:
        preferred = "codex"
    elif config.model_label_gemini.lower() in labels:
        preferred = "claude"

    default_order = ["claude", "codex"]
    if not preferred:
        return default_order
    return [preferred] + [name for name in default_order if name != preferred]


def reviewer_backend_order(config: Config, issue: IssueContext) -> list[str]:
    # Respect explicit model labels if present; otherwise use configured order.
    explicit = backend_order(config, issue)
    labels = {l.lower() for l in issue.labels}
    if labels.intersection(
        {
            config.model_label_claude.lower(),
            config.model_label_codex.lower(),
            config.model_label_gemini.lower(),
        }
    ):
        return explicit

    raw = [p.strip().lower() for p in config.reviewer_backend_order.split(",") if p.strip()]
    order = [b for b in raw if b in {"claude", "codex"}]
    # Ensure all are present at least once
    for b in ("claude", "codex"):
        if b not in order:
            order.append(b)
    return order


def run_backend(config: Config, work_dir: Path, backend: str, prompt: str) -> str:
    env = os.environ.copy()
    if config.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = config.anthropic_api_key

    if backend == "claude":
        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--model",
            config.claude_model,
            "--max-turns",
            "30",
        ]
        out = _run_cmd("claude", cmd, prompt, work_dir, env)
        return f"[backend:claude]\n{out}"

    if backend == "codex":
        # Prefer real Codex CLI if available. Some environments have a wrapper
        # that routes through OpenClaw; we still treat it as a backend.
        cmd = ["codex", "exec", "--full-auto", prompt]
        if config.codex_model:
            cmd = ["codex", "exec", "--full-auto", "--model", config.codex_model, prompt]
        try:
            out = _run_cmd("codex", cmd, prompt, work_dir, env)
        except RuntimeError:
            out = _run_cmd("codex", ["codex", prompt], prompt, work_dir, env)
        return f"[backend:codex]\n{out}"

    if backend == "gemini":
        raise AgentUnavailableError("gemini backend is disabled")

    raise RuntimeError(f"Unknown backend: {backend}")


def parse_reviewer_verdict(text: str) -> tuple[str, str]:
    """Return (verdict, normalized_text)."""
    t = (text or "").strip()
    low = t.lower()
    if "verdict:" in low:
        for line in t.splitlines():
            if line.lower().startswith("verdict:"):
                v = line.split(":", 1)[1].strip().upper()
                if "APPROVE" in v:
                    return "APPROVE", t
                if "CHANGES" in v:
                    return "CHANGES_REQUESTED", t
    # Fallback heuristic
    if "approve" in low and "changes" not in low:
        return "APPROVE", t
    return "CHANGES_REQUESTED", t
