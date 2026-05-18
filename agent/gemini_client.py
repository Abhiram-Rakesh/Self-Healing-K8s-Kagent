"""
Gemini 2.5 Flash client for Kubernetes failure diagnosis.

Calls the Gemini API with structured prompts and returns
JSON remediation plans. Retries on rate limiting.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import — keeps unit tests free of the SDK dependency.
try:  # pragma: no cover - thin import shim
    from google import genai  # type: ignore
    from google.genai import errors as genai_errors  # type: ignore
    from google.genai import types as genai_types  # type: ignore

    _HAS_GENAI = True
except Exception:  # pragma: no cover
    genai = None  # type: ignore
    genai_errors = None  # type: ignore
    genai_types = None  # type: ignore
    _HAS_GENAI = False


DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

VALID_ACTIONS = {
    "restart_pod",
    "scale_up",
    "cordon_node",
    "notify_only",
    "no_action",
}

SYSTEM_PROMPT = """You are an expert Kubernetes Site Reliability Engineer (SRE).
You diagnose Kubernetes failures from logs, events, pod state, and node conditions,
then return a single JSON remediation plan.

STRICT RULES:
1. Output MUST be a single JSON object with these keys ONLY:
   diagnosis, action, target, target_namespace, reason, confidence
2. action MUST be one of:
   restart_pod | scale_up | cordon_node | notify_only | no_action
3. target MUST be a Deployment name. NEVER a Pod name.
4. confidence MUST be a float between 0.0 and 1.0.
5. If confidence < 0.70, action MUST be "notify_only".
6. NEVER recommend deleting namespaces or cluster-scoped resources.
7. Always prefer the least-disruptive action that addresses the root cause.
8. Do NOT include markdown fences or explanatory text — JSON only.
"""

NOTIFY_ONLY_FALLBACK: dict[str, Any] = {
    "diagnosis": "Unable to diagnose — falling back to notify_only.",
    "action": "notify_only",
    "target": "unknown",
    "target_namespace": "unknown",
    "reason": "Gemini response was unparseable or unavailable.",
    "confidence": 0.0,
}


def _strip_json_fences(text: str) -> str:
    """Remove ```json fences and surrounding whitespace."""
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text


def _normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Coerce keys, action whitelist, and confidence threshold rules."""
    action = str(plan.get("action", "notify_only")).strip()
    if action not in VALID_ACTIONS:
        logger.warning("Gemini returned unknown action %r — coercing to notify_only", action)
        action = "notify_only"

    try:
        confidence = float(plan.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    if confidence < 0.70 and action != "notify_only":
        logger.info(
            "Gemini confidence %.2f below 0.70 — coercing action %s -> notify_only",
            confidence,
            action,
        )
        action = "notify_only"

    return {
        "diagnosis": str(plan.get("diagnosis", "")).strip() or "No diagnosis provided.",
        "action": action,
        "target": str(plan.get("target", "unknown")).strip() or "unknown",
        "target_namespace": str(plan.get("target_namespace", "unknown")).strip()
        or "unknown",
        "reason": str(plan.get("reason", "")).strip() or "No reason provided.",
        "confidence": confidence,
    }


class GeminiClient:
    """Wraps Gemini API calls with retries, parsing, and safety fallbacks."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 4,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model or DEFAULT_MODEL
        self.max_retries = max_retries
        self._client = None
        if _HAS_GENAI and self.api_key:
            try:
                self._client = genai.Client(api_key=self.api_key)
            except Exception as exc:  # pragma: no cover
                logger.error("Failed to construct Gemini client: %s", exc)
                self._client = None

    def _build_prompt(self, context: dict[str, Any], past_cases: str | None) -> str:
        past_section = ""
        if past_cases and past_cases not in ("No past cases.", "Memory unavailable"):
            past_section = f"\n\nRelevant past cases:\n{past_cases}\n"
        return (
            "Diagnose this Kubernetes failure and return ONE JSON plan.\n\n"
            f"Alert context:\n{json.dumps(context, indent=2, default=str)}"
            f"{past_section}\n\n"
            "Return JSON only. No prose. No markdown."
        )

    def _call_api(self, prompt: str) -> str:
        """Call the underlying SDK. Wrapped so tests can monkey-patch easily."""
        if self._client is None:
            raise RuntimeError("Gemini client not initialized")
        # Use type-checked config when available
        if genai_types is not None:
            config = genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2,
            )
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
        else:  # pragma: no cover
            response = self._client.models.generate_content(
                model=self.model,
                contents=f"{SYSTEM_PROMPT}\n\n{prompt}",
            )
        return getattr(response, "text", "") or ""

    def diagnose(
        self,
        context: dict[str, Any],
        past_cases: str | None = None,
    ) -> dict[str, Any]:
        """Return a remediation plan dict; always returns — never raises."""
        prompt = self._build_prompt(context, past_cases)

        backoffs = [1, 2, 4, 8]
        for attempt in range(self.max_retries):
            try:
                raw = self._call_api(prompt)
            except Exception as exc:  # broad: SDK exceptions vary
                msg = str(exc)
                is_rate_limit = (
                    "429" in msg
                    or "RESOURCE_EXHAUSTED" in msg
                    or "rate" in msg.lower()
                )
                if is_rate_limit and attempt < self.max_retries - 1:
                    delay = backoffs[min(attempt, len(backoffs) - 1)]
                    logger.warning(
                        "Gemini rate-limited (attempt %d) — sleeping %ds",
                        attempt + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                logger.error("Gemini call failed: %s", exc)
                plan = dict(NOTIFY_ONLY_FALLBACK)
                plan["reason"] = f"Gemini API error: {exc}"
                return _normalize_plan(plan)

            cleaned = _strip_json_fences(raw)
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                logger.error(
                    "Gemini returned unparseable JSON (attempt %d): %s | raw=%r",
                    attempt + 1,
                    exc,
                    raw[:500],
                )
                plan = dict(NOTIFY_ONLY_FALLBACK)
                plan["reason"] = f"JSON parse error: {exc}"
                return _normalize_plan(plan)

            plan = _normalize_plan(parsed if isinstance(parsed, dict) else {})
            logger.info(
                "Gemini diagnosis: action=%s target=%s/%s confidence=%.2f",
                plan["action"],
                plan["target_namespace"],
                plan["target"],
                plan["confidence"],
            )
            return plan

        # Exhausted retries
        logger.error("Gemini exhausted %d retries — notify_only fallback", self.max_retries)
        return _normalize_plan(dict(NOTIFY_ONLY_FALLBACK))
