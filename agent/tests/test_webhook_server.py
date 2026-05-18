"""Tests for the webhook HTTP handler."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import MagicMock

import pytest

from agent.webhook_server import HealingPipeline, WebhookServer


@pytest.fixture
def pipeline() -> HealingPipeline:
    pipe = MagicMock(spec=HealingPipeline)
    return pipe


@pytest.fixture
def server(pipeline: HealingPipeline) -> WebhookServer:  # type: ignore[no-redef]
    srv = WebhookServer(pipeline, host="127.0.0.1", port=0)
    # Bind to an OS-assigned port by constructing the handler/server manually.
    from agent.webhook_server import _make_handler
    from http.server import ThreadingHTTPServer

    handler = _make_handler(pipeline)
    srv._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.host, srv.port = srv._server.server_address
    t = threading.Thread(target=srv._server.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.stop()
    srv._server.server_close()  # type: ignore[union-attr]


def _url(srv: WebhookServer, path: str) -> str:
    return f"http://{srv.host}:{srv.port}{path}"


def test_get_health_returns_ok(server: WebhookServer) -> None:
    with urllib.request.urlopen(_url(server, "/health"), timeout=2) as r:
        assert r.status == 200
        body = json.loads(r.read())
    assert body["status"] == "ok"
    assert "version" in body


def test_post_webhook_returns_immediately(
    server: WebhookServer, pipeline: HealingPipeline
) -> None:
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "PodCrashLooping",
                    "namespace": "default",
                    "pod": "x",
                    "severity": "critical",
                },
            }
        ]
    }
    req = urllib.request.Request(
        _url(server, "/webhook"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as r:
        assert r.status == 200
        body = json.loads(r.read())
    assert body["received"] == 1
    # Async processing — give the worker thread a moment.
    for _ in range(50):
        if pipeline.process_alert.called:
            break
        time.sleep(0.02)
    pipeline.process_alert.assert_called()


def test_resolved_alerts_are_processed_but_skipped_inside_pipeline(
    server: WebhookServer, pipeline: HealingPipeline
) -> None:
    payload = {"alerts": [{"status": "resolved", "labels": {"alertname": "x"}}]}
    req = urllib.request.Request(
        _url(server, "/webhook"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as r:
        assert r.status == 200


def test_malformed_json_returns_400(server: WebhookServer) -> None:
    req = urllib.request.Request(
        _url(server, "/webhook"),
        data=b"not-json",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=2)
    assert exc_info.value.code == 400
