"""Logs in to the real WSAA homologation service. Run with `pytest -m homologation`.

Needs the environment variables named in conftest.py: PEM files of a homologation certificate and
its CUIT. Nothing is sent unless the certificate was issued by ARCA's homologation CA. Tickets are
kept under `.homologation/`, so a later run reuses them instead of being refused by WSAA.
"""

import pytest
from cryptography import x509

from pyarca.core.wsaa import Service
from pyarca.shell.clock import SystemClock
from pyarca.shell.endpoints import Environment
from pyarca.shell.environment_guard import is_homologation_issuer, issuer_of
from pyarca.shell.token_store import FileTokenStore, TicketKey
from pyarca.shell.wsaa_client import WsaaClient

from .conftest import GuardedTransport, HomologationIdentity


def test_the_guard_refuses_a_certificate_not_issued_by_the_homologation_ca(
    certificate: x509.Certificate,
) -> None:
    assert not is_homologation_issuer(issuer_of(certificate))


@pytest.mark.homologation
def test_login_with_a_homologation_certificate(
    identity: HomologationIdentity, token_store: FileTokenStore, transport: GuardedTransport
) -> None:
    client = WsaaClient(
        signer=identity.signer,
        transport=transport,
        clock=SystemClock(),
        token_store=token_store,
        environment=Environment.HOMOLOGATION,
    )

    ticket = client.get_access_ticket(Service.WSFE)

    key = TicketKey(
        certificate_id=identity.signer.certificate_id,
        service=Service.WSFE,
        environment=Environment.HOMOLOGATION,
    )
    assert ticket.token
    assert ticket.sign
    assert ticket.expires_at > SystemClock().now()
    assert token_store.get(key) == ticket
