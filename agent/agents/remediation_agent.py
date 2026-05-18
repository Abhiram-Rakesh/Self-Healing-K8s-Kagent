"""
Third stage: executes the healing action with safety gates.

High-impact actions (cordon_node) require HITL approval via Slack.
Auto-approves after 300s if no response received.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from agent.remediator import Remediator

logger = logging.getLogger(__name__)

REQUIRES_APPROVAL = {"cordon_node", "drain_node"}
APPROVAL_TIMEOUT_SECONDS = int(os.environ.get("APPROVAL_TIMEOUT_SECONDS", "300"))


class RemediationAgent:
    """Executes the plan via Remediator, optionally gated by Slack approval."""

    def __init__(
        self,
        remediator: Remediator,
        slack_webhook_url: str | None = None,
        approval_timeout_seconds: int = APPROVAL_TIMEOUT_SECONDS,
    ) -> None:
        self.remediator = remediator
        self.slack_webhook_url = slack_webhook_url or os.environ.get(
            "SLACK_WEBHOOK_URL", ""
        )
        self.approval_timeout_seconds = int(approval_timeout_seconds)

    def _request_approval(self, plan: dict[str, Any]) -> bool:
        """V1: best-effort Slack notification; auto-approve after timeout."""
        if not self.slack_webhook_url:
            logger.info(
                "No Slack webhook configured — auto-approving high-impact action %s",
                plan.get("action"),
            )
            return True

        msg = {
            "text": (
                f":warning: KAgent high-impact action pending approval\n"
                f"*Action:* `{plan.get('action')}`\n"
                f"*Target:* `{plan.get('target_namespace')}/{plan.get('target')}`\n"
                f"*Confidence:* `{plan.get('confidence', 0.0):.2f}`\n"
                f"*Reason:* {plan.get('reason', '')}\n"
                f"_Auto-approve in {self.approval_timeout_seconds}s._"
            )
        }
        try:
            requests.post(self.slack_webhook_url, json=msg, timeout=5)
        except Exception as exc:
            logger.warning("Slack approval notification failed: %s", exc)

        # V1: no interactive callback yet — sleep until timeout then auto-approve.
        logger.info(
            "Waiting %ds for human approval of %s (auto-approve on timeout)",
            self.approval_timeout_seconds,
            plan.get("action"),
        )
        time.sleep(self.approval_timeout_seconds)
        return True

    def execute(self, plan: dict[str, Any]) -> dict[str, Any]:
        action = str(plan.get("action", "no_action"))
        if action in REQUIRES_APPROVAL:
            approved = self._request_approval(plan)
            if not approved:
                logger.warning("HITL approval denied for %s", action)
                return {
                    "action": action,
                    "target": plan.get("target", "unknown"),
                    "namespace": plan.get("target_namespace", "unknown"),
                    "confidence": float(plan.get("confidence", 0.0)),
                    "executed": False,
                    "reason": "HITL approval denied",
                    "dry_run": False,
                }
        return self.remediator.execute(plan)
