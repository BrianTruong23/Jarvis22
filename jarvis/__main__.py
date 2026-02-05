"""CLI entry point: python -m jarvis <command>."""

from __future__ import annotations

import argparse
import logging
import sys

from jarvis.config import Config


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_poll(config: Config, args: argparse.Namespace) -> None:
    from jarvis.poller import run_poller
    run_poller(config)


def cmd_run(config: Config, args: argparse.Namespace) -> None:
    from jarvis.orchestrator import Orchestrator
    from jarvis.models import Trigger
    orch = Orchestrator(config)
    orch.run_single(args.issue_number, Trigger.CLI)


def cmd_webhook(config: Config, args: argparse.Namespace) -> None:
    from jarvis.webhook import run_webhook
    run_webhook(config)


def cmd_status(config: Config, args: argparse.Namespace) -> None:
    from jarvis.db import Database
    db = Database(config.db_path)

    if args.issue_number:
        runs = db.get_runs_for_issue(args.issue_number)
    else:
        runs = db.get_all_runs()

    if not runs:
        print("No runs found.")
        return

    for r in runs:
        pr = f" -> {r.pr_url}" if r.pr_url else ""
        err = f" | error: {r.error[:80]}" if r.error else ""
        print(f"  #{r.id:>4}  issue={r.issue_number:<6} {r.status.value:<8} {r.trigger.value:<8} {r.created_at}{pr}{err}")


def cmd_report(config: Config, args: argparse.Namespace) -> None:
    from jarvis.db import Database
    from jarvis.report import format_summary_report, format_issue_report
    db = Database(config.db_path)

    if args.issue_number:
        print(format_issue_report(db, args.issue_number))
    else:
        print(format_summary_report(db))


def main() -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis22 — Autonomous coding agent orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("poll", help="Start polling loop")

    run_parser = sub.add_parser("run", help="Process a single issue")
    run_parser.add_argument("issue_number", type=int, help="GitHub issue number")

    sub.add_parser("webhook", help="Start webhook server")

    status_parser = sub.add_parser("status", help="Show run status")
    status_parser.add_argument("issue_number", type=int, nargs="?", help="Filter by issue number")

    report_parser = sub.add_parser("report", help="Show run report")
    report_parser.add_argument("issue_number", type=int, nargs="?", help="Show report for specific issue")

    args = parser.parse_args()
    config = Config.from_env()
    setup_logging(config.log_level)

    # Validate config for commands that need external services
    if args.command in ("poll", "run", "webhook"):
        errors = config.validate()
        if errors:
            for e in errors:
                print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    handler = {
        "poll": cmd_poll,
        "run": cmd_run,
        "webhook": cmd_webhook,
        "status": cmd_status,
        "report": cmd_report,
    }
    handler[args.command](config, args)


if __name__ == "__main__":
    main()
