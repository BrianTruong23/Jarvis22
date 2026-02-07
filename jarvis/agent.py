"""Multi-model agent dispatch: Claude, Codex, and Gemini with fallback."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from jarvis.config import Config
from jarvis.models import AllModelsExhausted, IssueContext, ModelChoice

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


def _run_claude(config: Config, prompt: str, work_dir: Path, env: dict) -> str:
    """Invoke Claude Code CLI."""
    cmd = [
        "claude",
        "--print",
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


def _run_codex(config: Config, prompt: str, work_dir: Path, env: dict) -> str:
    """Invoke OpenAI Codex CLI (non-interactive exec mode)."""
    cmd = [
        "npx", "@openai/codex", "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C", str(work_dir),
    ]
    log.info("Trying Codex in %s", work_dir)
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
        raise RuntimeError(f"Codex exited with code {result.returncode}: {result.stderr or 'Unknown error'}")
    return result.stdout


def _run_gemini(config: Config, prompt: str, work_dir: Path, env: dict) -> str:
    """Invoke Gemini CLI (non-interactive prompt mode)."""
    cmd = [
        "gemini",
        "-p", prompt,
        "--yolo",
        "-o", "text",
    ]
    log.info("Trying Gemini in %s", work_dir)
    result = subprocess.run(
        cmd,
        input=None,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Gemini exited with code {result.returncode}: {result.stderr or 'Unknown error'}")
    return result.stdout


# Dispatch table: model -> runner function
_RUNNERS = {
    ModelChoice.CLAUDE: _run_claude,
    ModelChoice.CODEX: _run_codex,
    ModelChoice.GEMINI: _run_gemini,
}


def run_agent(
    config: Config,
    issue: IssueContext,
    work_dir: Path,
    model_order: list[ModelChoice] | None = None,
) -> str:
    """Try models in order; return output from the first that succeeds.

    Raises AllModelsExhausted if every model in the chain fails.
    """
    if model_order is None:
        model_order = [ModelChoice.CLAUDE]

    prompt = build_prompt(issue)

    env = os.environ.copy()
    if config.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = config.anthropic_api_key

    errors: list[str] = []

    for model in model_order:
        runner = _RUNNERS[model]
        try:
            log.info("Attempting model=%s for issue #%d", model.value, issue.number)
            output = runner(config, prompt, work_dir, env)
            log.info("Model %s succeeded for issue #%d (%d chars)", model.value, issue.number, len(output))
            return output
        except Exception as exc:
            err_msg = str(exc)
            log.warning("Model %s failed for issue #%d: %s", model.value, issue.number, err_msg[:300])
            errors.append(f"{model.value}: {err_msg}")

    summary = "; ".join(errors)
    raise AllModelsExhausted(f"All models exhausted for issue #{issue.number}: {summary}")
