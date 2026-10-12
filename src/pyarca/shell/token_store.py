"""Storage for access tickets."""

from dataclasses import dataclass

from pyarca.core.wsaa import AccessTicket, Service
from pyarca.shell.endpoints import Environment
from pyarca.shell.ports import TokenStore


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketKey:
    """Scope of an access ticket: the same one WSAA uses to refuse a repeated login."""

    certificate_id: str
    service: Service
    environment: Environment


class InMemoryTokenStore(TokenStore):
    """Keeps tickets in this process only."""

    def __init__(self) -> None:
        """Start with no tickets."""
        self._tickets: dict[TicketKey, AccessTicket] = {}

    def get(self, key: TicketKey) -> AccessTicket | None:
        """Return the ticket saved for `key`, if any."""
        return self._tickets.get(key)

    def save(self, key: TicketKey, ticket: AccessTicket) -> None:
        """Save `ticket` for `key`, replacing the previous one."""
        self._tickets[key] = ticket
