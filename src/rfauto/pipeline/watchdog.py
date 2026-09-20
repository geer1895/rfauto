"""Timeout watchdog with license-release-aware backoff.

Starts a background timer that calls a callback on timeout.
Includes license-release-aware backoff for reconnect.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class Watchdog:
    """Timeout watchdog that triggers a callback on expiry.

    Usage:
        wd = Watchdog()
        wd.start(timeout_s=300, callback=my_cleanup)
        # ... do work ...
        wd.cancel()  # or wd.reset() to restart timer
    """

    def __init__(self) -> None:
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._callback: Callable[[], Any] | None = None
        self._timeout_s: float = 0.0
        self._fired: bool = False

    def start(self, timeout_s: float, callback: Callable[[], Any]) -> None:
        """Start the watchdog timer."""
        with self._lock:
            self.cancel_locked()
            self._timeout_s = timeout_s
            self._callback = callback
            self._fired = False
            self._timer = threading.Timer(timeout_s, self._on_timeout)
            self._timer.daemon = True
            self._timer.start()
            logger.debug("Watchdog started: timeout=%ss", timeout_s)

    def cancel(self) -> None:
        """Cancel the watchdog timer."""
        with self._lock:
            self.cancel_locked()

    def cancel_locked(self) -> None:
        """Cancel timer (caller must hold lock)."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
            logger.debug("Watchdog cancelled")

    def reset(self) -> None:
        """Reset the watchdog timer with the same timeout and callback."""
        with self._lock:
            if self._callback is None or self._timeout_s <= 0:
                return
            self.cancel_locked()
            self._fired = False
            self._timer = threading.Timer(self._timeout_s, self._on_timeout)
            self._timer.daemon = True
            self._timer.start()
            logger.debug("Watchdog reset: timeout=%ss", self._timeout_s)

    def _on_timeout(self) -> None:
        """Called when the timer fires."""
        with self._lock:
            if self._fired:
                return
            self._fired = True
            self._timer = None

        logger.warning("Watchdog fired after %ss", self._timeout_s)
        if self._callback:
            try:
                self._callback()
            except Exception as e:
                logger.error("Watchdog callback error: %s", e)

    @property
    def fired(self) -> bool:
        """Whether the watchdog has fired."""
        return self._fired

    # License-release-aware backoff for reconnect
    @staticmethod
    def license_backoff(
        attempt: int,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: float = 0.1,
    ) -> float:
        """Calculate backoff delay with exponential backoff and jitter.

        Used when reconnecting after a license release event.
        """
        import random

        delay = min(base_delay * (2 ** attempt), max_delay)
        if jitter > 0:
            delay += random.uniform(0, delay * jitter)
        return delay
