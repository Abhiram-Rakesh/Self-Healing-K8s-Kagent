"""Tests for the Kubernetes ContextBuilder."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.context_builder import ContextBuilder


def _make_builder() -> ContextBuilder:
    cb = ContextBuilder()
    cb._configured = True  # type: ignore[attr-defined]
    cb._core = MagicMock()  # type: ignore[attr-defined]
    return cb


def _alert() -> dict:
    return {
        "labels": {
            "alertname": "PodCrashLooping",
            "severity": "critical",
            "namespace": "default",
            "pod": "myapp-abc",
        }
    }


def test_previous_logs_used_when_available() -> None:
    cb = _make_builder()

    def fake_logs(*, name: str, namespace: str, tail_lines: int, previous: bool) -> str:
        return "PREVIOUS LOGS" if previous else "CURRENT LOGS"

    cb._core.read_namespaced_pod_log.side_effect = fake_logs  # type: ignore[attr-defined]
    # Provide minimum needed for describe/node lookups.
    cb._core.read_namespaced_pod.return_value = SimpleNamespace(  # type: ignore[attr-defined]
        spec=SimpleNamespace(containers=[], node_name="ip-10-0-1-2"),
        status=SimpleNamespace(phase="Running", container_statuses=[]),
    )
    cb._core.list_namespaced_event.return_value = SimpleNamespace(items=[])  # type: ignore[attr-defined]
    cb._core.read_node.return_value = SimpleNamespace(  # type: ignore[attr-defined]
        status=SimpleNamespace(conditions=[])
    )

    ctx = cb.build(_alert())
    assert "PREVIOUS LOGS" in ctx["pod_logs"]


def test_falls_back_to_current_logs_when_previous_unavailable() -> None:
    cb = _make_builder()
    calls = {"previous": 0, "current": 0}

    def fake_logs(*, name: str, namespace: str, tail_lines: int, previous: bool) -> str:
        if previous:
            calls["previous"] += 1
            raise RuntimeError("previous unavailable")
        calls["current"] += 1
        return "CURRENT LOGS"

    cb._core.read_namespaced_pod_log.side_effect = fake_logs  # type: ignore[attr-defined]
    cb._core.read_namespaced_pod.return_value = SimpleNamespace(  # type: ignore[attr-defined]
        spec=SimpleNamespace(containers=[], node_name=""),
        status=SimpleNamespace(phase="Running", container_statuses=[]),
    )
    cb._core.list_namespaced_event.return_value = SimpleNamespace(items=[])  # type: ignore[attr-defined]

    ctx = cb.build(_alert())
    assert "CURRENT LOGS" in ctx["pod_logs"]
    assert calls["previous"] == 1
    assert calls["current"] == 1


def test_returns_unavailable_on_k8s_error() -> None:
    cb = _make_builder()
    cb._core.read_namespaced_pod_log.side_effect = RuntimeError("boom")  # type: ignore[attr-defined]
    cb._core.read_namespaced_pod.side_effect = RuntimeError("boom")  # type: ignore[attr-defined]
    cb._core.list_namespaced_event.side_effect = RuntimeError("boom")  # type: ignore[attr-defined]
    cb._core.read_node.side_effect = RuntimeError("boom")  # type: ignore[attr-defined]

    ctx = cb.build(_alert())
    assert ctx["pod_logs"].startswith("Unavailable")
    assert isinstance(ctx["pod_describe"], str)
    assert ctx["pod_describe"].startswith("Unavailable")
    assert ctx["k8s_events"] == []


def test_events_sorted_by_timestamp_descending() -> None:
    cb = _make_builder()

    older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 5, 1, tzinfo=timezone.utc)

    e1 = SimpleNamespace(
        type="Warning",
        reason="BackOff",
        message="older",
        count=2,
        last_timestamp=older,
    )
    e2 = SimpleNamespace(
        type="Warning",
        reason="BackOff",
        message="newer",
        count=5,
        last_timestamp=newer,
    )
    cb._core.list_namespaced_event.return_value = SimpleNamespace(items=[e1, e2])  # type: ignore[attr-defined]
    cb._core.read_namespaced_pod_log.return_value = "logs"  # type: ignore[attr-defined]
    cb._core.read_namespaced_pod.return_value = SimpleNamespace(  # type: ignore[attr-defined]
        spec=SimpleNamespace(containers=[], node_name=""),
        status=SimpleNamespace(phase="Running", container_statuses=[]),
    )

    ctx = cb.build(_alert())
    assert [e["message"] for e in ctx["k8s_events"]] == ["newer", "older"]
