"""Git workspace management: clone, branch, commit, push."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from jarvis.config import Config

log = logging.getLogger(__name__)


class Workspace:
    def __init__(self, config: Config, clone_url: str) -> None:
        self._config = config
        self._clone_url = clone_url
        self._repo_dir = Path(config.workspace_dir) / config.target_repo.replace("/", "_")

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
            log.info("Repo already cloned, pulling latest")
            self._run(["git", "fetch", "--all"])
            default = self._get_default_branch()
            self._run(["git", "checkout", default])
            self._run(["git", "reset", "--hard", f"origin/{default}"])
        else:
            log.info("Cloning repo to %s", self._repo_dir)
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
        # Delete branch if it already exists (from failed run)
        try:
            self._run(["git", "branch", "-D", branch])
            log.info("Deleted existing local branch %s", branch)
        except RuntimeError:
            pass
        try:
            self._run(["git", "push", "origin", "--delete", branch])
            log.info("Deleted existing remote branch %s", branch)
        except RuntimeError:
            pass
        default = self._get_default_branch()
        self._run(["git", "checkout", "-b", branch, f"origin/{default}"])
        log.info("Created branch %s", branch)

    def commit_and_push(self, branch: str, message: str) -> bool:
        # Check if there are changes to commit
        status = self._run(["git", "status", "--porcelain"])
        if not status:
            log.warning("No changes to commit")
            return False
        self._run(["git", "add", "-A"])
        self._run(["git", "commit", "-m", message])
        self._run(["git", "push", "-u", "origin", branch])
        log.info("Pushed branch %s", branch)
        return True

    def branch_name(self, issue_number: int) -> str:
        return f"{self._config.branch_prefix}{issue_number}"
