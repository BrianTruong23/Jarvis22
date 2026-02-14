"""SQLite database for tracking runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jarvis.models import Run, RunStatus, Trigger

SCHEMA = """\
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_number INTEGER NOT NULL,
    issue_title  TEXT NOT NULL,
    repo         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending',
    trigger      TEXT NOT NULL,
    branch       TEXT,
    pr_url       TEXT,
    error        TEXT,
    agent_output TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

MIGRATIONS = [
    "ALTER TABLE runs ADD COLUMN repo TEXT NOT NULL DEFAULT '';",
    "ALTER TABLE runs ADD COLUMN agent_name TEXT;",
    "ALTER TABLE runs ADD COLUMN tokens_used INTEGER;",
]


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("PRAGMA table_info(runs)")
        columns = {row[1] for row in cursor.fetchall()}
        if "repo" not in columns or "agent_name" not in columns or "tokens_used" not in columns:
            for sql in MIGRATIONS:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass

    def _row_to_run(self, row: sqlite3.Row) -> Run:
        return Run(
            id=row["id"],
            issue_number=row["issue_number"],
            issue_title=row["issue_title"],
            repo=row["repo"],
            status=RunStatus(row["status"]),
            trigger=Trigger(row["trigger"]),
            branch=row["branch"],
            pr_url=row["pr_url"],
            error=row["error"],
            agent_output=row["agent_output"],
            agent_name=row["agent_name"],
            tokens_used=row["tokens_used"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_run(self, issue_number: int, issue_title: str, trigger: Trigger, repo: str = "") -> Run:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO runs (issue_number, issue_title, trigger, repo) VALUES (?, ?, ?, ?)",
                (issue_number, issue_title, trigger.value, repo),
            )
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._row_to_run(row)

    def update_run(
        self,
        run_id: int,
        *,
        status: RunStatus | None = None,
        branch: str | None = None,
        pr_url: str | None = None,
        error: str | None = None,
        agent_output: str | None = None,
        agent_name: str | None = None,
        tokens_used: int | None = None,
    ) -> Run:
        updates: list[str] = []
        params: list[object] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status.value)
        if branch is not None:
            updates.append("branch = ?")
            params.append(branch)
        if pr_url is not None:
            updates.append("pr_url = ?")
            params.append(pr_url)
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if agent_output is not None:
            updates.append("agent_output = ?")
            params.append(agent_output)
        if agent_name is not None:
            updates.append("agent_name = ?")
            params.append(agent_name)
        if tokens_used is not None:
            updates.append("tokens_used = ?")
            params.append(tokens_used)
        if not updates:
            return self.get_run(run_id)
        updates.append("updated_at = datetime('now')")
        params.append(run_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE runs SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_run(row)

    def get_run(self, run_id: int) -> Run:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Run {run_id} not found")
        return self._row_to_run(row)

    def get_runs_for_issue(self, issue_number: int, repo: str = "") -> list[Run]:
        with self._connect() as conn:
            if repo:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE issue_number = ? AND repo = ? ORDER BY created_at DESC",
                    (issue_number, repo),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE issue_number = ? ORDER BY created_at DESC",
                    (issue_number,),
                ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def get_all_runs(self) -> list[Run]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [self._row_to_run(r) for r in rows]

    def is_issue_claimed(self, issue_number: int, repo: str = "") -> bool:
        """Check if issue has an in-flight or terminal run.

        DEFERRED is intentionally excluded so the next poll cycle can retry.
        """
        claimed = (
            RunStatus.PENDING.value,
            RunStatus.RUNNING.value,
            RunStatus.SUCCESS.value,
            RunStatus.NEEDS_HUMAN.value,
        )
        with self._connect() as conn:
            if repo:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM runs WHERE issue_number = ? AND repo = ? AND status IN (?, ?, ?, ?)",
                    (issue_number, repo, *claimed),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM runs WHERE issue_number = ? AND status IN (?, ?, ?, ?)",
                    (issue_number, *claimed),
                ).fetchone()
        return row["cnt"] > 0
