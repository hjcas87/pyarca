from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from pyarca.core.amounts import format_amount
from pyarca.core.soap import MalformedResponseError, ResponseDefect, SoapFaultError
from pyarca.core.voucher import InvalidVoucherError, VoucherDefect, VoucherRequest
from pyarca.core.wsaa import AccessTicket
from pyarca.core.wsfe import (
    ArcaMessage,
    AuthorizationResult,
    build_authorize_request,
    parse_authorize_response,
)

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


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_an_approved_response_yields_the_cae_and_its_due_date() -> None:
    authorization = parse_authorize_response(_fixture("authorize_response_approved.xml"))

    assert authorization.result == AuthorizationResult.APPROVED
    assert authorization.voucher_number == VOUCHER_NUMBER
    assert authorization.cae == "76412345678901"
    assert authorization.cae_due_date == date(2026, 10, 22)
    assert authorization.observations == ()
    assert authorization.errors == ()
    assert authorization.events == ()


def test_an_approved_response_keeps_its_observations_and_events() -> None:
    authorization = parse_authorize_response(
        _fixture("authorize_response_approved_with_observations.xml")
    )

    assert authorization.result == AuthorizationResult.APPROVED
    assert authorization.cae == "76412345678901"
    assert [message.code for message in authorization.observations] == [10245]
    assert authorization.observations[0].message.startswith("Observation sample")
    assert authorization.events == (
        ArcaMessage(code=39, message="Event sample: scheduled maintenance."),
    )


def test_a_rejected_response_carries_no_cae_and_says_why() -> None:
    authorization = parse_authorize_response(_fixture("authorize_response_rejected.xml"))

    assert authorization.result == AuthorizationResult.REJECTED
    assert authorization.cae is None
    assert authorization.cae_due_date is None
    assert [message.code for message in authorization.observations] == [10048]


def test_a_response_with_only_errors_is_a_rejection_that_reports_them() -> None:
    authorization = parse_authorize_response(_fixture("authorize_response_errors.xml"))

    assert authorization.result == AuthorizationResult.REJECTED
    assert authorization.voucher_number is None
    assert [message.code for message in authorization.errors] == [10016]


def test_a_soap_fault_is_raised_with_its_code() -> None:
    with pytest.raises(SoapFaultError) as error:
        parse_authorize_response(_fixture("fault.xml"))

    assert error.value.code == "Server"
    assert error.value.description == "Server was unable to process request."


@pytest.mark.parametrize(
    ("old", "new", "defect", "element"),
    [
        (b"<CAE>76412345678901</CAE>", b"<CAE></CAE>", ResponseDefect.MISSING_ELEMENT, "CAE"),
        (
            b"<CAEFchVto>20261022</CAEFchVto>",
            b"<CAEFchVto>2026-10-22</CAEFchVto>",
            ResponseDefect.INVALID_DATE,
            "CAEFchVto",
        ),
        (
            b"<CbteDesde>7</CbteDesde>",
            b"<CbteDesde>seven</CbteDesde>",
            ResponseDefect.INVALID_NUMBER,
            "CbteDesde",
        ),
        (
            b"<Resultado>A</Resultado>\n            <CAE>",
            b"<Resultado>X</Resultado>\n            <CAE>",
            ResponseDefect.INVALID_VALUE,
            "Resultado",
        ),
    ],
)
def test_an_approved_response_with_unreadable_values_is_malformed(
    old: bytes, new: bytes, defect: ResponseDefect, element: str
) -> None:
    response = _fixture("authorize_response_approved.xml").replace(old, new)

    with pytest.raises(MalformedResponseError) as error:
        parse_authorize_response(response)

    assert error.value.defect == defect
    assert error.value.element == element


def test_a_response_with_neither_a_result_nor_errors_is_malformed() -> None:
    response = (
        b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        b'<FECAESolicitarResponse xmlns="http://ar.gov.afip.dif.FEV1/"/></s:Body></s:Envelope>'
    )

    with pytest.raises(MalformedResponseError) as error:
        parse_authorize_response(response)

    assert error.value.defect == ResponseDefect.MISSING_ELEMENT
    assert error.value.element == "FECAESolicitarResult"


@pytest.mark.parametrize(
    ("response", "element"),
    [
        (
            _fixture("authorize_response_approved.xml").replace(
                b"<Resultado>A</Resultado>\n            <CAE>", b"<CAE>"
            ),
            "Resultado",
        ),
        (
            (
                b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                b'<FECAESolicitarResponse xmlns="http://ar.gov.afip.dif.FEV1/">'
                b"<FECAESolicitarResult/></FECAESolicitarResponse></s:Body></s:Envelope>"
            ),
            "FECAEDetResponse",
        ),
    ],
)
def test_a_response_missing_its_result_is_malformed(response: bytes, element: str) -> None:
    with pytest.raises(MalformedResponseError) as error:
        parse_authorize_response(response)

    assert error.value.element == element
