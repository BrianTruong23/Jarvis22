# Jarvis22

Autonomous coding agent orchestrator that watches a GitHub repo for issues, spawns Claude Code CLI to solve them, and opens PRs with the results.

## Quickstart

### 1. Configure

```bash
cp .env.example .env
# Edit .env with your tokens and target repo
```

### 2. Install

```bash
pip install -e ".[dev]"
```

### 3. Run

```bash
# Process a single issue
python -m jarvis run 42

# Start polling loop
python -m jarvis poll

# Check status
python -m jarvis status
python -m jarvis report
```

### Docker

```bash
docker compose up -d          # Start poller
docker compose logs -f        # Watch logs

# With webhook server
docker compose --profile webhook up -d
```

## CLI Reference

| Command | Description |
|---|---|
| `python -m jarvis poll` | Start polling loop |
| `python -m jarvis run <N>` | Process issue #N |
| `python -m jarvis webhook` | Start webhook server |
| `python -m jarvis status [N]` | Show run status (optionally for issue N) |
| `python -m jarvis report [N]` | Show report (optionally for issue N) |

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | Yes | — | GitHub PAT with repo scope |
| `TARGET_REPO` | Yes | — | `owner/repo` format |
| `ANTHROPIC_API_KEY` | Yes | — | For Claude Code CLI |
| `POLL_INTERVAL` | No | `60` | Seconds between polls |
| `ISSUE_LABEL` | No | `jarvis` | Label to watch |
| `DONE_LABEL` | No | `jarvis-done` | Label added on completion |
| `WORKSPACE_DIR` | No | `/tmp/jarvis-workspace` | Clone directory |
| `DB_PATH` | No | `jarvis.db` | SQLite path |
| `BRANCH_PREFIX` | No | `jarvis/issue-` | Branch naming |
| `CLAUDE_MODEL` | No | `sonnet` | Model for agent |
| `CLAUDE_MAX_BUDGET` | No | `5.00` | Max USD per run |
| `WEBHOOK_PORT` | No | `8080` | Webhook listen port |
| `WEBHOOK_SECRET` | No | `""` | GitHub webhook secret |
| `LOG_LEVEL` | No | `INFO` | Logging level |

## Architecture

```
GitHub Issue (labeled "jarvis")
        │
        ▼
   ┌─────────┐
   │ Poller / │──── polls every N seconds
   │ Webhook  │──── or receives webhook event
   └────┬─────┘
        │
        ▼
  ┌──────────────┐
  │ Orchestrator  │──── claims issue in SQLite
  └──┬───────────┘
     │
     ├──▶ Workspace: clone/pull repo, create branch
     │
     ├──▶ Agent: spawn `claude --print` with issue context
     │
     ├──▶ Workspace: commit + push changes
     │
     ├──▶ GitHub: create PR, swap labels, comment
     │
     └──▶ DB: record result
```

## How It Works

1. **Watch**: Poller checks for open issues with the `jarvis` label, or webhook receives label events
2. **Claim**: Orchestrator creates a run record in SQLite (prevents duplicate processing)
3. **Workspace**: Clones/pulls the target repo and creates a feature branch
4. **Agent**: Spawns Claude Code CLI with the issue context as a prompt
5. **Commit**: Commits any file changes the agent made and pushes the branch
6. **PR**: Creates a pull request linking back to the issue
7. **Report**: Comments on the issue with the result (success or failure)

## Deploy to a VPS

### Prerequisites

- A VPS with Docker and Docker Compose installed (Ubuntu 22.04+ recommended)
- A GitHub PAT with `repo` scope
- An Anthropic API key

### Step-by-step

```bash
# 1. SSH into your VPS
ssh user@your-vps-ip

# 2. Clone the repo
git clone https://github.com/thangtruong/Jarvis22.git
cd Jarvis22

# 3. Create and fill in your .env
cp .env.example .env
nano .env   # Set GITHUB_TOKEN, TARGET_REPO, ANTHROPIC_API_KEY

# 4. Start the poller (runs in background, restarts on crash)
docker compose up -d

# 5. Check logs
docker compose logs -f

# 6. (Optional) Also run the webhook server
docker compose --profile webhook up -d
```

### Managing

```bash
# View status from inside the container
docker compose exec poller python -m jarvis status

# View reports
docker compose exec poller python -m jarvis report

# Process a specific issue manually
docker compose exec poller python -m jarvis run 42

# Restart after config change
docker compose down && docker compose up -d

# Update to latest code
git pull && docker compose up -d --build
```

### Without Docker

```bash
# 1. Clone and enter repo
git clone https://github.com/thangtruong/Jarvis22.git
cd Jarvis22

# 2. Install Python 3.11+ and Node.js 20+, then install Claude Code CLI
npm install -g @anthropic-ai/claude-code

# 3. Install Python deps
pip install -e .

# 4. Configure
cp .env.example .env
nano .env

# 5. Source env and run
export $(grep -v '^#' .env | xargs)
python -m jarvis poll

# Or use a process manager like systemd or tmux to keep it running
```

## CI

Tests run automatically on push and PR via GitHub Actions (`.github/workflows/ci.yml`). To run locally:

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```
