"""Core pipeline: claim issue -> workspace -> agent -> PR -> report."""

from __future__ import annotations

import logging
import time

from jarvis.agent import AgentTimeoutError, run_agent
from jarvis.config import Config
from jarvis.db import Database
from jarvis.github_client import GitHubClient
from jarvis.models import AgentResult, IssueContext, Run, RunStatus, Trigger
from jarvis.report import (
    format_failure_comment,
    format_success_comment,
    generate_run_report,
    report_filename,
    write_report_file,
)
from jarvis.workspace import Workspace

log = logging.getLogger(__name__)


class RepoHandler:
    """Handles a single repo's GitHub client + workspace."""

    def __init__(self, config: Config, repo_name: str) -> None:
        self.repo_name = repo_name
        self.gh = GitHubClient(config, repo_name)
        self.workspace = Workspace(config, self.gh.clone_url, repo_name)


class Orchestrator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.db = Database(config.db_path)
        self._handlers: dict[str, RepoHandler] = {}
        for repo in config.target_repos:
            self._handlers[repo] = RepoHandler(config, repo)
        self._session_tokens = 0

    def _get_handler(self, repo_name: str) -> RepoHandler:
        if repo_name not in self._handlers:
            self._handlers[repo_name] = RepoHandler(self.config, repo_name)
        return self._handlers[repo_name]

    def _near_token_limit(self) -> bool:
        """Check if we're within token_warning_buffer of max_tokens_per_run."""
        return self._session_tokens >= (
            self.config.max_tokens_per_run - self.config.token_warning_buffer
        )

    def process_issue(self, issue: IssueContext, trigger: Trigger) -> Run:
        handler = self._get_handler(issue.repo)
        run = self.db.create_run(issue.number, issue.title, trigger, repo=issue.repo)
        run_id = run.id
        branch = handler.workspace.branch_name(issue.number)
        agent_result: AgentResult | None = None
        diff_detail = ""

        try:
            self.db.update_run(run_id, status=RunStatus.RUNNING, branch=branch)

            # Setup workspace
            handler.workspace.ensure_repo()
            handler.workspace.create_branch(branch)

            # Run agent
            agent_result = run_agent(self.config, issue, handler.workspace.repo_dir)
            self._session_tokens += agent_result.total_tokens
            self.db.update_run(
                run_id,
                agent_output=agent_result.output,
                agent_name=agent_result.agent_name,
                tokens_used=agent_result.total_tokens,
            )

            # Check diff limits before committing
            within_limits, diff_detail = handler.workspace.check_diff_limits(
                self.config.max_diff_files, self.config.max_diff_loc,
            )
            if not within_limits:
                log.warning(
                    "[%s] Issue #%d diff exceeds limits: %s",
                    issue.repo, issue.number, diff_detail,
                )
                run = self.db.update_run(
                    run_id,
                    status=RunStatus.BLOCKED,
                    error=f"Diff exceeds limits: {diff_detail}",
                )
                comment = format_failure_comment(issue.number, f"Diff exceeds limits: {diff_detail}")
                handler.gh.comment_on_issue(issue.number, comment)
                self._write_run_report(run, agent_result, diff_detail)
                return run

            # Commit and push
            commit_msg = f"fix: resolve issue #{issue.number} — {issue.title}"
            pushed = handler.workspace.commit_and_push(branch, commit_msg)

            if not pushed:
                run = self.db.update_run(
                    run_id,
                    status=RunStatus.FAILED,
                    error="Agent produced no file changes",
                )
                comment = format_failure_comment(issue.number, "Agent produced no file changes")
                handler.gh.comment_on_issue(issue.number, comment)
                self._write_run_report(run, agent_result, diff_detail)
                return run

            # Create PR
            pr_body = self._build_pr_body(issue, agent_result.output)
            pr_url = handler.gh.create_pr(
                branch=branch,
                title=f"fix: resolve #{issue.number} — {issue.title}",
                body=pr_body,
            )

            run = self.db.update_run(run_id, status=RunStatus.SUCCESS, pr_url=pr_url)
            handler.gh.swap_labels(issue.number)

            comment = format_success_comment(issue.number, pr_url)
            handler.gh.comment_on_issue(issue.number, comment)

            log.info("[%s] Issue #%d processed successfully: %s", issue.repo, issue.number, pr_url)
            self._write_run_report(run, agent_result, diff_detail)
            return run

        except AgentTimeoutError as e:
            log.warning("[%s] Issue #%d timed out: %s", issue.repo, issue.number, e)
            run = self.db.update_run(
                run_id,
                status=RunStatus.TIMEOUT,
                error=str(e),
                agent_output=e.partial_output,
                agent_name=e.agent_name,
            )
            try:
                comment = format_failure_comment(issue.number, f"Agent timed out: {e}")
                handler.gh.comment_on_issue(issue.number, comment)
            except Exception:
                log.exception("[%s] Failed to comment on issue #%d", issue.repo, issue.number)
            self._write_run_report(run, agent_result, diff_detail)
            return run

        except Exception as e:
            error_msg = str(e)
            log.error("[%s] Failed to process issue #%d: %s", issue.repo, issue.number, error_msg)
            run = self.db.update_run(run_id, status=RunStatus.FAILED, error=error_msg)

            try:
                comment = format_failure_comment(issue.number, error_msg)
                handler.gh.comment_on_issue(issue.number, comment)
            except Exception:
                log.exception("[%s] Failed to comment on issue #%d", issue.repo, issue.number)

            self._write_run_report(run, agent_result, diff_detail)
            return run

    def _write_run_report(self, run: Run, agent_result: AgentResult | None, diff_detail: str) -> None:
        """Write a per-issue report file."""
        try:
            content = generate_run_report(run, agent_result, diff_detail)
            filename = report_filename(run)
            write_report_file(content, filename, self.config)
        except Exception:
            log.exception("Failed to write run report for issue #%d", run.issue_number)

    def poll_once(self, trigger: Trigger = Trigger.POLL) -> list[Run]:
        """Process all eligible issues, respecting session timeout. Returns list of runs."""
        session_start = time.monotonic()
        runs: list[Run] = []

        for repo_name, handler in self._handlers.items():
            # Check session timeout
            elapsed = time.monotonic() - session_start
            if elapsed >= self.config.session_timeout:
                log.warning("Session timeout reached (%.0fs), stopping", elapsed)
                break

            # Check token limit
            if self._near_token_limit():
                log.warning(
                    "Near token limit (%d/%d), stopping session",
                    self._session_tokens, self.config.max_tokens_per_run,
                )
                break

            log.debug("Polling %s for labeled issues", repo_name)
            try:
                issues = handler.gh.get_labeled_issues()
            except Exception:
                log.exception("Failed to fetch issues from %s", repo_name)
                continue

            for issue in issues:
                # Check session timeout before each issue
                elapsed = time.monotonic() - session_start
                if elapsed >= self.config.session_timeout:
                    log.warning("Session timeout reached (%.0fs), stopping", elapsed)
                    break

                # Check token limit
                if self._near_token_limit():
                    log.warning(
                        "Near token limit (%d/%d), stopping session",
                        self._session_tokens, self.config.max_tokens_per_run,
                    )
                    break

                if self.db.is_issue_claimed(issue.number, repo=repo_name):
                    log.debug("[%s] Issue #%d already claimed, skipping", repo_name, issue.number)
                    continue

                log.info("[%s] Processing issue #%d: %s", repo_name, issue.number, issue.title)
                run = self.process_issue(issue, trigger)
                runs.append(run)

        return runs

    def run_single(self, issue_number: int, repo_name: str, trigger: Trigger = Trigger.CLI) -> Run:
        handler = self._get_handler(repo_name)
        issue = handler.gh.get_issue(issue_number)
        return self.process_issue(issue, trigger)

    def _build_pr_body(self, issue: IssueContext, agent_output: str) -> str:
        max_output = 3000
        output_excerpt = agent_output[:max_output]
        if len(agent_output) > max_output:
            output_excerpt += "\n\n... (truncated)"

        return f"""\
Closes #{issue.number}

## What this PR does
Automated fix for: **{issue.title}**

## Issue description
{issue.body[:1000] if issue.body else "No description provided."}

## Agent output
<details>
<summary>Click to expand</summary>

```
{output_excerpt}
```

</details>

---
*Generated by [Jarvis22](https://github.com/BrianTruong23/Jarvis22)*
"""
