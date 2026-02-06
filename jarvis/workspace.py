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
