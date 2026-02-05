"""Report generation from run history."""

from __future__ import annotations

from jarvis.db import Database
from jarvis.models import Run, RunStatus


def format_summary_report(db: Database) -> str:
    runs = db.get_all_runs()
    if not runs:
        return "No runs recorded yet."

    total = len(runs)
    success = sum(1 for r in runs if r.status == RunStatus.SUCCESS)
    failed = sum(1 for r in runs if r.status == RunStatus.FAILED)
    running = sum(1 for r in runs if r.status == RunStatus.RUNNING)
    pending = sum(1 for r in runs if r.status == RunStatus.PENDING)
    rate = (success / total * 100) if total > 0 else 0

    unique_issues = len({r.issue_number for r in runs})

    lines = [
        "# Jarvis22 Run Report",
        "",
        f"**Total runs:** {total}",
        f"**Unique issues:** {unique_issues}",
        f"**Success:** {success} | **Failed:** {failed} | **Running:** {running} | **Pending:** {pending}",
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
        status_icon = {"success": "+", "failed": "x", "running": "~", "pending": "?"}
        icon = status_icon.get(r.status.value, "?")
        lines.append(f"  [{icon}] Run #{r.id} ({r.status.value}) — {r.created_at}")
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
