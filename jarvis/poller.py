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
    labels = ", ".join(config.issue_labels)
    log.info(
        "Starting poller: repos=[%s], labels=[%s], interval=%ds, max_issues_per_poll=%d",
        repos,
        labels,
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

        time.sleep(config.poll_interval)
