from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from pyarca.core.amounts import format_amount
from pyarca.core.soap import MalformedResponseError, ResponseDefect, SoapFaultError
from pyarca.core.voucher import (
    InvalidVoucherError,
    ServicePeriod,
    VoucherDefect,
    VoucherOptional,
    VoucherRequest,
)
from pyarca.core.wsaa import AccessTicket
from pyarca.core.wsfe import (
    ArcaMessage,
    AuthorizationResult,
    build_authorize_request,
    build_consult_request,
    build_last_authorized_request,
    parse_authorize_response,
    parse_consult_response,
    parse_last_authorized_response,
)
from pyarca.core.wsfe_codes import Concept, DocumentType, OptionalId, TributeType, VoucherType

FIXTURES = Path(__file__).parent / "fixtures/wsfe"
CUIT = 20111111112
VOUCHER_NUMBER = 7
RECORDED_CUIT = 20111111112
RECORDED_VOUCHER_NUMBER = 1
RECORDED_CAE = "86410988009458"
RECORDED_TICKET = AccessTicket(
    token="REDACTED", sign="REDACTED", expires_at=datetime(2026, 10, 13, tzinfo=UTC)
)
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


def test_an_invoice_c_request_matches_the_one_homologation_authorized(
    invoice_c: VoucherRequest,
) -> None:
    request = build_authorize_request(
        ticket=RECORDED_TICKET,
        cuit=RECORDED_CUIT,
        voucher=invoice_c,
        voucher_number=RECORDED_VOUCHER_NUMBER,
    )

    expected = (FIXTURES / "authorize_request_invoice_c.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


def test_an_invoice_a_request_states_its_aliquots_and_tributes_in_the_order_arca_expects(
    invoice_a: VoucherRequest,
) -> None:
    request = build_authorize_request(
        ticket=TICKET, cuit=CUIT, voucher=invoice_a, voucher_number=VOUCHER_NUMBER
    )

    expected = (FIXTURES / "authorize_request_invoice_a.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


def test_an_fce_invoice_request_states_its_payment_due_date_and_optionals_in_order(
    fce_invoice_c: VoucherRequest,
) -> None:
    request = build_authorize_request(
        ticket=TICKET, cuit=CUIT, voucher=fce_invoice_c, voucher_number=VOUCHER_NUMBER
    )

    expected = (FIXTURES / "authorize_request_fce_invoice_c.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


def test_a_credit_note_carries_the_point_of_sale_of_the_voucher_it_cancels(
    credit_note_c: VoucherRequest,
) -> None:
    request = build_authorize_request(
        ticket=TICKET, cuit=CUIT, voucher=credit_note_c, voucher_number=VOUCHER_NUMBER
    )

    expected = (FIXTURES / "authorize_request_credit_note_c.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


def test_a_credit_note_c_request_matches_the_one_homologation_authorized(
    credit_note_c: VoucherRequest,
) -> None:
    (associated,) = credit_note_c.associated_vouchers
    cancelled = replace(associated, point_of_sale=1, number=1, voucher_date=date(2026, 10, 12))
    request = build_authorize_request(
        ticket=RECORDED_TICKET,
        cuit=RECORDED_CUIT,
        voucher=replace(credit_note_c, associated_vouchers=(cancelled,)),
        voucher_number=RECORDED_VOUCHER_NUMBER,
    )

    expected = (FIXTURES / "authorize_request_credit_note_c_recorded.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


def test_an_associated_voucher_without_cuit_or_date_is_sent_without_them(
    credit_note_c: VoucherRequest,
) -> None:
    (associated,) = credit_note_c.associated_vouchers
    bare = replace(associated, cuit=None, voucher_date=None)

    request = build_authorize_request(
        ticket=TICKET,
        cuit=CUIT,
        voucher=replace(credit_note_c, associated_vouchers=(bare,)),
        voucher_number=VOUCHER_NUMBER,
    )

    (element,) = etree.fromstring(request).iter("{http://ar.gov.afip.dif.FEV1/}CbteAsoc")
    assert [etree.QName(child).localname for child in element] == ["Tipo", "PtoVta", "Nro"]


def test_a_service_in_foreign_currency_states_its_period_rate_and_settlement(
    invoice_b: VoucherRequest,
) -> None:
    service = replace(
        invoice_b,
        concept=Concept.SERVICES,
        currency="DOL",
        exchange_rate=Decimal("1050.123456"),
        settles_in_foreign_currency=False,
        service_period=ServicePeriod(
            service_from=date(2026, 10, 1),
            service_to=date(2026, 10, 31),
            payment_due=date(2026, 11, 10),
        ),
    )

    request = build_authorize_request(
        ticket=TICKET, cuit=CUIT, voucher=service, voucher_number=VOUCHER_NUMBER
    )

    expected = (FIXTURES / "authorize_request_service_foreign_currency.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


def test_a_settlement_in_the_foreign_currency_is_sent_as_s(invoice_b: VoucherRequest) -> None:
    foreign = replace(
        invoice_b,
        currency="DOL",
        exchange_rate=Decimal("1050.50"),
        settles_in_foreign_currency=True,
    )

    request = build_authorize_request(
        ticket=TICKET, cuit=CUIT, voucher=foreign, voucher_number=VOUCHER_NUMBER
    )

    assert b"<ar:MonCotiz>1050.50</ar:MonCotiz><ar:CanMisMonExt>S</ar:CanMisMonExt>" in request


def test_a_tribute_without_a_description_is_sent_without_one(invoice_a: VoucherRequest) -> None:
    (tribute,) = invoice_a.tributes
    described = replace(tribute, tribute_type=TributeType.GROSS_INCOME, description=None)

    request = build_authorize_request(
        ticket=TICKET,
        cuit=CUIT,
        voucher=replace(invoice_a, tributes=(described,)),
        voucher_number=VOUCHER_NUMBER,
    )

    assert b"<ar:Desc>" not in request
    assert b"<ar:Id>5</ar:Id><ar:BaseImp>150.00</ar:BaseImp><ar:Alic>5.20" in request


def test_optionals_follow_the_vat_aliquots_in_the_order_the_caller_gave_them(
    invoice_b: VoucherRequest,
) -> None:
    optionals = (
        VoucherOptional(optional_id=OptionalId.COMMERCIAL_REFERENCE, value="OC-1"),
        VoucherOptional(optional_id=OptionalId.COMMERCIAL_REFERENCE, value="OC-2"),
    )

    request = build_authorize_request(
        ticket=TICKET,
        cuit=CUIT,
        voucher=replace(invoice_b, optionals=optionals),
        voucher_number=VOUCHER_NUMBER,
    )

    assert (
        b"</ar:Iva><ar:Opcionales>"
        b"<ar:Opcional><ar:Id>23</ar:Id><ar:Valor>OC-1</ar:Valor></ar:Opcional>"
        b"<ar:Opcional><ar:Id>23</ar:Id><ar:Valor>OC-2</ar:Valor></ar:Opcional>"
        b"</ar:Opcionales></ar:FECAEDetRequest>"
    ) in request


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
    assert authorization.voucher_number == RECORDED_VOUCHER_NUMBER
    assert authorization.cae == RECORDED_CAE
    assert authorization.cae_due_date == date(2026, 10, 22)
    assert authorization.observations == ()
    assert authorization.errors == ()
    assert authorization.events == ()


def test_the_approved_response_to_a_credit_note_yields_its_cae() -> None:
    authorization = parse_authorize_response(_fixture("authorize_response_credit_note_c.xml"))

    assert authorization.result == AuthorizationResult.APPROVED
    assert authorization.voucher_number == RECORDED_VOUCHER_NUMBER
    assert authorization.cae == "86410988055852"


def test_a_recorded_consult_response_yields_the_invoice_a_note_cancels() -> None:
    voucher = parse_consult_response(_fixture("consult_response_invoice_c.xml")).voucher

    assert voucher is not None
    assert voucher.voucher_number == RECORDED_VOUCHER_NUMBER
    assert voucher.voucher_date == date(2026, 10, 12)
    assert voucher.total == Decimal(100)
    assert voucher.cae == RECORDED_CAE


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
        (b"<CAE>86410988009458</CAE>", b"<CAE></CAE>", ResponseDefect.MISSING_ELEMENT, "CAE"),
        (
            b"<CAEFchVto>20261022</CAEFchVto>",
            b"<CAEFchVto>2026-10-22</CAEFchVto>",
            ResponseDefect.INVALID_DATE,
            "CAEFchVto",
        ),
        (
            b"<CbteDesde>1</CbteDesde>",
            b"<CbteDesde>seven</CbteDesde>",
            ResponseDefect.INVALID_NUMBER,
            "CbteDesde",
        ),
        (
            b"<Resultado>A</Resultado><CAE>",
            b"<Resultado>X</Resultado><CAE>",
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
                b"<Resultado>A</Resultado><CAE>", b"<CAE>"
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


POINT_OF_SALE = 1


def test_a_last_authorized_request_matches_the_recorded_one() -> None:
    request = build_last_authorized_request(
        ticket=TICKET, cuit=CUIT, point_of_sale=POINT_OF_SALE, voucher_type=VoucherType.INVOICE_B
    )

    expected = (FIXTURES / "last_authorized_request.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


def test_a_consult_request_matches_the_recorded_one() -> None:
    request = build_consult_request(
        ticket=TICKET,
        cuit=CUIT,
        point_of_sale=POINT_OF_SALE,
        voucher_type=VoucherType.INVOICE_B,
        voucher_number=VOUCHER_NUMBER,
    )

    expected = (FIXTURES / "consult_request.xml").read_bytes()
    assert _canonical(request) == _canonical(expected)


def test_consulting_a_voucher_number_outside_arcas_range_is_rejected() -> None:
    with pytest.raises(InvalidVoucherError) as error:
        build_consult_request(
            ticket=TICKET,
            cuit=CUIT,
            point_of_sale=POINT_OF_SALE,
            voucher_type=VoucherType.INVOICE_B,
            voucher_number=0,
        )

    assert error.value.defect == VoucherDefect.VOUCHER_NUMBER_OUT_OF_RANGE


def test_the_last_authorized_number_is_read_from_the_response() -> None:
    last = parse_last_authorized_response(_fixture("last_authorized_response.xml"))

    assert last.voucher_number == VOUCHER_NUMBER - 1
    assert last.errors == ()


def test_the_errors_of_a_last_authorized_response_are_reported() -> None:
    last = parse_last_authorized_response(_fixture("last_authorized_response_errors.xml"))

    assert [message.code for message in last.errors] == [600]


def test_an_authorized_voucher_is_read_from_a_consult_response() -> None:
    consultation = parse_consult_response(_fixture("consult_response.xml"))

    voucher = consultation.voucher
    assert voucher is not None
    assert voucher.result == AuthorizationResult.APPROVED
    assert voucher.voucher_number == VOUCHER_NUMBER
    assert voucher.voucher_date == date(2026, 10, 12)
    assert voucher.document_type == DocumentType.FINAL_CONSUMER
    assert voucher.document_number == 0
    assert voucher.total == Decimal(121)
    assert voucher.cae == "76412345678901"
    assert voucher.cae_due_date == date(2026, 10, 22)
    assert consultation.errors == ()


def test_a_voucher_that_does_not_exist_is_reported_through_its_errors() -> None:
    consultation = parse_consult_response(_fixture("consult_response_not_found.xml"))

    assert consultation.voucher is None
    assert [message.code for message in consultation.errors] == [602]


def test_a_consult_response_with_an_unreadable_total_is_malformed() -> None:
    response = _fixture("consult_response.xml").replace(b"<ImpTotal>121", b"<ImpTotal>many")

    with pytest.raises(MalformedResponseError) as error:
        parse_consult_response(response)

    assert error.value.defect == ResponseDefect.INVALID_NUMBER
    assert error.value.element == "ImpTotal"


def test_a_consult_response_with_neither_a_voucher_nor_errors_is_malformed() -> None:
    response = (
        _fixture("consult_response_not_found.xml")
        .replace(b"<Errors>", b"<Nothing>")
        .replace(b"</Errors>", b"</Nothing>")
    )

    with pytest.raises(MalformedResponseError) as error:
        parse_consult_response(response)

    assert error.value.element == "ResultGet"


@pytest.mark.parametrize(
    "parse", [parse_last_authorized_response, parse_consult_response], ids=["last", "consult"]
)
def test_a_soap_fault_is_raised_by_every_parser(parse: Callable[[bytes], object]) -> None:
    with pytest.raises(SoapFaultError):
        parse(_fixture("fault.xml"))


def test_a_last_authorized_response_missing_the_number_is_malformed() -> None:
    response = _fixture("last_authorized_response.xml").replace(b"CbteNro", b"Other")

    with pytest.raises(MalformedResponseError) as error:
        parse_last_authorized_response(response)

    assert error.value.element == "CbteNro"
