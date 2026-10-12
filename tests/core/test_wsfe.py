from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from pyarca.core.amounts import format_amount
from pyarca.core.voucher import InvalidVoucherError, VoucherDefect, VoucherRequest
from pyarca.core.wsaa import AccessTicket
from pyarca.core.wsfe import build_authorize_request

FIXTURES = Path(__file__).parent / "fixtures/wsfe"
CUIT = 20111111112
VOUCHER_NUMBER = 7
TICKET = AccessTicket(token="TOKEN", sign="SIGN", expires_at=datetime(2026, 10, 13, tzinfo=UTC))


def _canonical(document: bytes) -> bytes:
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True)
    return etree.tostring(etree.fromstring(document, parser=parser), method="c14n")


def test_amounts_are_serialized_with_exactly_two_decimals() -> None:
    assert [format_amount(Decimal(value)) for value in ("0", "100", "100.5", "1.25")] == [
        "0.00",
        "100.00",
        "100.50",
        "1.25",
    ]


def test_an_invoice_b_request_matches_the_recorded_one(invoice_b: VoucherRequest) -> None:
    request = build_authorize_request(
        ticket=TICKET, cuit=CUIT, voucher=invoice_b, voucher_number=VOUCHER_NUMBER
    )

    expected = (FIXTURES / "authorize_request_invoice_b.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


def test_an_invoice_c_request_states_no_vat(invoice_c: VoucherRequest) -> None:
    request = build_authorize_request(
        ticket=TICKET, cuit=CUIT, voucher=invoice_c, voucher_number=VOUCHER_NUMBER
    )

    expected = (FIXTURES / "authorize_request_invoice_c.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


@pytest.mark.parametrize("voucher_number", [0, -1, 100_000_000])
def test_a_voucher_number_outside_arcas_range_is_rejected(
    invoice_b: VoucherRequest, voucher_number: int
) -> None:
    with pytest.raises(InvalidVoucherError) as error:
        build_authorize_request(
            ticket=TICKET, cuit=CUIT, voucher=invoice_b, voucher_number=voucher_number
        )

    assert error.value.defect == VoucherDefect.VOUCHER_NUMBER_OUT_OF_RANGE
