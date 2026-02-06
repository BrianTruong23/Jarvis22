"""Tests for the database module."""

import os
import tempfile

import pytest

from jarvis.db import Database
from jarvis.models import RunStatus, Trigger


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    d = Database(db_path)
    yield d
    os.unlink(db_path)


def test_create_run(db: Database):
    run = db.create_run(1, "Test issue", Trigger.CLI, repo="owner/repo")
    assert run.id is not None
    assert run.issue_number == 1
    assert run.issue_title == "Test issue"
    assert run.status == RunStatus.PENDING
    assert run.trigger == Trigger.CLI
    assert run.repo == "owner/repo"


def test_update_run_status(db: Database):
    run = db.create_run(1, "Test issue", Trigger.CLI)
    updated = db.update_run(run.id, status=RunStatus.RUNNING)
    assert updated.status == RunStatus.RUNNING


def test_update_run_fields(db: Database):
    run = db.create_run(1, "Test issue", Trigger.CLI)
    updated = db.update_run(
        run.id,
        status=RunStatus.SUCCESS,
        branch="jarvis/issue-1",
        pr_url="https://github.com/test/repo/pull/1",
        agent_output="did some work",
    )
    assert updated.status == RunStatus.SUCCESS
    assert updated.branch == "jarvis/issue-1"
    assert updated.pr_url == "https://github.com/test/repo/pull/1"
    assert updated.agent_output == "did some work"


def test_get_run(db: Database):
    run = db.create_run(1, "Test issue", Trigger.CLI)
    fetched = db.get_run(run.id)
    assert fetched.id == run.id
    assert fetched.issue_number == 1


def test_get_run_not_found(db: Database):
    with pytest.raises(ValueError, match="not found"):
        db.get_run(999)


def test_get_runs_for_issue(db: Database):
    db.create_run(1, "Issue 1", Trigger.CLI, repo="owner/repo")
    db.create_run(1, "Issue 1 retry", Trigger.CLI, repo="owner/repo")
    db.create_run(2, "Issue 2", Trigger.CLI, repo="owner/repo")
    runs = db.get_runs_for_issue(1)
    assert len(runs) == 2
    assert all(r.issue_number == 1 for r in runs)


def test_get_runs_for_issue_filtered_by_repo(db: Database):
    db.create_run(1, "Issue 1 repo A", Trigger.CLI, repo="owner/repoA")
    db.create_run(1, "Issue 1 repo B", Trigger.CLI, repo="owner/repoB")
    runs = db.get_runs_for_issue(1, repo="owner/repoA")
    assert len(runs) == 1
    assert runs[0].repo == "owner/repoA"


def test_get_all_runs(db: Database):
    db.create_run(1, "Issue 1", Trigger.CLI)
    db.create_run(2, "Issue 2", Trigger.POLL)
    runs = db.get_all_runs()
    assert len(runs) == 2


def test_is_issue_claimed_pending(db: Database):
    db.create_run(1, "Issue 1", Trigger.CLI, repo="owner/repo")
    assert db.is_issue_claimed(1, repo="owner/repo") is True


def test_is_issue_claimed_success(db: Database):
    run = db.create_run(1, "Issue 1", Trigger.CLI, repo="owner/repo")
    db.update_run(run.id, status=RunStatus.SUCCESS)
    assert db.is_issue_claimed(1, repo="owner/repo") is True


def test_is_issue_claimed_failed_allows_retry(db: Database):
    run = db.create_run(1, "Issue 1", Trigger.CLI, repo="owner/repo")
    db.update_run(run.id, status=RunStatus.FAILED)
    assert db.is_issue_claimed(1, repo="owner/repo") is False


def test_is_issue_unclaimed(db: Database):
    assert db.is_issue_claimed(99, repo="owner/repo") is False


def test_is_issue_claimed_scoped_to_repo(db: Database):
    db.create_run(1, "Issue 1", Trigger.CLI, repo="owner/repoA")
    assert db.is_issue_claimed(1, repo="owner/repoA") is True
    assert db.is_issue_claimed(1, repo="owner/repoB") is False
