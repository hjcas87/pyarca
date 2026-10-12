"""Obtains a real CAE from the WSFE homologation service. Run with `pytest -m homologation`.

Needs the environment variables named in conftest.py. Sends exactly one FECAESolicitar, to
consumidor final, and records its request and response (without token and sign) under
`.homologation/last_authorization/`. Optional: PYARCA_HOMOLOGATION_POINT_OF_SALE (default 1) and
PYARCA_HOMOLOGATION_VOUCHER_TYPE (6 for Factura B, 11 for Factura C, default 11).
"""

import os
import re
from collections.abc import Callable
from datetime import date, timedelta, timezone
from decimal import Decimal

import pytest

from pyarca.core.voucher import PESOS, PESOS_EXCHANGE_RATE, VatLine, VoucherRequest
from pyarca.core.wsfe import AuthorizationResult
from pyarca.core.wsfe_codes import (
    Concept,
    DocumentType,
    ReceiverVatCondition,
    VatRate,
    VoucherType,
)
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
)

POINT_OF_SALE_ENV = "PYARCA_HOMOLOGATION_POINT_OF_SALE"
VOUCHER_TYPE_ENV = "PYARCA_HOMOLOGATION_VOUCHER_TYPE"
DEFAULT_POINT_OF_SALE = 1
DEFAULT_VOUCHER_TYPE = VoucherType.INVOICE_C
ARGENTINA = timezone(timedelta(hours=-3))
RECORD_DIRECTORY = STATE_DIRECTORY / "last_authorization"
CAE_LENGTH = 14
SECRET_ELEMENT = re.compile(rb"(<(?:\w+:)?(Token|Sign)>)[^<]*(</)")


def _invoice_c(*, point_of_sale: int, voucher_date: date) -> VoucherRequest:
    return VoucherRequest(
        point_of_sale=point_of_sale,
        voucher_type=VoucherType.INVOICE_C,
        concept=Concept.PRODUCTS,
        document_type=DocumentType.FINAL_CONSUMER,
        document_number=0,
        receiver_vat_condition=ReceiverVatCondition.FINAL_CONSUMER,
        voucher_date=voucher_date,
        total=Decimal("100.00"),
        non_taxed=Decimal(0),
        net=Decimal("100.00"),
        exempt=Decimal(0),
        vat_total=Decimal(0),
        vat_lines=(),
        currency=PESOS,
        exchange_rate=PESOS_EXCHANGE_RATE,
    )


def _invoice_b(*, point_of_sale: int, voucher_date: date) -> VoucherRequest:
    return VoucherRequest(
        point_of_sale=point_of_sale,
        voucher_type=VoucherType.INVOICE_B,
        concept=Concept.PRODUCTS,
        document_type=DocumentType.FINAL_CONSUMER,
        document_number=0,
        receiver_vat_condition=ReceiverVatCondition.FINAL_CONSUMER,
        voucher_date=voucher_date,
        total=Decimal("121.00"),
        non_taxed=Decimal(0),
        net=Decimal("100.00"),
        exempt=Decimal(0),
        vat_total=Decimal("21.00"),
        vat_lines=(VatLine(rate=VatRate.RATE_21, base=Decimal("100.00"), amount=Decimal("21.00")),),
        currency=PESOS,
        exchange_rate=PESOS_EXCHANGE_RATE,
    )


VOUCHERS: dict[VoucherType, Callable[..., VoucherRequest]] = {
    VoucherType.INVOICE_B: _invoice_b,
    VoucherType.INVOICE_C: _invoice_c,
}


def _strip_secrets(document: bytes) -> bytes:
    return SECRET_ELEMENT.sub(rb"\1REDACTED\3", document)


@pytest.mark.homologation
def test_authorize_an_invoice_to_a_final_consumer_obtains_a_cae(
    identity: HomologationIdentity, token_store: FileTokenStore, transport: GuardedTransport
) -> None:
    voucher_type = VoucherType(int(os.environ.get(VOUCHER_TYPE_ENV, DEFAULT_VOUCHER_TYPE)))
    point_of_sale = int(os.environ.get(POINT_OF_SALE_ENV, DEFAULT_POINT_OF_SALE))
    clock = SystemClock()
    today = clock.now().astimezone(ARGENTINA).date()
    voucher = VOUCHERS[voucher_type](point_of_sale=point_of_sale, voucher_date=today)
    wsaa = WsaaClient(
        signer=identity.signer,
        transport=transport,
        clock=clock,
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
        authorization = client.authorize(voucher)
    finally:
        _record_exchange(transport)

    assert authorization.result == AuthorizationResult.APPROVED, authorization
    assert authorization.cae is not None
    assert len(authorization.cae) == CAE_LENGTH
    assert authorization.cae_due_date is not None
    assert authorization.cae_due_date >= today


def _record_exchange(transport: GuardedTransport) -> None:
    sent = [exchange for exchange in transport.exchanges if exchange[0] == HOMOLOGATION_WSFE_URL]
    if not sent:
        return
    _, action, request, response = sent[-1]
    RECORD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    name = action.rpartition("/")[2]
    (RECORD_DIRECTORY / f"{name}_request.xml").write_bytes(_strip_secrets(request))
    (RECORD_DIRECTORY / f"{name}_response.xml").write_bytes(response)
