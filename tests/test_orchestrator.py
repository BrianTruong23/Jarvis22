"""Tests for the orchestrator module."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from jarvis.config import Config
from jarvis.db import Database
from jarvis.models import IssueContext, RunStatus, Trigger
from jarvis.orchestrator import Orchestrator


@pytest.fixture
def config():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    cfg = Config(
        github_token="fake-token",
        target_repo="owner/repo",
        anthropic_api_key="fake-key",
        db_path=db_path,
        workspace_dir=tempfile.mkdtemp(),
    )
    yield cfg
    os.unlink(db_path)


@pytest.fixture
def mock_issue():
    return IssueContext(
        number=42,
        title="Fix the bug",
        body="There is a bug in main.py",
        labels=["jarvis"],
    )


@patch("jarvis.orchestrator.GitHubClient")
@patch("jarvis.orchestrator.Workspace")
@patch("jarvis.orchestrator.run_agent")
def test_process_issue_success(mock_agent, mock_ws_cls, mock_gh_cls, config, mock_issue):
    mock_agent.return_value = "I fixed the bug"
    mock_ws = mock_ws_cls.return_value
    mock_ws.repo_dir = config.workspace_dir
    mock_ws.branch_name.return_value = "jarvis/issue-42"
    mock_ws.commit_and_push.return_value = True

    mock_gh = mock_gh_cls.return_value
    mock_gh.create_pr.return_value = "https://github.com/owner/repo/pull/1"
    mock_gh.clone_url = "https://github.com/owner/repo.git"

    orch = Orchestrator(config)
    orch.gh = mock_gh
    orch.workspace = mock_ws
    orch.process_issue(mock_issue, Trigger.CLI)

    # Verify run was created and completed
    runs = orch.db.get_runs_for_issue(42)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.SUCCESS
    assert runs[0].pr_url == "https://github.com/owner/repo/pull/1"

    # Verify agent was called
    mock_agent.assert_called_once()

    # Verify PR was created
    mock_gh.create_pr.assert_called_once()
    mock_gh.swap_labels.assert_called_once_with(42)


@patch("jarvis.orchestrator.GitHubClient")
@patch("jarvis.orchestrator.Workspace")
@patch("jarvis.orchestrator.run_agent")
def test_process_issue_no_changes(mock_agent, mock_ws_cls, mock_gh_cls, config, mock_issue):
    mock_agent.return_value = "I looked at it but nothing to change"
    mock_ws = mock_ws_cls.return_value
    mock_ws.repo_dir = config.workspace_dir
    mock_ws.branch_name.return_value = "jarvis/issue-42"
    mock_ws.commit_and_push.return_value = False  # No changes

    mock_gh = mock_gh_cls.return_value
    mock_gh.clone_url = "https://github.com/owner/repo.git"

    orch = Orchestrator(config)
    orch.gh = mock_gh
    orch.workspace = mock_ws
    orch.process_issue(mock_issue, Trigger.CLI)

    runs = orch.db.get_runs_for_issue(42)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    assert "no file changes" in runs[0].error.lower()


@patch("jarvis.orchestrator.GitHubClient")
@patch("jarvis.orchestrator.Workspace")
@patch("jarvis.orchestrator.run_agent")
def test_process_issue_agent_failure(mock_agent, mock_ws_cls, mock_gh_cls, config, mock_issue):
    mock_agent.side_effect = RuntimeError("Claude Code crashed")
    mock_ws = mock_ws_cls.return_value
    mock_ws.repo_dir = config.workspace_dir
    mock_ws.branch_name.return_value = "jarvis/issue-42"

    mock_gh = mock_gh_cls.return_value
    mock_gh.clone_url = "https://github.com/owner/repo.git"

    orch = Orchestrator(config)
    orch.gh = mock_gh
    orch.workspace = mock_ws
    orch.process_issue(mock_issue, Trigger.CLI)

    runs = orch.db.get_runs_for_issue(42)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    assert "crashed" in runs[0].error.lower()


@patch("jarvis.orchestrator.GitHubClient")
@patch("jarvis.orchestrator.Workspace")
def test_poll_once_skips_claimed(mock_ws_cls, mock_gh_cls, config, mock_issue):
    mock_gh = mock_gh_cls.return_value
    mock_gh.get_labeled_issues.return_value = [mock_issue]
    mock_gh.clone_url = "https://github.com/owner/repo.git"

    orch = Orchestrator(config)
    orch.gh = mock_gh
    orch.workspace = mock_ws_cls.return_value

    # Pre-claim the issue
    orch.db.create_run(42, "Fix the bug", Trigger.CLI)

    count = orch.poll_once()
    assert count == 0
