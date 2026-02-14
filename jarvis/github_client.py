"""GitHub API wrapper using PyGithub."""

from __future__ import annotations

import logging

from github import Github
from github.Issue import Issue
from github.PullRequest import PullRequest
from github.Repository import Repository

from jarvis.config import Config
from jarvis.models import IssueContext

log = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, config: Config, repo_name: str) -> None:
        self._gh = Github(config.github_token)
        self._repo: Repository = self._gh.get_repo(repo_name)
        self._repo_name = repo_name
        self._config = config

    @property
    def repo(self) -> Repository:
        return self._repo

    @property
    def repo_name(self) -> str:
        return self._repo_name

    @property
    def clone_url(self) -> str:
        return f"https://x-access-token:{self._config.github_token}@github.com/{self._repo_name}.git"

    def _to_issue_context(self, issue: Issue) -> IssueContext:
        return IssueContext(
            number=issue.number,
            title=issue.title,
            body=issue.body or "",
            repo=self._repo_name,
            labels=[l.name for l in issue.labels],
        )

    def get_issues_with_label(self, label: str) -> list[IssueContext]:
        issues: list[IssueContext] = []
        for issue in self._repo.get_issues(state="open", labels=[label]):
            if issue.pull_request is not None:
                continue
            issues.append(self._to_issue_context(issue))
        return issues

    def get_unlabeled_issues(self, limit: int = 25) -> list[IssueContext]:
        issues: list[IssueContext] = []
        for issue in self._repo.get_issues(state="open"):
            if issue.pull_request is not None:
                continue
            try:
                if issue.labels.totalCount != 0:  # type: ignore[attr-defined]
                    continue
            except Exception:
                if list(issue.labels):
                    continue
            issues.append(self._to_issue_context(issue))
            if len(issues) >= limit:
                break
        return issues

    def get_labeled_issues(self) -> list[IssueContext]:
        return self.get_issues_with_label(self._config.issue_label)

    def get_issue(self, number: int) -> IssueContext:
        issue: Issue = self._repo.get_issue(number)
        return self._to_issue_context(issue)

    def create_pr(self, branch: str, title: str, body: str) -> str:
        default_branch = self._repo.default_branch
        pr: PullRequest = self._repo.create_pull(
            title=title,
            body=body,
            head=branch,
            base=default_branch,
        )
        log.info("[%s] Created PR #%d: %s", self._repo_name, pr.number, pr.html_url)
        return pr.html_url

    def comment_on_issue(self, issue_number: int, body: str) -> None:
        issue = self._repo.get_issue(issue_number)
        issue.create_comment(body)
        log.info("[%s] Commented on issue #%d", self._repo_name, issue_number)

    def mark_done(self, issue_number: int) -> None:
        issue = self._repo.get_issue(issue_number)
        for label in (self._config.issue_label, self._config.ready_label):
            try:
                issue.remove_from_labels(label)
            except Exception:
                pass
        issue.add_to_labels(self._config.done_label)
        log.info("[%s] Marked issue #%d done", self._repo_name, issue_number)

    def mark_needs_human(self, issue_number: int) -> None:
        issue = self._repo.get_issue(issue_number)
        for label in (self._config.issue_label, self._config.ready_label):
            try:
                issue.remove_from_labels(label)
            except Exception:
                pass
        if self._config.needs_human_label:
            issue.add_to_labels(self._config.needs_human_label)
        log.info("[%s] Marked issue #%d needs human", self._repo_name, issue_number)
