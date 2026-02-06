"""Tests for the orchestrator module."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from jarvis.config import Config
from jarvis.db import Database
from jarvis.models import AgentResult, IssueContext, RunStatus, Trigger
from jarvis.orchestrator import Orchestrator


@pytest.fixture
def config():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    cfg = Config(
        github_token="fake-token",
        target_repos=("owner/repo",),
        anthropic_api_key="fake-key",
        db_path=db_path,
        workspace_dir=tempfile.mkdtemp(),
    )
    yield cfg
    os.unlink(db_path)


@pytest.fixture
def multi_repo_config():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    cfg = Config(
        github_token="fake-token",
        target_repos=("owner/repoA", "owner/repoB"),
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
        repo="owner/repo",
        labels=["jarvis"],
    )


def _make_orch(config):
    """Create an Orchestrator bypassing __init__ but setting all required attrs."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.db = Database(config.db_path)
    orch._handlers = {}
    orch._session_tokens = 0
    return orch


@patch("jarvis.orchestrator.GitHubClient")
@patch("jarvis.orchestrator.Workspace")
@patch("jarvis.orchestrator.run_agent")
def test_process_issue_success(mock_agent, mock_ws_cls, mock_gh_cls, config, mock_issue):
    mock_agent.return_value = AgentResult(output="I fixed the bug", agent_name="claude", total_tokens=1000)
    mock_ws = mock_ws_cls.return_value
    mock_ws.repo_dir = config.workspace_dir
    mock_ws.branch_name.return_value = "jarvis/issue-42"
    mock_ws.commit_and_push.return_value = True
    mock_ws.check_diff_limits.return_value = (True, "2 files changed, 10 LOC")

    mock_gh = mock_gh_cls.return_value
    mock_gh.create_pr.return_value = "https://github.com/owner/repo/pull/1"
    mock_gh.clone_url = "https://github.com/owner/repo.git"

    orch = _make_orch(config)
    orch._handlers = {"owner/repo": MagicMock()}
    orch._handlers["owner/repo"].gh = mock_gh
    orch._handlers["owner/repo"].workspace = mock_ws

    orch.process_issue(mock_issue, Trigger.CLI)

    runs = orch.db.get_runs_for_issue(42)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.SUCCESS
    assert runs[0].pr_url == "https://github.com/owner/repo/pull/1"
    assert runs[0].repo == "owner/repo"
    assert runs[0].agent_name == "claude"
    assert runs[0].tokens_used == 1000

    mock_agent.assert_called_once()
    mock_gh.create_pr.assert_called_once()
    mock_gh.swap_labels.assert_called_once_with(42)


@patch("jarvis.orchestrator.GitHubClient")
@patch("jarvis.orchestrator.Workspace")
@patch("jarvis.orchestrator.run_agent")
def test_process_issue_no_changes(mock_agent, mock_ws_cls, mock_gh_cls, config, mock_issue):
    mock_agent.return_value = AgentResult(output="I looked at it but nothing to change", agent_name="claude")
    mock_ws = mock_ws_cls.return_value
    mock_ws.repo_dir = config.workspace_dir
    mock_ws.branch_name.return_value = "jarvis/issue-42"
    mock_ws.commit_and_push.return_value = False
    mock_ws.check_diff_limits.return_value = (True, "No changes")

    mock_gh = mock_gh_cls.return_value
    mock_gh.clone_url = "https://github.com/owner/repo.git"

    orch = _make_orch(config)
    orch._handlers = {"owner/repo": MagicMock()}
    orch._handlers["owner/repo"].gh = mock_gh
    orch._handlers["owner/repo"].workspace = mock_ws

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

    orch = _make_orch(config)
    orch._handlers = {"owner/repo": MagicMock()}
    orch._handlers["owner/repo"].gh = mock_gh
    orch._handlers["owner/repo"].workspace = mock_ws

    orch.process_issue(mock_issue, Trigger.CLI)

    runs = orch.db.get_runs_for_issue(42)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    assert "crashed" in runs[0].error.lower()


@patch("jarvis.orchestrator.GitHubClient")
@patch("jarvis.orchestrator.Workspace")
@patch("jarvis.orchestrator.run_agent")
def test_process_issue_diff_exceeds_limits(mock_agent, mock_ws_cls, mock_gh_cls, config, mock_issue):
    mock_agent.return_value = AgentResult(output="Changed a lot", agent_name="claude", total_tokens=500)
    mock_ws = mock_ws_cls.return_value
    mock_ws.repo_dir = config.workspace_dir
    mock_ws.branch_name.return_value = "jarvis/issue-42"
    mock_ws.check_diff_limits.return_value = (False, "Exceeds file limit: 25 files changed, 600 LOC (max 20 files)")

    mock_gh = mock_gh_cls.return_value
    mock_gh.clone_url = "https://github.com/owner/repo.git"

    orch = _make_orch(config)
    orch._handlers = {"owner/repo": MagicMock()}
    orch._handlers["owner/repo"].gh = mock_gh
    orch._handlers["owner/repo"].workspace = mock_ws

    run = orch.process_issue(mock_issue, Trigger.CLI)

    assert run.status == RunStatus.BLOCKED
    assert "exceeds limits" in run.error.lower()
    mock_ws.commit_and_push.assert_not_called()


@patch("jarvis.orchestrator.GitHubClient")
@patch("jarvis.orchestrator.Workspace")
@patch("jarvis.orchestrator.run_agent")
def test_process_issue_timeout(mock_agent, mock_ws_cls, mock_gh_cls, config, mock_issue):
    from jarvis.agent import AgentTimeoutError
    mock_agent.side_effect = AgentTimeoutError("partial output here", "claude", 1200)
    mock_ws = mock_ws_cls.return_value
    mock_ws.repo_dir = config.workspace_dir
    mock_ws.branch_name.return_value = "jarvis/issue-42"

    mock_gh = mock_gh_cls.return_value
    mock_gh.clone_url = "https://github.com/owner/repo.git"

    orch = _make_orch(config)
    orch._handlers = {"owner/repo": MagicMock()}
    orch._handlers["owner/repo"].gh = mock_gh
    orch._handlers["owner/repo"].workspace = mock_ws

    run = orch.process_issue(mock_issue, Trigger.CLI)

    assert run.status == RunStatus.TIMEOUT
    assert "timed out" in run.error.lower()
    assert run.agent_name == "claude"


def test_poll_once_skips_claimed(config, mock_issue):
    orch = _make_orch(config)

    mock_handler = MagicMock()
    mock_handler.gh.get_labeled_issues.return_value = [mock_issue]
    orch._handlers = {"owner/repo": mock_handler}

    # Pre-claim the issue
    orch.db.create_run(42, "Fix the bug", Trigger.CLI, repo="owner/repo")

    runs = orch.poll_once()
    assert len(runs) == 0
