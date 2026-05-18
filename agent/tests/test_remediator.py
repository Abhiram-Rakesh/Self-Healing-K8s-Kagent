"""Tests for the Remediator safety gates and actions."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from agent.remediator import Remediator


@pytest.fixture(autouse=True)
def _reset_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default each test to live mode unless it overrides.
    monkeypatch.setenv("DRY_RUN", "false")
    yield


def _make_remediator(
    confidence_threshold: float = 0.75,
    max_replicas: int = 10,
) -> Remediator:
    r = Remediator(confidence_threshold=confidence_threshold, max_replicas=max_replicas)
    r._configured = True  # type: ignore[attr-defined]
    r._apps = MagicMock()  # type: ignore[attr-defined]
    r._core = MagicMock()  # type: ignore[attr-defined]
    return r


def _plan(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "diagnosis": "test",
        "action": "restart_pod",
        "target": "myapp",
        "target_namespace": "default",
        "reason": "test",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def test_low_confidence_not_executed() -> None:
    r = _make_remediator()
    res = r.execute(_plan(confidence=0.5))
    assert res["executed"] is False
    assert "below threshold" in res["reason"]


def test_protected_namespace_blocks() -> None:
    r = _make_remediator()
    res = r.execute(_plan(target_namespace="kube-system"))
    assert res["executed"] is False
    assert "protected" in res["reason"].lower()


def test_dry_run_skips_real_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    r = _make_remediator()
    res = r.execute(_plan())
    assert res["executed"] is True
    assert res["dry_run"] is True
    r._apps.patch_namespaced_deployment.assert_not_called()  # type: ignore[attr-defined]


def test_restart_pod_patches_annotation() -> None:
    r = _make_remediator()
    res = r.execute(_plan(action="restart_pod"))
    assert res["executed"] is True
    args, kwargs = r._apps.patch_namespaced_deployment.call_args  # type: ignore[attr-defined]
    body = kwargs.get("body") or args[-1]
    annotations = body["spec"]["template"]["metadata"]["annotations"]
    assert "kubectl.kubernetes.io/restartedAt" in annotations


def test_scale_up_increments_replicas() -> None:
    r = _make_remediator()
    dep = MagicMock()
    dep.spec.replicas = 3
    r._apps.read_namespaced_deployment.return_value = dep  # type: ignore[attr-defined]
    res = r.execute(_plan(action="scale_up"))
    assert res["executed"] is True
    _, kwargs = r._apps.patch_namespaced_deployment_scale.call_args  # type: ignore[attr-defined]
    assert kwargs["body"]["spec"]["replicas"] == 4


def test_scale_up_respects_max() -> None:
    r = _make_remediator(max_replicas=5)
    dep = MagicMock()
    dep.spec.replicas = 5
    r._apps.read_namespaced_deployment.return_value = dep  # type: ignore[attr-defined]
    res = r.execute(_plan(action="scale_up"))
    # Already at cap — patch not called, but execute path returns success.
    assert res["executed"] is True
    r._apps.patch_namespaced_deployment_scale.assert_not_called()  # type: ignore[attr-defined]


def test_notify_only_short_circuits() -> None:
    r = _make_remediator()
    res = r.execute(_plan(action="notify_only"))
    assert res["executed"] is True
    r._apps.patch_namespaced_deployment.assert_not_called()  # type: ignore[attr-defined]
