import time
from typing import Protocol
from .model import integer


class Clock(Protocol):
    def now(self) -> int: ...


class SystemClock:
    def now(self):
        return int(time.time())


class ManualClock:
    """Deterministic clock for tests and offline demonstrations only."""
    def __init__(self, now=0):
        self.value = integer(now)

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value = integer(self.value + integer(seconds))
