# Jarvis22

Autonomous coding agent orchestrator. Watches a GitHub repo for issues labeled `jarvis`, spawns Claude Code CLI to solve them, and opens PRs.

## Architecture

- **Config** (`jarvis/config.py`): Frozen dataclass from env vars
- **Models** (`jarvis/models.py`): Run, RunStatus, IssueContext, Trigger
- **DB** (`jarvis/db.py`): SQLite CRUD for runs table
- **GitHub** (`jarvis/github_client.py`): PyGithub wrapper for issues/PRs/labels
- **Workspace** (`jarvis/workspace.py`): Git clone/branch/commit/push
- **Agent** (`jarvis/agent.py`): Spawns `claude --print` subprocess
- **Orchestrator** (`jarvis/orchestrator.py`): Wires everything together
- **CLI** (`jarvis/__main__.py`): argparse entry point

## Conventions

- Python 3.11+, type hints everywhere
- Single external dep: PyGithub
- Agent is told NOT to commit — workspace.py handles git
- Failed runs don't block retry
- Single-threaded MVP

## Commands

```
python -m jarvis poll          # Start polling loop
python -m jarvis run 42        # Process issue #42
python -m jarvis webhook       # Start webhook server
python -m jarvis status        # List all runs
python -m jarvis report        # Summary report
```
