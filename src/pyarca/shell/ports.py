"""Interfaces the shell needs from the outside world, so callers and tests can replace them."""

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pyarca.core.wsaa import AccessTicket, Service
    from pyarca.shell.environment_guard import CertificateIssuer
    from pyarca.shell.token_store import TicketKey


class Signer(Protocol):
    """Signs the login ticket request with the taxpayer's certificate."""

    @property
    def certificate_id(self) -> str:
        """Identify the certificate, so access tickets are stored per certificate."""

    @property
    def issuer(self) -> "CertificateIssuer":
        """Identify who issued the certificate, so it is not used in the wrong environment."""

    def sign(self, data: bytes) -> bytes:
        """Return `data` wrapped in a CMS signed structure, DER encoded."""


class Transport(Protocol):
    """Sends a SOAP request and returns the response body."""

    def post(self, *, url: str, body: bytes, soap_action: str) -> bytes:
        """Post `body` to `url` and return the body of the answer, including SOAP faults.

        `soap_action` is the operation's SOAPAction without quotes; WSAA's is empty.
        """


class Clock(Protocol):
    """Tells the current time."""

    def now(self) -> datetime:
        """Return the current time, timezone-aware."""


class TokenStore(Protocol):
    """Keeps access tickets between logins; share one across processes to share tickets."""

    def get(self, key: "TicketKey") -> "AccessTicket | None":
        """Return the ticket saved for `key`, if any."""

    def save(self, key: "TicketKey", ticket: "AccessTicket") -> None:
        """Save `ticket` for `key`, replacing the previous one."""


class TicketProvider(Protocol):
    """Hands out a valid access ticket for a service, logging in only when needed."""

    def get_access_ticket(self, service: "Service") -> "AccessTicket":
        """Return a valid access ticket for `service`."""
