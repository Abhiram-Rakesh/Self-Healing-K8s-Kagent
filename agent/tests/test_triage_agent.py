"""Tests for the TriageAgent dedup + severity classification."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from agent.agents.triage_agent import SEVERITY_WEIGHTS, TriageAgent


def _alert(name: str = "PodCrashLooping", severity: str = "critical") -> dict:
    return {
        "labels": {
            "alertname": name,
            "severity": severity,
            "namespace": "default",
            "pod": "myapp-abc",
        }
    }


def test_first_alert_passes_through() -> None:
    t = TriageAgent()
    res = t.triage(_alert())
    assert res is not None
    assert res["alert_name"] == "PodCrashLooping"
    assert res["severity"] == "critical"
    assert res["severity_weight"] == SEVERITY_WEIGHTS["critical"]


def test_duplicate_within_ttl_is_dropped() -> None:
    t = TriageAgent(ttl_seconds=300)
    assert t.triage(_alert()) is not None
    assert t.triage(_alert()) is None


def test_duplicate_after_ttl_passes() -> None:
    t = TriageAgent(ttl_seconds=300)
    base = time.time()
    with patch("agent.agents.triage_agent.time.time", return_value=base):
        assert t.triage(_alert()) is not None
    with patch("agent.agents.triage_agent.time.time", return_value=base + 301):
        assert t.triage(_alert()) is not None


def test_severity_weights() -> None:
    assert SEVERITY_WEIGHTS == {"critical": 3, "warning": 2, "info": 1}


@pytest.mark.parametrize(
    "severity,expected",
    [("critical", 3), ("warning", 2), ("info", 1), ("unknown", 1)],
)
def test_severity_weight_lookup(severity: str, expected: int) -> None:
    t = TriageAgent()
    res = t.triage(_alert(severity=severity))
    assert res is not None
    assert res["severity_weight"] == expected
