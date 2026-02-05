"""Polling loop that periodically checks for new issues."""

from __future__ import annotations

import logging
import time

from jarvis.config import Config
from jarvis.orchestrator import Orchestrator

log = logging.getLogger(__name__)


def run_poller(config: Config) -> None:
    orch = Orchestrator(config)
    log.info(
        "Starting poller: repo=%s, label=%s, interval=%ds",
        config.target_repo,
        config.issue_label,
        config.poll_interval,
    )

    while True:
        try:
            count = orch.poll_once()
            if count:
                log.info("Processed %d issue(s)", count)
            else:
                log.debug("No new issues found")
        except KeyboardInterrupt:
            log.info("Poller stopped by user")
            break
        except Exception:
            log.exception("Error during poll cycle")

        time.sleep(config.poll_interval)
