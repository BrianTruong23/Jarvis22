"""Core pipeline: claim issue -> workspace -> agent -> PR -> report."""

from __future__ import annotations

import logging

from jarvis.agent import run_agent
from jarvis.config import Config
from jarvis.db import Database
from jarvis.github_client import GitHubClient
from jarvis.models import IssueContext, RunStatus, Trigger
from jarvis.report import format_failure_comment, format_success_comment
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

    def _get_handler(self, repo_name: str) -> RepoHandler:
        if repo_name not in self._handlers:
            self._handlers[repo_name] = RepoHandler(self.config, repo_name)
        return self._handlers[repo_name]

    def process_issue(self, issue: IssueContext, trigger: Trigger) -> None:
        handler = self._get_handler(issue.repo)
        run = self.db.create_run(issue.number, issue.title, trigger, repo=issue.repo)
        run_id = run.id
        branch = handler.workspace.branch_name(issue.number)

        try:
            self.db.update_run(run_id, status=RunStatus.RUNNING, branch=branch)

            # Setup workspace
            handler.workspace.ensure_repo()
            handler.workspace.create_branch(branch)

            # Run agent
            output = run_agent(self.config, issue, handler.workspace.repo_dir)
            self.db.update_run(run_id, agent_output=output)

            # Commit and push
            commit_msg = f"fix: resolve issue #{issue.number} — {issue.title}"
            pushed = handler.workspace.commit_and_push(branch, commit_msg)

            if not pushed:
                self.db.update_run(
                    run_id,
                    status=RunStatus.FAILED,
                    error="Agent produced no file changes",
                )
                comment = format_failure_comment(issue.number, "Agent produced no file changes")
                handler.gh.comment_on_issue(issue.number, comment)
                return

            # Create PR
            pr_body = self._build_pr_body(issue, output)
            pr_url = handler.gh.create_pr(
                branch=branch,
                title=f"fix: resolve #{issue.number} — {issue.title}",
                body=pr_body,
            )

            self.db.update_run(run_id, status=RunStatus.SUCCESS, pr_url=pr_url)
            handler.gh.swap_labels(issue.number)

            comment = format_success_comment(issue.number, pr_url)
            handler.gh.comment_on_issue(issue.number, comment)

            log.info("[%s] Issue #%d processed successfully: %s", issue.repo, issue.number, pr_url)

        except Exception as e:
            error_msg = str(e)
            log.error("[%s] Failed to process issue #%d: %s", issue.repo, issue.number, error_msg)
            self.db.update_run(run_id, status=RunStatus.FAILED, error=error_msg)

            try:
                comment = format_failure_comment(issue.number, error_msg)
                handler.gh.comment_on_issue(issue.number, comment)
            except Exception:
                log.exception("[%s] Failed to comment on issue #%d", issue.repo, issue.number)

    def poll_once(self, trigger: Trigger = Trigger.POLL) -> int:
        processed = 0

        for repo_name, handler in self._handlers.items():
            log.debug("Polling %s for labeled issues", repo_name)
            try:
                issues = handler.gh.get_labeled_issues()
            except Exception:
                log.exception("Failed to fetch issues from %s", repo_name)
                continue

            for issue in issues:
                if self.db.is_issue_claimed(issue.number, repo=repo_name):
                    log.debug("[%s] Issue #%d already claimed, skipping", repo_name, issue.number)
                    continue

                log.info("[%s] Processing issue #%d: %s", repo_name, issue.number, issue.title)
                self.process_issue(issue, trigger)
                processed += 1

        return processed

    def run_single(self, issue_number: int, repo_name: str, trigger: Trigger = Trigger.CLI) -> None:
        handler = self._get_handler(repo_name)
        issue = handler.gh.get_issue(issue_number)
        self.process_issue(issue, trigger)

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
