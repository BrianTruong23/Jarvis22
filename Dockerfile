FROM python:3.12-slim

# Install git and Node.js (for Claude Code CLI)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI and Codex CLI (fallback agent)
RUN npm install -g @anthropic-ai/claude-code @openai/codex

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application
COPY jarvis/ jarvis/

# Default command
CMD ["python", "-m", "jarvis", "poll"]
