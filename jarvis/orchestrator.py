"""Core pipeline: claim issue -> workspace -> agent -> PR -> review loop -> report."""

from __future__ import annotations

import logging

from jarvis.agent import (
    AgentUnavailableError,
    backend_order,
    implementer_prompt,
    parse_reviewer_verdict,
    reviewer_backend_order,
    reviewer_prompt,
    run_backend,
)
from jarvis.config import Config
from jarvis.db import Database
from jarvis.github_client import GitHubClient
from jarvis.models import IssueContext, RunStatus, Trigger
from jarvis.report import format_failure_comment
from jarvis.workspace import Workspace

log = logging.getLogger(__name__)


def _truncate(s: str, max_chars: int = 8000) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n\n...(truncated)"


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

        self._claude_unavailable_recently = False

    @property
    def claude_unavailable_recently(self) -> bool:
        return self._claude_unavailable_recently

    def _get_handler(self, repo_name: str) -> RepoHandler:
        if repo_name not in self._handlers:
            self._handlers[repo_name] = RepoHandler(self.config, repo_name)
        return self._handlers[repo_name]

    def should_process(self, issue: IssueContext, trigger: Trigger) -> bool:
        labels = {l.lower() for l in issue.labels}
        allowed = {
            self.config.issue_label.lower(),
            self.config.model_label_claude.lower(),
            self.config.model_label_codex.lower(),
            self.config.model_label_gemini.lower(),
        }
        return bool(labels.intersection(allowed))

    def _run_implementer_until_changes(
        self,
        handler: RepoHandler,
        issue: IssueContext,
        extra_instructions: str,
        combined_output_parts: list[str],
    ) -> tuple[bool, bool]:
        """Returns (has_changes, any_unavailable)."""
        any_unavailable = False
        prompt = implementer_prompt(issue, extra_instructions=extra_instructions)

        for backend in backend_order(self.config, issue):
            try:
                out = run_backend(self.config, handler.workspace.repo_dir, backend, prompt)
                combined_output_parts.append(f"[implementer:{backend}]\n{out}")

                if backend == "claude":
                    self._claude_unavailable_recently = False

                if handler.workspace.has_changes():
                    log.info("[%s] Implementer produced changes using %s", issue.repo, backend)
                    return True, any_unavailable

                log.warning("[%s] Implementer %s produced no file changes; trying next backend", issue.repo, backend)

            except AgentUnavailableError as e:
                any_unavailable = True
                combined_output_parts.append(f"[implementer:{backend}]\nUNAVAILABLE: {e}")
                if backend == "claude":
                    self._claude_unavailable_recently = True
                continue

        return handler.workspace.has_changes(), any_unavailable

    def _run_reviewer(
        self,
        handler: RepoHandler,
        issue: IssueContext,
        round_num: int,
        test_output: str,
        combined_output_parts: list[str],
    ) -> tuple[str, str]:
        diffstat = handler.workspace.diffstat()
        diff = handler.workspace.diff()
        prompt = reviewer_prompt(issue, diffstat=diffstat, diff=diff, test_output=test_output)

        last_err = ""
        for backend in reviewer_backend_order(self.config, issue):
            try:
                out = run_backend(self.config, handler.workspace.repo_dir, backend, prompt)
                combined_output_parts.append(f"[reviewer:{backend}:round{round_num}]\n{out}")
                verdict, normalized = parse_reviewer_verdict(out)
                return verdict, normalized
            except AgentUnavailableError as e:
                last_err = str(e)
                combined_output_parts.append(f"[reviewer:{backend}:round{round_num}]\nUNAVAILABLE: {e}")
                continue

        return "CHANGES_REQUESTED", f"VERDICT: CHANGES_REQUESTED\nSUMMARY: Reviewer backend unavailable\nNOTES:\n- {last_err or 'all reviewer backends unavailable'}\nTESTING:\n- (none)"

    def process_issue(self, issue: IssueContext, trigger: Trigger) -> None:
        handler = self._get_handler(issue.repo)
        run = self.db.create_run(issue.number, issue.title, trigger, repo=issue.repo)
        run_id = run.id
        branch = handler.workspace.branch_name(issue.number)

        combined_output_parts: list[str] = []

        try:
            self.db.update_run(run_id, status=RunStatus.RUNNING, branch=branch)

            # Setup workspace
            handler.workspace.ensure_repo()
            handler.workspace.create_branch(branch)

            # Implementer pass 1
            has_changes, any_unavailable = self._run_implementer_until_changes(
                handler,
                issue,
                extra_instructions="",
                combined_output_parts=combined_output_parts,
            )
            self.db.update_run(run_id, agent_output="\n\n".join(combined_output_parts))

            if not has_changes:
                if any_unavailable:
                    self.db.update_run(
                        run_id,
                        status=RunStatus.DEFERRED,
                        error="No backend produced changes (some backends unavailable); will retry.",
                    )
                    return

                self.db.update_run(run_id, status=RunStatus.FAILED, error="Agent produced no file changes")
                handler.gh.comment_on_issue(issue.number, format_failure_comment(issue.number, "Agent produced no file changes"))
                return

            # Commit + push + PR
            commit_msg = f"jarvis: pass 1 implement — issue #{issue.number}"
            pushed = handler.workspace.commit_and_push(branch, commit_msg)
            if not pushed:
                self.db.update_run(run_id, status=RunStatus.FAILED, error="Agent produced no file changes")
                handler.gh.comment_on_issue(issue.number, format_failure_comment(issue.number, "Agent produced no file changes"))
                return

            pr_body = _truncate("\n\n".join(combined_output_parts), 3000)
            pr_url = handler.gh.create_pr(
                branch=branch,
                title=f"fix: resolve #{issue.number} — {issue.title}",
                body=f"Closes #{issue.number}\n\n## Agent output\n\n```\n{pr_body}\n```\n",
            )

            handler.gh.comment_on_issue(
                issue.number,
                _truncate(
                    f"Jarvis22 implementer completed pass 1.\n\nPR: {pr_url}\n\nImplementer output:\n\n```\n{_truncate(combined_output_parts[-1], 6000)}\n```",
                    9000,
                ),
            )

            # Review loop: up to N rounds, but only 2 by default.
            feedback_text = ""
            approved = False
            for r in range(1, max(1, self.config.review_rounds) + 1):
                test_res = handler.workspace.run_test_cmd(self.config.test_cmd, self.config.test_timeout_s)
                test_out = f"CMD: {test_res.cmd}\nEXIT: {test_res.exit_code}\nSTDOUT:\n{test_res.stdout}\nSTDERR:\n{test_res.stderr}"
                test_out_short = _truncate(test_out, 12000)

                verdict, review_text = self._run_reviewer(
                    handler,
                    issue,
                    round_num=r,
                    test_output=test_out_short,
                    combined_output_parts=combined_output_parts,
                )
                self.db.update_run(run_id, agent_output="\n\n".join(combined_output_parts))

                handler.gh.comment_on_issue(
                    issue.number,
                    _truncate(
                        f"Jarvis22 reviewer round {r}:\n\n```\n{_truncate(review_text, 12000)}\n```\n\nTest output (truncated):\n\n```\n{_truncate(test_out_short, 12000)}\n```",
                        15000,
                    ),
                )

                if verdict == "APPROVE":
                    approved = True
                    break

                feedback_text = review_text

                # Implementer addresses feedback
                has_changes2, any_unavailable2 = self._run_implementer_until_changes(
                    handler,
                    issue,
                    extra_instructions=f"Address the following review feedback:\n\n{feedback_text}",
                    combined_output_parts=combined_output_parts,
                )
                self.db.update_run(run_id, agent_output="\n\n".join(combined_output_parts))

                if not has_changes2:
                    if any_unavailable2:
                        self.db.update_run(
                            run_id,
                            status=RunStatus.DEFERRED,
                            error="Could not address review (backends unavailable); will retry.",
                        )
                        return

                pushed2 = handler.workspace.commit_and_push(branch, f"jarvis: pass {r + 1} address review — issue #{issue.number}")
                if pushed2:
                    handler.gh.comment_on_issue(
                        issue.number,
                        _truncate(
                            f"Jarvis22 implementer updated the branch after reviewer round {r}.\n\nPR: {pr_url}\n\nImplementer output (latest):\n\n```\n{_truncate(combined_output_parts[-1], 8000)}\n```",
                            12000,
                        ),
                    )

            if approved:
                self.db.update_run(run_id, status=RunStatus.SUCCESS, pr_url=pr_url)
                handler.gh.mark_done(issue.number)
                handler.gh.comment_on_issue(issue.number, f"Jarvis22: approved. PR: {pr_url}")
                return

            # Not approved after max rounds
            self.db.update_run(run_id, status=RunStatus.NEEDS_HUMAN, pr_url=pr_url, error="Review not approved")
            handler.gh.mark_needs_human(issue.number)
            handler.gh.comment_on_issue(
                issue.number,
                _truncate(
                    f"Jarvis22: reviewer did not approve after {self.config.review_rounds} rounds. Marking needs human.\n\nPR: {pr_url}\n\nLast feedback:\n\n```\n{_truncate(feedback_text, 12000)}\n```",
                    15000,
                ),
            )

        except Exception as e:
            error_msg = str(e)
            log.error("[%s] Failed to process issue #%d: %s", issue.repo, issue.number, error_msg)
            self.db.update_run(run_id, status=RunStatus.FAILED, error=error_msg)
            try:
                handler.gh.comment_on_issue(issue.number, format_failure_comment(issue.number, error_msg))
            except Exception:
                log.exception("[%s] Failed to comment on issue #%d", issue.repo, issue.number)

    def poll_once(self, trigger: Trigger = Trigger.POLL) -> int:
        processed = 0

        for repo_name, handler in self._handlers.items():
            try:
                issues = handler.gh.get_labeled_issues()
            except Exception:
                log.exception("Failed to fetch issues from %s", repo_name)
                issues = []

            for issue in issues:
                if processed >= self.config.max_issues_per_poll:
                    return processed
                if self.db.is_issue_claimed(issue.number, repo=repo_name):
                    continue
                if not self.should_process(issue, trigger):
                    continue
                log.info("[%s] Processing issue #%d: %s", repo_name, issue.number, issue.title)
                self.process_issue(issue, trigger)
                processed += 1

        return processed

    def run_single(self, issue_number: int, repo_name: str, trigger: Trigger = Trigger.CLI) -> None:
        handler = self._get_handler(repo_name)
        issue = handler.gh.get_issue(issue_number)
        if not self.should_process(issue, trigger):
            log.info("[%s] Skipping issue #%d due to label policy (trigger=%s)", repo_name, issue_number, trigger.value)
            return
        self.process_issue(issue, trigger)
