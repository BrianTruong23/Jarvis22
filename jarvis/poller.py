"""Polling loop that periodically checks for new issues."""

from __future__ import annotations

import logging
import time

from jarvis.config import Config
from jarvis.orchestrator import Orchestrator

log = logging.getLogger(__name__)


def run_poller(config: Config) -> None:
    orch = Orchestrator(config)
    repos = ", ".join(config.target_repos)
    log.info(
        "Starting poller: repos=[%s], labels=[%s,%s,%s,%s], interval=%ds, max_issues_per_poll=%d",
        repos,
        config.issue_label,
        config.model_label_claude,
        config.model_label_codex,
        config.model_label_gemini,
        config.poll_interval,
        config.max_issues_per_poll,
    )

    while True:
        try:
            count = orch.poll_once()
            if count:
                log.info("Processed %d issue(s) across repos", count)
            else:
                log.debug("No new issues found")
        except KeyboardInterrupt:
            log.info("Poller stopped by user")
            break
        except Exception:
            log.exception("Error during poll cycle")

        # If Claude was unavailable recently, poll more frequently so we start
        # work quickly after limits are restored.
        sleep_s = 10 if orch.claude_unavailable_recently else config.poll_interval
        time.sleep(sleep_s)
