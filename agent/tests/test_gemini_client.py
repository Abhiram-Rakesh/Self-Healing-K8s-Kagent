"""Tests for the Gemini client wrapper."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agent.gemini_client import GeminiClient


def _make_client() -> GeminiClient:
    c = GeminiClient(api_key="fake-key", max_retries=4)
    # Force the "client constructed" path so retries/backoff can run.
    c._client = object()  # type: ignore[attr-defined]
    return c


def test_valid_json_response_parsed() -> None:
    client = _make_client()
    response = json.dumps(
        {
            "diagnosis": "OOM killed container",
            "action": "restart_pod",
            "target": "myapp",
            "target_namespace": "default",
            "reason": "memory limit too low",
            "confidence": 0.91,
        }
    )
    with patch.object(client, "_call_api", return_value=response):
        plan = client.diagnose({"alert_name": "PodOOMKilled"})
    assert plan["action"] == "restart_pod"
    assert plan["target"] == "myapp"
    assert plan["confidence"] == pytest.approx(0.91)


def test_markdown_fences_stripped() -> None:
    client = _make_client()
    fenced = (
        "```json\n"
        + json.dumps(
            {
                "diagnosis": "fence test",
                "action": "no_action",
                "target": "n/a",
                "target_namespace": "n/a",
                "reason": "no fix needed",
                "confidence": 0.99,
            }
        )
        + "\n```"
    )
    with patch.object(client, "_call_api", return_value=fenced):
        plan = client.diagnose({})
    assert plan["action"] == "no_action"
    assert plan["diagnosis"] == "fence test"


def test_unparseable_json_falls_back_to_notify_only() -> None:
    client = _make_client()
    with patch.object(client, "_call_api", return_value="this is not JSON"):
        plan = client.diagnose({})
    assert plan["action"] == "notify_only"
    assert plan["confidence"] == 0.0


def test_low_confidence_coerced_to_notify_only() -> None:
    client = _make_client()
    response = json.dumps(
        {
            "diagnosis": "uncertain",
            "action": "restart_pod",
            "target": "x",
            "target_namespace": "default",
            "reason": "guessing",
            "confidence": 0.5,
        }
    )
    with patch.object(client, "_call_api", return_value=response):
        plan = client.diagnose({})
    assert plan["action"] == "notify_only"


def test_rate_limit_retries_with_backoff() -> None:
    client = _make_client()
    good = json.dumps(
        {
            "diagnosis": "ok",
            "action": "restart_pod",
            "target": "x",
            "target_namespace": "default",
            "reason": "ok",
            "confidence": 0.9,
        }
    )

    calls = {"n": 0}

    def fake_call(_prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED rate limited")
        return good

    with patch("agent.gemini_client.time.sleep") as sleep_mock, patch.object(
        client, "_call_api", side_effect=fake_call
    ):
        plan = client.diagnose({})
    assert plan["action"] == "restart_pod"
    assert calls["n"] == 3
    assert sleep_mock.call_count == 2  # slept before retries 2 and 3


def test_past_cases_injected_into_prompt() -> None:
    client = _make_client()
    good = json.dumps(
        {
            "diagnosis": "ok",
            "action": "restart_pod",
            "target": "x",
            "target_namespace": "default",
            "reason": "ok",
            "confidence": 0.9,
        }
    )
    captured = {}

    def fake_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return good

    past = "- [2026-01-01] diagnosis='memory leak' action=restart_pod outcome=executed confidence=0.92"
    with patch.object(client, "_call_api", side_effect=fake_call):
        client.diagnose({"alert_name": "OOM"}, past_cases=past)

    assert "Relevant past cases" in captured["prompt"]
    assert "memory leak" in captured["prompt"]


def test_past_cases_omitted_when_empty() -> None:
    client = _make_client()
    good = json.dumps(
        {
            "diagnosis": "ok",
            "action": "no_action",
            "target": "n/a",
            "target_namespace": "n/a",
            "reason": "ok",
            "confidence": 0.9,
        }
    )
    captured = {}

    def fake_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return good

    with patch.object(client, "_call_api", side_effect=fake_call):
        client.diagnose({}, past_cases="No past cases.")
    assert "Relevant past cases" not in captured["prompt"]
