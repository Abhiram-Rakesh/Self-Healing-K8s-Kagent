"""
First stage of the healing pipeline.

Deduplicates alerts (5-minute TTL) and classifies severity.
Returns None for duplicates so they are silently dropped.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEDUP_TTL_SECONDS = 300
SEVERITY_WEIGHTS = {"critical": 3, "warning": 2, "info": 1}


class TriageAgent:
    """Deduplicates Alertmanager webhooks and adds a severity score."""

    def __init__(self, ttl_seconds: int = DEDUP_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    @staticmethod
    def _alert_key(alert: dict[str, Any]) -> str:
        labels = alert.get("labels") or {}
        return (
            f"{labels.get('alertname', 'unknown')}:"
            f"{labels.get('namespace', '-')}:"
            f"{labels.get('pod', '-')}"
        )

    def _prune(self, now: float) -> None:
        expired = [k for k, ts in self._seen.items() if now - ts >= self.ttl_seconds]
        for k in expired:
            self._seen.pop(k, None)

    def triage(self, alert: dict[str, Any]) -> dict[str, Any] | None:
        """Return a triage result dict, or None to drop the alert."""
        labels = alert.get("labels") or {}
        severity = str(labels.get("severity", "info")).lower()
        key = self._alert_key(alert)
        now = time.time()

        with self._lock:
            self._prune(now)
            last_seen = self._seen.get(key)
            if last_seen is not None and now - last_seen < self.ttl_seconds:
                logger.info("Triage: duplicate alert %s — dropping", key)
                return None
            self._seen[key] = now

        result = {
            "alert_key": key,
            "alert_name": labels.get("alertname", "UnknownAlert"),
            "severity": severity,
            "severity_weight": SEVERITY_WEIGHTS.get(severity, 1),
            "namespace": labels.get("namespace", ""),
            "pod": labels.get("pod", ""),
            "alert": alert,
        }
        logger.info(
            "Triage: accepted alert %s (severity=%s weight=%d)",
            key,
            severity,
            result["severity_weight"],
        )
        return result
