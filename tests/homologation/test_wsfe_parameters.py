"""Reads the WSFE reference data in homologation. Run with `pytest -m homologation`.

Needs the environment variables named in conftest.py. Asks FEDummy and the receiver VAT conditions,
neither of which authorizes anything, and records every WSFE exchange, without token and sign, under
`.homologation/parameters/`.
"""

import pytest

from pyarca.core.wsfe_codes import ReceiverVatCondition
from pyarca.shell.clock import SystemClock
from pyarca.shell.endpoints import Environment
from pyarca.shell.token_store import FileTokenStore
from pyarca.shell.wsaa_client import WsaaClient
from pyarca.shell.wsfe_client import WsfeClient

from .conftest import (
    HOMOLOGATION_WSFE_URL,
    STATE_DIRECTORY,
    GuardedTransport,
    HomologationIdentity,
    strip_secrets,
)

RECORD_DIRECTORY = STATE_DIRECTORY / "parameters"


@pytest.mark.homologation
def test_the_service_is_up_and_lists_the_receiver_vat_conditions(
    identity: HomologationIdentity, token_store: FileTokenStore, transport: GuardedTransport
) -> None:
    wsaa = WsaaClient(
        signer=identity.signer,
        transport=transport,
        clock=SystemClock(),
        token_store=token_store,
        environment=Environment.HOMOLOGATION,
    )
    client = WsfeClient(
        ticket_provider=wsaa,
        transport=transport,
        environment=Environment.HOMOLOGATION,
        cuit=identity.cuit,
    )

    try:
        status = client.ping()
        conditions = {item.identifier for item in client.receiver_vat_conditions()}
    finally:
        _record_exchanges(transport)

    assert status.is_operational, status
    assert {condition.value for condition in ReceiverVatCondition} <= conditions


def _record_exchanges(transport: GuardedTransport) -> None:
    RECORD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    sent = [exchange for exchange in transport.exchanges if exchange[0] == HOMOLOGATION_WSFE_URL]
    for index, (_, action, request, response) in enumerate(sent):
        name = f"{index:02d}_{action.rpartition('/')[2]}"
        (RECORD_DIRECTORY / f"{name}_request.xml").write_bytes(strip_secrets(request))
        (RECORD_DIRECTORY / f"{name}_response.xml").write_bytes(response)
