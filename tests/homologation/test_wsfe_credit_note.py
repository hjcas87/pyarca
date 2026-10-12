"""Authorizes a Nota de Crédito C in homologation. Run with `pytest -m homologation`.

Needs the environment variables named in conftest.py. Reads the last authorized Factura C of the
point of sale (optional PYARCA_HOMOLOGATION_POINT_OF_SALE, default 1), consults it, and sends
exactly one FECAESolicitar for a Nota de Crédito C that cancels it in full. Every WSFE exchange is
recorded, without token and sign, under `.homologation/last_authorization/credit_note/`.
"""

import os
from datetime import timedelta, timezone
from decimal import Decimal

import pytest

from pyarca.core.voucher import (
    PESOS,
    PESOS_EXCHANGE_RATE,
    AssociatedVoucher,
    VoucherRequest,
)
from pyarca.core.wsaa import Service
from pyarca.core.wsfe import (
    AuthorizationResult,
    ConsultedVoucher,
    build_consult_request,
    parse_consult_response,
)
from pyarca.core.wsfe_codes import Concept, DocumentType, ReceiverVatCondition, VoucherType
from pyarca.core.wsfe_xml import WsfeOperation, soap_action
from pyarca.shell.clock import SystemClock
from pyarca.shell.endpoints import WSFE_ENDPOINTS, Environment
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

POINT_OF_SALE_ENV = "PYARCA_HOMOLOGATION_POINT_OF_SALE"
DEFAULT_POINT_OF_SALE = 1
ARGENTINA = timezone(timedelta(hours=-3))
RECORD_DIRECTORY = STATE_DIRECTORY / "last_authorization" / "credit_note"
CAE_LENGTH = 14


def _credit_note(*, invoice: ConsultedVoucher, point_of_sale: int, cuit: int) -> VoucherRequest:
    return VoucherRequest(
        point_of_sale=point_of_sale,
        voucher_type=VoucherType.CREDIT_NOTE_C,
        concept=Concept.PRODUCTS,
        document_type=DocumentType.FINAL_CONSUMER,
        document_number=0,
        receiver_vat_condition=ReceiverVatCondition.FINAL_CONSUMER,
        voucher_date=SystemClock().now().astimezone(ARGENTINA).date(),
        total=invoice.total,
        non_taxed=Decimal(0),
        net=invoice.total,
        exempt=Decimal(0),
        vat_total=Decimal(0),
        vat_lines=(),
        currency=PESOS,
        exchange_rate=PESOS_EXCHANGE_RATE,
        associated_vouchers=(
            AssociatedVoucher(
                voucher_type=VoucherType.INVOICE_C,
                point_of_sale=point_of_sale,
                number=invoice.voucher_number,
                cuit=cuit,
                voucher_date=invoice.voucher_date,
            ),
        ),
    )


@pytest.mark.homologation
def test_a_credit_note_c_cancels_an_authorized_invoice_c(
    identity: HomologationIdentity, token_store: FileTokenStore, transport: GuardedTransport
) -> None:
    point_of_sale = int(os.environ.get(POINT_OF_SALE_ENV, DEFAULT_POINT_OF_SALE))
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
        invoice_number = client.last_authorized(
            point_of_sale=point_of_sale, voucher_type=VoucherType.INVOICE_C
        )
        assert invoice_number > 0, "authorize a Factura C first: there is none to cancel"
        consultation = parse_consult_response(
            transport.post(
                url=WSFE_ENDPOINTS[Environment.HOMOLOGATION],
                body=build_consult_request(
                    ticket=wsaa.get_access_ticket(Service.WSFE),
                    cuit=identity.cuit,
                    point_of_sale=point_of_sale,
                    voucher_type=VoucherType.INVOICE_C,
                    voucher_number=invoice_number,
                ),
                soap_action=soap_action(WsfeOperation.CONSULT),
            )
        )
        assert consultation.voucher is not None, consultation
        assert consultation.voucher.document_type == DocumentType.FINAL_CONSUMER
        note = _credit_note(
            invoice=consultation.voucher, point_of_sale=point_of_sale, cuit=identity.cuit
        )

        authorization = client.authorize(note)
    finally:
        _record_exchanges(transport)

    assert authorization.result == AuthorizationResult.APPROVED, authorization
    assert authorization.cae is not None
    assert len(authorization.cae) == CAE_LENGTH


def _record_exchanges(transport: GuardedTransport) -> None:
    RECORD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    sent = [exchange for exchange in transport.exchanges if exchange[0] == HOMOLOGATION_WSFE_URL]
    for index, (_, action, request, response) in enumerate(sent):
        name = f"{index:02d}_{action.rpartition('/')[2]}"
        (RECORD_DIRECTORY / f"{name}_request.xml").write_bytes(strip_secrets(request))
        (RECORD_DIRECTORY / f"{name}_response.xml").write_bytes(response)
