from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass


class BusyError(RuntimeError):
    """Raised when the run-lock is already held by another invocation."""

    def __init__(self, holder: str) -> None:
        super().__init__(f"another operation is in progress: {holder}")
        self.holder = holder


@dataclass
class RuntimeState:
    """Mutable bot-wide runtime state. Lives only in memory."""

    maintenance: bool = False
    last_health_ts: float = 0.0
    last_health_ok: bool = False

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()
        self._holder: str | None = None

    @property
    def lock_holder(self) -> str | None:
        return self._holder

    @property
    def lock_held(self) -> bool:
        return self._lock.locked()

    @asynccontextmanager
    async def acquire_run(self, holder: str):
        """Acquire the global Run-Command lock or raise BusyError immediately.

        We do NOT wait — concurrent destructive operations are exactly the
        scenario we want to prevent. The user is told to retry.
        """
        if self._lock.locked():
            raise BusyError(self._holder or "unknown")
        await self._lock.acquire()
        self._holder = holder
        try:
            yield
        finally:
            self._holder = None
            self._lock.release()
