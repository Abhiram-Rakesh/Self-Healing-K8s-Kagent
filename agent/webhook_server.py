"""
HTTP server receiving Alertmanager webhook POSTs.

Returns 200 immediately, processes alerts asynchronously.
Pipeline: triage -> diagnosis -> remediation -> audit.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agent.agents import (
    AuditAgent,
    DiagnosisAgent,
    RemediationAgent,
    TriageAgent,
)

logger = logging.getLogger(__name__)

VERSION = "1.0.0"


def _time_stage(metrics: Any, stage: str, fn: Any, *args: Any) -> Any:
    """Call fn(*args), recording duration and incrementing error counter on exception."""
    t = time.time()
    try:
        return fn(*args)
    except Exception:
        if metrics:
            try:
                metrics["stage_errors"].labels(stage=stage).inc()
            except Exception:
                pass
        raise
    finally:
        if metrics:
            try:
                metrics["stage_duration"].labels(stage=stage).observe(time.time() - t)
            except Exception:
                pass


class HealingPipeline:
    """Bundles the four pipeline stages for a single request."""

    def __init__(
        self,
        triage: TriageAgent,
        diagnosis: DiagnosisAgent,
        remediation: RemediationAgent,
        audit: AuditAgent,
        metrics: Any = None,
    ) -> None:
        self.triage = triage
        self.diagnosis = diagnosis
        self.remediation = remediation
        self.audit = audit
        self.metrics = metrics  # optional dict of Prometheus metric objects

    def process_alert(self, alert: dict[str, Any]) -> dict[str, Any] | None:
        start = time.time()
        if alert.get("status") == "resolved":
            logger.info("Skipping resolved alert")
            return None

        triage_result = _time_stage(self.metrics, "triage", self.triage.triage, alert)
        if triage_result is None:
            return None

        if self.metrics:
            try:
                self.metrics["alerts_total"].labels(
                    severity=triage_result.get("severity", "unknown")
                ).inc()
            except Exception:
                pass

        plan = _time_stage(self.metrics, "diagnosis", self.diagnosis.diagnose, triage_result)

        if self.metrics:
            try:
                self.metrics["gemini_calls_total"].inc()
                self.metrics["confidence_gauge"].set(float(plan.get("confidence", 0.0)))
            except Exception:
                pass

        result = _time_stage(self.metrics, "remediation", self.remediation.execute, plan)

        if self.metrics:
            try:
                self.metrics["actions_total"].labels(
                    action=str(result.get("action")),
                    executed=str(result.get("executed")).lower(),
                ).inc()
                self.metrics["healing_seconds"].observe(time.time() - start)
            except Exception:
                pass

        record = _time_stage(
            self.metrics, "audit", self.audit.record, triage_result, plan, result
        )
        logger.info("Pipeline result: %s", json.dumps(record, default=str))
        return record


def _make_handler(pipeline: HealingPipeline) -> type[BaseHTTPRequestHandler]:
    class WebhookHandler(BaseHTTPRequestHandler):
        server_version = f"KAgentHealer/{VERSION}"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            logger.debug("%s - %s", self.address_string(), format % args)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/health", "/healthz", "/readyz"):
                self._send_json(200, {"status": "ok", "version": VERSION})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in ("/webhook", "/"):
                self._send_json(404, {"error": "not found"})
                return

            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send_json(400, {"error": "malformed JSON"})
                return

            alerts = payload.get("alerts") if isinstance(payload, dict) else None
            if not isinstance(alerts, list):
                # Treat the whole body as a single alert (some emitters do this)
                alerts = [payload] if isinstance(payload, dict) else []

            for alert in alerts:
                if not isinstance(alert, dict):
                    continue
                t = threading.Thread(
                    target=_safe_process,
                    args=(pipeline, alert),
                    daemon=True,
                )
                t.start()

            self._send_json(200, {"received": len(alerts)})

    return WebhookHandler


def _safe_process(pipeline: HealingPipeline, alert: dict[str, Any]) -> None:
    try:
        pipeline.process_alert(alert)
    except Exception as exc:  # never let a single alert crash the server
        logger.exception("Pipeline crashed processing alert: %s", exc)


class WebhookServer:
    """ThreadingHTTPServer wrapper. Call start() to block-serve."""

    def __init__(self, pipeline: HealingPipeline, host: str = "0.0.0.0", port: int = 8000) -> None:
        self.host = host
        self.port = port
        self.pipeline = pipeline
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        handler = _make_handler(self.pipeline)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        logger.info("Webhook server listening on %s:%d", self.host, self.port)
        try:
            self._server.serve_forever()
        finally:
            if self._server is not None:
                self._server.server_close()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
