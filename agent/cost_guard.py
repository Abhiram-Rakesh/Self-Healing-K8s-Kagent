"""
Daily Gemini API request budget enforcer.

Counts API calls per day. When limit is reached, switches the
agent to notify-only mode until midnight UTC resets the counter.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_DAILY_LIMIT = int(os.environ.get("DAILY_REQUEST_LIMIT", "200"))


class CostGuard:
    """Thread-safe daily request counter with midnight-UTC reset."""

    def __init__(self, daily_limit: int | None = None) -> None:
        self.daily_limit = int(
            daily_limit if daily_limit is not None else DEFAULT_DAILY_LIMIT
        )
        self._lock = threading.Lock()
        self._count = 0
        self._day = self._today()
        self._warned_at_80 = False

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _rollover_if_new_day(self) -> None:
        today = self._today()
        if today != self._day:
            logger.info(
                "CostGuard: new UTC day %s — resetting counter (was %d)",
                today,
                self._count,
            )
            self._day = today
            self._count = 0
            self._warned_at_80 = False

    def check_and_increment(self) -> bool:
        """Return True if the call is allowed; False if the daily budget is exhausted."""
        with self._lock:
            self._rollover_if_new_day()
            if self._count >= self.daily_limit:
                logger.error(
                    "CostGuard: daily limit reached (%d/%d) — denying call",
                    self._count,
                    self.daily_limit,
                )
                return False
            self._count += 1
            if (
                not self._warned_at_80
                and self._count >= int(0.8 * self.daily_limit)
                and self.daily_limit > 0
            ):
                logger.warning(
                    "CostGuard: 80%% of daily limit consumed (%d/%d)",
                    self._count,
                    self.daily_limit,
                )
                self._warned_at_80 = True
            return True

    def remaining(self) -> int:
        with self._lock:
            self._rollover_if_new_day()
            return max(0, self.daily_limit - self._count)

    def used(self) -> int:
        with self._lock:
            self._rollover_if_new_day()
            return self._count
