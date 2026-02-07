"""Git workspace management: clone, branch, commit, push."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from jarvis.config import Config

log = logging.getLogger(__name__)


class Workspace:
    def __init__(self, config: Config, clone_url: str, repo_name: str) -> None:
        self._config = config
        self._clone_url = clone_url
        self._repo_name = repo_name
        self._repo_dir = Path(config.workspace_dir) / repo_name.replace("/", "_")

    @property
    def repo_dir(self) -> Path:
        return self._repo_dir

    def _run(self, cmd: list[str], cwd: Path | None = None) -> str:
        log.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
        result = subprocess.run(
            cmd,
            cwd=cwd or self._repo_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(cmd)}\nstderr: {result.stderr}")
        return result.stdout.strip()

    def ensure_repo(self) -> None:
        if (self._repo_dir / ".git").exists():
            log.info("[%s] Repo already cloned, pulling latest", self._repo_name)
            self._run(["git", "fetch", "--all"])
            default = self._get_default_branch()
            self._run(["git", "checkout", default])
            self._run(["git", "reset", "--hard", f"origin/{default}"])
        else:
            log.info("[%s] Cloning repo to %s", self._repo_name, self._repo_dir)
            self._repo_dir.mkdir(parents=True, exist_ok=True)
            self._run(
                ["git", "clone", self._clone_url, str(self._repo_dir)],
                cwd=self._repo_dir.parent,
            )
        self._run(["git", "config", "user.email", "jarvis@bot.dev"])
        self._run(["git", "config", "user.name", "Jarvis"])

    def _get_default_branch(self) -> str:
        output = self._run(["git", "remote", "show", "origin"])
        for line in output.splitlines():
            if "HEAD branch" in line:
                return line.split(":")[-1].strip()
        return "main"

    def create_branch(self, branch: str) -> None:
        try:
            self._run(["git", "branch", "-D", branch])
            log.info("[%s] Deleted existing local branch %s", self._repo_name, branch)
        except RuntimeError:
            pass
        try:
            self._run(["git", "push", "origin", "--delete", branch])
            log.info("[%s] Deleted existing remote branch %s", self._repo_name, branch)
        except RuntimeError:
            pass
        default = self._get_default_branch()
        self._run(["git", "checkout", "-b", branch, f"origin/{default}"])
        log.info("[%s] Created branch %s", self._repo_name, branch)

    def check_diff_limits(self, max_files: int, max_loc: int) -> tuple[bool, str]:
        """Check if the current diff exceeds file/LOC limits.

        Returns (within_limits, detail_message).
        """
        try:
            numstat = self._run(["git", "diff", "--numstat", "HEAD"])
        except RuntimeError:
            return True, "No diff to check"

        if not numstat:
            return True, "No changes"

        files_changed = 0
        total_loc = 0
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            files_changed += 1
            added = int(parts[0]) if parts[0] != "-" else 0
            removed = int(parts[1]) if parts[1] != "-" else 0
            total_loc += added + removed

        detail = f"{files_changed} files changed, {total_loc} LOC"

        if files_changed > max_files:
            return False, f"Exceeds file limit: {detail} (max {max_files} files)"
        if total_loc > max_loc:
            return False, f"Exceeds LOC limit: {detail} (max {max_loc} LOC)"

        return True, detail

    def commit_and_push(self, branch: str, message: str) -> bool:
        status = self._run(["git", "status", "--porcelain"])
        if not status:
            log.warning("[%s] No changes to commit", self._repo_name)
            return False
        self._run(["git", "add", "-A"])
        self._run(["git", "commit", "-m", message])
        self._run(["git", "push", "-u", "origin", branch])
        log.info("[%s] Pushed branch %s", self._repo_name, branch)
        return True

    def branch_name(self, issue_number: int) -> str:
        return f"{self._config.branch_prefix}{issue_number}"
