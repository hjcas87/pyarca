"""Interfaces the shell needs from the outside world, so callers and tests can replace them."""

from typing import Protocol


class Signer(Protocol):
    """Signs the login ticket request with the taxpayer's certificate."""

    def sign(self, data: bytes) -> bytes:
        """Return `data` wrapped in a CMS signed structure, DER encoded."""
