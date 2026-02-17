"""Minimal HTTP webhook server using stdlib."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

from jarvis.config import Config
from jarvis.models import Trigger
from jarvis.orchestrator import Orchestrator

log = logging.getLogger(__name__)


class WebhookHandler(BaseHTTPRequestHandler):
    config: Config
    orchestrator: Orchestrator

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        if not self._verify_signature(body):
            self._respond(403, {"error": "Invalid signature"})
            return

        event = self.headers.get("X-GitHub-Event", "")
        if event != "issues":
            self._respond(200, {"status": "ignored", "event": event})
            return

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "Invalid JSON"})
            return

        action = payload.get("action", "")
        if action != "labeled":
            self._respond(200, {"status": "ignored", "action": action})
            return

        label_name = payload.get("label", {}).get("name", "")
        if label_name not in self.config.issue_labels:
            self._respond(200, {"status": "ignored", "label": label_name})
            return

        repo_name = payload.get("repository", {}).get("full_name", "")
        if repo_name not in self.config.target_repos:
            self._respond(200, {"status": "ignored", "repo": repo_name})
            return

        issue_number = payload["issue"]["number"]
        log.info("Webhook: [%s] issue #%d labeled with %s", repo_name, issue_number, label_name)

        self._respond(200, {"status": "accepted", "repo": repo_name, "issue": issue_number})

        try:
            self.orchestrator.run_single(issue_number, repo_name, Trigger.WEBHOOK)
        except Exception:
            log.exception("Webhook: failed to process [%s] issue #%d", repo_name, issue_number)

    def _verify_signature(self, body: bytes) -> bool:
        secret = self.config.webhook_secret
        if not secret:
            return True
        signature = self.headers.get("X-Hub-Signature-256", "")
        if not signature:
            log.warning("Missing X-Hub-Signature-256 header")
            return False
        expected = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    def _respond(self, status: int, data: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format: str, *args: object) -> None:
        log.debug(format, *args)


def run_webhook(config: Config) -> None:
    orch = Orchestrator(config)
    WebhookHandler.config = config
    WebhookHandler.orchestrator = orch

    server = HTTPServer(("0.0.0.0", config.webhook_port), WebhookHandler)
    log.info("Webhook server listening on port %d", config.webhook_port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Webhook server stopped by user")
    finally:
        server.server_close()
