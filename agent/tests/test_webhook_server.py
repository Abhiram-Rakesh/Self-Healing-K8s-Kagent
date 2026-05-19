"""Tests for the webhook HTTP handler."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import MagicMock

import pytest

from agent.agents import ApprovalStore
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


# ---------------------------------------------------------------------------
# ApprovalStore unit tests
# ---------------------------------------------------------------------------

def test_approval_store_approve_sets_event() -> None:
    store = ApprovalStore()
    event = store.register("action-1")
    assert not event.is_set()
    assert store.approve("action-1") is True
    assert event.is_set()


def test_approval_store_unknown_id_returns_false() -> None:
    store = ApprovalStore()
    assert store.approve("nonexistent") is False


def test_approval_store_cancel_removes_entry() -> None:
    store = ApprovalStore()
    store.register("action-2")
    store.cancel("action-2")
    assert store.pending_ids() == []


def test_approval_store_approve_twice_returns_false() -> None:
    store = ApprovalStore()
    store.register("action-3")
    store.approve("action-3")
    assert store.approve("action-3") is False  # already consumed


# ---------------------------------------------------------------------------
# Approval HTTP endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture
def store() -> ApprovalStore:
    return ApprovalStore()


@pytest.fixture
def server_with_store(
    pipeline: HealingPipeline, store: ApprovalStore
) -> WebhookServer:  # type: ignore[misc]
    from agent.webhook_server import _make_handler
    from http.server import ThreadingHTTPServer

    srv = WebhookServer(pipeline, host="127.0.0.1", port=0, approval_store=store)
    handler = _make_handler(pipeline, store)
    srv._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.host, srv.port = srv._server.server_address  # type: ignore[misc]
    t = threading.Thread(target=srv._server.serve_forever, daemon=True)
    t.start()
    yield srv  # type: ignore[misc]
    srv.stop()
    srv._server.server_close()  # type: ignore[union-attr]


def test_approve_endpoint_signals_pending_action(
    server_with_store: WebhookServer, store: ApprovalStore
) -> None:
    event = store.register("my-action-id")
    req = urllib.request.Request(
        _url(server_with_store, "/approve/my-action-id"),
        data=b"",
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as r:
        assert r.status == 200
        body = json.loads(r.read())
    assert body["approved"] == "my-action-id"
    assert event.is_set()


def test_approve_endpoint_returns_404_for_unknown_id(
    server_with_store: WebhookServer,
) -> None:
    req = urllib.request.Request(
        _url(server_with_store, "/approve/nonexistent"),
        data=b"",
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=2)
    assert exc_info.value.code == 404


# ---------------------------------------------------------------------------
# Webhook bearer-token auth tests
# ---------------------------------------------------------------------------

def test_webhook_returns_401_with_wrong_token(
    monkeypatch: pytest.MonkeyPatch, server: WebhookServer
) -> None:
    import agent.webhook_server as ws
    monkeypatch.setattr(ws, "_WEBHOOK_TOKEN", "correct-token")
    req = urllib.request.Request(
        _url(server, "/webhook"),
        data=json.dumps({"alerts": []}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer wrong-token",
        },
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=2)
    assert exc_info.value.code == 401


def test_webhook_returns_200_with_correct_token(
    monkeypatch: pytest.MonkeyPatch, server: WebhookServer
) -> None:
    import agent.webhook_server as ws
    monkeypatch.setattr(ws, "_WEBHOOK_TOKEN", "correct-token")
    req = urllib.request.Request(
        _url(server, "/webhook"),
        data=json.dumps({"alerts": []}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer correct-token",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as r:
        assert r.status == 200


def test_webhook_no_auth_required_when_token_unset(server: WebhookServer) -> None:
    import agent.webhook_server as ws
    assert ws._WEBHOOK_TOKEN == ""  # default — no token configured
    req = urllib.request.Request(
        _url(server, "/webhook"),
        data=json.dumps({"alerts": []}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as r:
        assert r.status == 200
