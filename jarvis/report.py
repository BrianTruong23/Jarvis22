"""Report generation from run history and file-based reports."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from jarvis.config import Config
from jarvis.db import Database
from jarvis.models import AgentResult, Run, RunStatus

log = logging.getLogger(__name__)


def format_summary_report(db: Database) -> str:
    runs = db.get_all_runs()
    if not runs:
        return "No runs recorded yet."

    total = len(runs)
    success = sum(1 for r in runs if r.status == RunStatus.SUCCESS)
    failed = sum(1 for r in runs if r.status == RunStatus.FAILED)
    running = sum(1 for r in runs if r.status == RunStatus.RUNNING)
    pending = sum(1 for r in runs if r.status == RunStatus.PENDING)
    timeout = sum(1 for r in runs if r.status == RunStatus.TIMEOUT)
    blocked = sum(1 for r in runs if r.status == RunStatus.BLOCKED)
    rate = (success / total * 100) if total > 0 else 0

    unique_issues = len({r.issue_number for r in runs})

    lines = [
        "# Jarvis22 Run Report",
        "",
        f"**Total runs:** {total}",
        f"**Unique issues:** {unique_issues}",
        f"**Success:** {success} | **Failed:** {failed} | **Timeout:** {timeout} | **Blocked:** {blocked} | **Running:** {running} | **Pending:** {pending}",
        f"**Success rate:** {rate:.1f}%",
    ]

    # Recent failures
    failures = [r for r in runs if r.status == RunStatus.FAILED][:5]
    if failures:
        lines.append("")
        lines.append("## Recent Failures")
        for r in failures:
            error_excerpt = (r.error or "unknown")[:100]
            lines.append(f"- Issue #{r.issue_number} ({r.issue_title}): {error_excerpt}")

    # Recent successes
    successes = [r for r in runs if r.status == RunStatus.SUCCESS][:5]
    if successes:
        lines.append("")
        lines.append("## Recent Successes")
        for r in successes:
            lines.append(f"- Issue #{r.issue_number} ({r.issue_title}): {r.pr_url or 'no PR'}")

    return "\n".join(lines)


def format_issue_report(db: Database, issue_number: int) -> str:
    runs = db.get_runs_for_issue(issue_number)
    if not runs:
        return f"No runs found for issue #{issue_number}."

    lines = [
        f"# Report for Issue #{issue_number}",
        f"**Title:** {runs[0].issue_title}",
        f"**Total attempts:** {len(runs)}",
        "",
        "## Run History",
    ]

    for r in runs:
        status_icon = {"success": "+", "failed": "x", "running": "~", "pending": "?", "timeout": "T", "blocked": "B"}
        icon = status_icon.get(r.status.value, "?")
        lines.append(f"  [{icon}] Run #{r.id} ({r.status.value}) — {r.created_at}")
        if r.agent_name:
            lines.append(f"      Agent: {r.agent_name}")
        if r.tokens_used:
            lines.append(f"      Tokens: {r.tokens_used}")
        if r.pr_url:
            lines.append(f"      PR: {r.pr_url}")
        if r.error:
            lines.append(f"      Error: {r.error[:200]}")
        if r.agent_output:
            excerpt = r.agent_output[:200].replace("\n", " ")
            lines.append(f"      Output: {excerpt}...")

    return "\n".join(lines)


def format_success_comment(issue_number: int, pr_url: str) -> str:
    return f"""\
Jarvis22 has created a pull request to resolve this issue.

**PR:** {pr_url}

Please review the changes and merge if they look good.
"""


def format_failure_comment(issue_number: int, error: str) -> str:
    error_excerpt = error[:500]
    return f"""\
Jarvis22 attempted to resolve this issue but encountered an error:

```
{error_excerpt}
```

The issue remains open for manual intervention or a retry.
"""


def generate_run_report(
    run: Run,
    agent_result: AgentResult | None,
    diff_detail: str = "",
) -> str:
    """Generate a per-issue Markdown report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    status_map = {
        RunStatus.SUCCESS: "Completed",
        RunStatus.FAILED: "Failed",
        RunStatus.TIMEOUT: "Timed out",
        RunStatus.BLOCKED: "Blocked",
        RunStatus.RUNNING: "In progress",
        RunStatus.PENDING: "Pending",
    }
    status_label = status_map.get(run.status, run.status.value)

    lines = [
        f"# Run Report: Issue #{run.issue_number}",
        "",
        f"**Title:** {run.issue_title}",
        f"**Repo:** {run.repo}",
        f"**Status:** {status_label}",
        f"**Generated:** {now}",
    ]

    if agent_result:
        lines.append(f"**Agent:** {agent_result.agent_name}")
        lines.append(f"**Tokens:** {agent_result.total_tokens} (in: {agent_result.input_tokens}, out: {agent_result.output_tokens})")
    elif run.agent_name:
        lines.append(f"**Agent:** {run.agent_name}")
        if run.tokens_used:
            lines.append(f"**Tokens:** {run.tokens_used}")

    if run.pr_url:
        lines.append(f"**PR:** {run.pr_url}")

    if diff_detail:
        lines.append(f"**Diff:** {diff_detail}")

    if run.error:
        lines.append("")
        lines.append("## Error")
        lines.append(f"```\n{run.error[:1000]}\n```")

    if agent_result and agent_result.output:
        excerpt = agent_result.output[:2000]
        lines.append("")
        lines.append("## Agent Output")
        lines.append(f"```\n{excerpt}\n```")

    lines.append("")
    lines.append("## Next Steps")
    if run.status == RunStatus.SUCCESS:
        lines.append("- Review and merge the PR")
    elif run.status == RunStatus.BLOCKED:
        lines.append("- Address the blocking issue and retry")
    elif run.status == RunStatus.TIMEOUT:
        lines.append("- Consider breaking the issue into smaller tasks")
    else:
        lines.append("- Investigate the error and retry")

    return "\n".join(lines)


def generate_session_report(runs: list[Run]) -> str:
    """Generate a session summary Markdown report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    success = sum(1 for r in runs if r.status == RunStatus.SUCCESS)
    failed = sum(1 for r in runs if r.status == RunStatus.FAILED)
    timeout = sum(1 for r in runs if r.status == RunStatus.TIMEOUT)
    blocked = sum(1 for r in runs if r.status == RunStatus.BLOCKED)

    lines = [
        "# Session Report",
        "",
        f"**Date:** {now}",
        f"**Issues processed:** {len(runs)}",
        f"**Success:** {success} | **Failed:** {failed} | **Timeout:** {timeout} | **Blocked:** {blocked}",
        "",
        "## Issues",
    ]

    for run in runs:
        status_icon = {"success": "+", "failed": "x", "timeout": "T", "blocked": "B"}.get(run.status.value, "?")
        agent_tag = f" ({run.agent_name})" if run.agent_name else ""
        tokens_tag = f" [{run.tokens_used} tokens]" if run.tokens_used else ""
        pr_tag = f" -> {run.pr_url}" if run.pr_url else ""
        lines.append(f"- [{status_icon}] #{run.issue_number}: {run.issue_title}{agent_tag}{tokens_tag}{pr_tag}")
        if run.error:
            lines.append(f"  Error: {run.error[:100]}")

    return "\n".join(lines)


def write_report_file(content: str, filename: str, config: Config) -> Path:
    """Write a report file to the reports directory."""
    repo_dir = Path(config.jarvis_repo_dir) if config.jarvis_repo_dir else Path.cwd()
    reports_dir = repo_dir / config.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / filename
    path.write_text(content, encoding="utf-8")
    log.info("Wrote report: %s", path)
    return path


def report_filename(run: Run) -> str:
    """Generate a report filename for a run."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    repo_slug = run.repo.replace("/", "_") if run.repo else "unknown"
    return f"{date}_issue-{run.issue_number}_{repo_slug}.md"


def commit_reports(config: Config, message: str) -> None:
    """Git add, commit, and push reports in the Jarvis22 repo."""
    repo_dir = Path(config.jarvis_repo_dir) if config.jarvis_repo_dir else Path.cwd()
    reports_path = config.reports_dir

    try:
        subprocess.run(
            ["git", "add", reports_path],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        # Check if there's anything to commit
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_dir,
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            log.info("No report changes to commit")
            return

        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        log.info("Reports committed and pushed: %s", message)
    except subprocess.CalledProcessError as e:
        log.error("Failed to commit/push reports: %s", e.stderr or str(e))
    except subprocess.TimeoutExpired:
        log.error("Timed out committing/pushing reports")
