"""Polling loop and single-cycle poll for scheduled runs."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from jarvis.config import Config
from jarvis.orchestrator import Orchestrator
from jarvis.report import commit_reports, generate_session_report, write_report_file

log = logging.getLogger(__name__)


def run_poller(config: Config) -> None:
    """Continuous polling loop."""
    orch = Orchestrator(config)
    repos = ", ".join(config.target_repos)
    log.info(
        "Starting poller: repos=[%s], label=%s+%s, interval=%ds",
        repos,
        config.issue_label,
        config.ready_label,
        config.poll_interval,
    )

    while True:
        try:
            runs = orch.poll_once()
            if runs:
                log.info("Processed %d issue(s) across repos", len(runs))
            else:
                log.debug("No new issues found")
        except KeyboardInterrupt:
            log.info("Poller stopped by user")
            break
        except Exception:
            log.exception("Error during poll cycle")

        time.sleep(config.poll_interval)


def run_poll_once(config: Config) -> None:
    """Single poll cycle with session timeout, reports, and exit."""
    orch = Orchestrator(config)
    repos = ", ".join(config.target_repos)
    log.info(
        "Starting single poll cycle: repos=[%s], label=%s+%s, session_timeout=%ds",
        repos,
        config.issue_label,
        config.ready_label,
        config.session_timeout,
    )

    try:
        runs = orch.poll_once()

        if runs:
            log.info("Processed %d issue(s)", len(runs))

            # Write session report
            session_content = generate_session_report(runs)
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            session_filename = f"{date}_session-summary.md"
            write_report_file(session_content, session_filename, config)

            # Commit and push reports to Jarvis22 repo
            commit_reports(config, f"report: session {date} — {len(runs)} issues processed")
        else:
            log.info("No issues to process")

    except Exception:
        log.exception("Error during poll-once cycle")

    log.info("Poll-once complete, exiting")
