"""Storage for access tickets."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pyarca.core.wsaa import AccessTicket, Service
from pyarca.shell.endpoints import Environment
from pyarca.shell.ports import TokenStore

DIRECTORY_MODE = 0o700
TICKET_FILE_SUFFIX = ".json"
TEMPORARY_FILE_SUFFIX = ".tmp"


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


class StoredTicketError(Exception):
    """A stored ticket file cannot be read back; it is reported, not silently replaced."""

    def __init__(self, path: Path) -> None:
        """Build the error naming the unreadable file."""
        super().__init__(f"unreadable access ticket file: {path}")
        self.path = path


class FileTokenStore(TokenStore):
    """Keeps tickets in a directory, one file per key, readable only by the owner.

    A process restart, or another process using the same directory, finds the ticket again, so
    WSAA is not asked for a login it would refuse while the previous one is still valid.
    """

    def __init__(self, directory: Path) -> None:
        """Keep tickets under `directory`, created on the first save."""
        self._directory = directory

    def get(self, key: TicketKey) -> AccessTicket | None:
        """Return the ticket saved for `key`, if any.

        Raises:
            StoredTicketError: If the file exists but does not hold a ticket.
        """
        path = self._path(key)
        if not path.exists():
            return None
        try:
            stored = json.loads(path.read_bytes())
            return AccessTicket(
                token=stored["token"],
                sign=stored["sign"],
                expires_at=datetime.fromisoformat(stored["expires_at"]),
            )
        except (ValueError, KeyError, TypeError) as error:
            raise StoredTicketError(path) from error

    def save(self, key: TicketKey, ticket: AccessTicket) -> None:
        """Save `ticket` for `key`, replacing the previous one atomically."""
        self._directory.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "token": ticket.token,
                "sign": ticket.sign,
                "expires_at": ticket.expires_at.isoformat(),
            }
        ).encode()
        # mkstemp creates the file readable by its owner only.
        descriptor, temporary = tempfile.mkstemp(dir=self._directory, suffix=TEMPORARY_FILE_SUFFIX)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(payload)
            temporary_path.replace(self._path(key))
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    def _path(self, key: TicketKey) -> Path:
        # The certificate id is hashed so a caller's identifier never becomes part of a path.
        certificate = hashlib.sha256(key.certificate_id.encode()).hexdigest()
        name = f"{key.environment}-{key.service}-{certificate}{TICKET_FILE_SUFFIX}"
        return self._directory / name
