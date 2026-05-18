"""
Second stage: builds context and calls Gemini for diagnosis.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.context_builder import ContextBuilder
from agent.cost_guard import CostGuard
from agent.gemini_client import NOTIFY_ONLY_FALLBACK, GeminiClient, _normalize_plan
from agent.memory import RunbookMemory

logger = logging.getLogger(__name__)


class DiagnosisAgent:
    """Ties together context, memory, cost-guard, and the LLM."""

    def __init__(
        self,
        gemini: GeminiClient,
        context_builder: ContextBuilder,
        memory: RunbookMemory,
        cost_guard: CostGuard,
    ) -> None:
        self.gemini = gemini
        self.context = context_builder
        self.memory = memory
        self.cost_guard = cost_guard

    def diagnose(self, triage_result: dict[str, Any]) -> dict[str, Any]:
        alert = triage_result.get("alert", {}) or {}
        alert_name = triage_result.get("alert_name", "UnknownAlert")

        context = self.context.build(alert)

        if not self.cost_guard.check_and_increment():
            plan = dict(NOTIFY_ONLY_FALLBACK)
            plan["reason"] = "Daily Gemini request budget exhausted — notify_only."
            logger.warning("Cost guard denied Gemini call for %s", alert_name)
            return _normalize_plan(plan)

        past_cases = self.memory.recall(alert_name)
        plan = self.gemini.diagnose(context, past_cases=past_cases)
        plan.setdefault("alert_name", alert_name)
        return plan
