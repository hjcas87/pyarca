"""The system clock, the only place in the package that reads the time."""

from datetime import UTC, datetime

from pyarca.shell.ports import Clock


class SystemClock(Clock):
    """Reads the time from the operating system."""

    def now(self) -> datetime:
        """Return the current time in UTC."""
        return datetime.now(UTC)
