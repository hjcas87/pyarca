from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from lxml import etree

from pyarca.core.soap import MalformedResponseError, ResponseDefect, SoapFaultError
from pyarca.core.voucher import VoucherClass
from pyarca.core.wsaa import AccessTicket
from pyarca.core.wsfe_parameters import (
    ExchangeRate,
    PointOfSale,
    ReceiverVatConditionItem,
    ReferenceItem,
    ReferenceList,
    ServerStatus,
    build_exchange_rate_request,
    build_ping_request,
    build_points_of_sale_request,
    build_receiver_vat_conditions_request,
    build_reference_list_request,
    parse_exchange_rate_response,
    parse_ping_response,
    parse_points_of_sale_response,
    parse_receiver_vat_conditions_response,
    parse_reference_list_response,
)
from pyarca.core.wsfe_xml import ArcaMessage

CUIT = 20111111112
TICKET = AccessTicket(token="TOKEN", sign="SIGN", expires_at=datetime(2026, 10, 13, tzinfo=UTC))
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
WSFE = "http://ar.gov.afip.dif.FEV1/"
AUTH = (
    f"<ar:Auth><ar:Token>TOKEN</ar:Token><ar:Sign>SIGN</ar:Sign><ar:Cuit>{CUIT}</ar:Cuit></ar:Auth>"
)


def _canonical(document: bytes | str) -> bytes:
    data = document.encode() if isinstance(document, str) else document
    parser = etree.XMLParser(remove_blank_text=True)
    return etree.tostring(etree.fromstring(data, parser=parser), method="c14n")


def _request(operation: str, inner: str = "") -> bytes:
    return _canonical(
        f'<soapenv:Envelope xmlns:soapenv="{SOAP}" xmlns:ar="{WSFE}"><soapenv:Body>'
        f"<ar:{operation}>{inner}</ar:{operation}></soapenv:Body></soapenv:Envelope>"
    )


def _response(operation: str, result: str) -> bytes:
    return (
        f'<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>'
        f'<{operation}Response xmlns="{WSFE}"><{operation}Result>{result}</{operation}Result>'
        f"</{operation}Response></soap:Body></soap:Envelope>"
    ).encode()


def test_a_ping_request_carries_no_credentials() -> None:
    assert _canonical(build_ping_request()) == _request("FEDummy")


def test_a_reference_list_request_asks_with_the_credentials_alone() -> None:
    request = build_reference_list_request(ReferenceList.VOUCHER_TYPES, ticket=TICKET, cuit=CUIT)

    assert _canonical(request) == _request("FEParamGetTiposCbte", AUTH)


def test_a_points_of_sale_request_asks_with_the_credentials_alone() -> None:
    request = build_points_of_sale_request(ticket=TICKET, cuit=CUIT)

    assert _canonical(request) == _request("FEParamGetPtosVenta", AUTH)


@pytest.mark.parametrize(
    ("voucher_class", "inner"),
    [
        (None, AUTH),
        (VoucherClass.B, f"{AUTH}<ar:ClaseCmp>B</ar:ClaseCmp>"),
    ],
)
def test_a_receiver_conditions_request_may_ask_for_one_voucher_class(
    voucher_class: VoucherClass | None, inner: str
) -> None:
    request = build_receiver_vat_conditions_request(
        ticket=TICKET, cuit=CUIT, voucher_class=voucher_class
    )

    assert _canonical(request) == _request("FEParamGetCondicionIvaReceptor", inner)


@pytest.mark.parametrize(
    ("on", "inner"),
    [
        (None, f"{AUTH}<ar:MonId>DOL</ar:MonId>"),
        (date(2026, 10, 9), f"{AUTH}<ar:MonId>DOL</ar:MonId><ar:FchCotiz>20261009</ar:FchCotiz>"),
    ],
)
def test_an_exchange_rate_request_may_ask_for_a_date(on: date | None, inner: str) -> None:
    request = build_exchange_rate_request(ticket=TICKET, cuit=CUIT, currency="DOL", on=on)

    assert _canonical(request) == _request("FEParamGetCotizacion", inner)


def test_a_ping_answer_names_the_state_of_each_server() -> None:
    answer = _response(
        "FEDummy",
        "<AppServer>OK</AppServer><DbServer>OK</DbServer><AuthServer>DOWN</AuthServer>",
    )

    status = parse_ping_response(answer)

    assert status == ServerStatus(application="OK", database="OK", authentication="DOWN")
    assert not status.is_operational


def test_a_ping_answer_with_every_server_up_is_operational() -> None:
    answer = _response(
        "FEDummy",
        "<AppServer>OK</AppServer><DbServer>OK</DbServer><AuthServer>OK</AuthServer>",
    )

    assert parse_ping_response(answer).is_operational


VOUCHER_TYPES_RESULT = (
    "<ResultGet>"
    "<CbteTipo><Id>1</Id><Desc>Factura A</Desc><FchDesde>20100917</FchDesde>"
    "<FchHasta>NULL</FchHasta></CbteTipo>"
    "<CbteTipo><Id>4</Id><Desc>Recibos A</Desc><FchDesde>20100917</FchDesde>"
    "<FchHasta>20260101</FchHasta></CbteTipo>"
    "</ResultGet>"
)


def test_a_reference_list_reads_each_item_with_its_validity() -> None:
    answer = _response("FEParamGetTiposCbte", VOUCHER_TYPES_RESULT)

    result = parse_reference_list_response(answer, ReferenceList.VOUCHER_TYPES)

    assert result.items == (
        ReferenceItem(
            identifier="1", description="Factura A", valid_from=date(2010, 9, 17), valid_until=None
        ),
        ReferenceItem(
            identifier="4",
            description="Recibos A",
            valid_from=date(2010, 9, 17),
            valid_until=date(2026, 1, 1),
        ),
    )
    assert result.errors == ()


@pytest.mark.parametrize(
    ("table", "operation", "item"),
    [
        (ReferenceList.DOCUMENT_TYPES, "FEParamGetTiposDoc", "DocTipo"),
        (ReferenceList.VAT_RATES, "FEParamGetTiposIva", "IvaTipo"),
        (ReferenceList.CURRENCIES, "FEParamGetTiposMonedas", "Moneda"),
        (ReferenceList.OPTIONAL_TYPES, "FEParamGetTiposOpcional", "OpcionalTipo"),
        (ReferenceList.TRIBUTE_TYPES, "FEParamGetTiposTributos", "TributoTipo"),
    ],
)
def test_every_reference_list_is_read_from_its_own_elements(
    table: ReferenceList, operation: str, item: str
) -> None:
    answer = _response(
        operation,
        f"<ResultGet><{item}><Id>PES</Id><Desc>Pesos</Desc><FchDesde>20100917</FchDesde>"
        f"<FchHasta>NULL</FchHasta></{item}></ResultGet>",
    )

    assert parse_reference_list_response(answer, table).items == (
        ReferenceItem(
            identifier="PES",
            description="Pesos",
            valid_from=date(2010, 9, 17),
            valid_until=None,
        ),
    )
    request = build_reference_list_request(table, ticket=TICKET, cuit=CUIT)
    assert _canonical(request) == _request(operation, AUTH)


def test_a_reference_list_answered_with_errors_returns_them_without_items() -> None:
    answer = _response(
        "FEParamGetTiposCbte",
        "<Errors><Err><Code>600</Code><Msg>Ticket not valid</Msg></Err></Errors>",
    )

    result = parse_reference_list_response(answer, ReferenceList.VOUCHER_TYPES)

    assert result.items == ()
    assert result.errors == (ArcaMessage(code=600, message="Ticket not valid"),)


def test_a_reference_list_with_neither_items_nor_errors_is_malformed() -> None:
    with pytest.raises(MalformedResponseError) as error:
        parse_reference_list_response(
            _response("FEParamGetTiposCbte", ""), ReferenceList.VOUCHER_TYPES
        )

    assert error.value.defect == ResponseDefect.MISSING_ELEMENT
    assert error.value.element == "ResultGet"


def test_a_reference_list_with_an_empty_result_has_no_items() -> None:
    answer = _response("FEParamGetTiposCbte", "<ResultGet/>")

    assert parse_reference_list_response(answer, ReferenceList.VOUCHER_TYPES).items == ()


def test_a_reference_item_with_an_invalid_date_is_malformed() -> None:
    answer = _response(
        "FEParamGetTiposCbte",
        "<ResultGet><CbteTipo><Id>1</Id><Desc>Factura A</Desc><FchDesde>soon</FchDesde>"
        "</CbteTipo></ResultGet>",
    )

    with pytest.raises(MalformedResponseError) as error:
        parse_reference_list_response(answer, ReferenceList.VOUCHER_TYPES)

    assert error.value.defect == ResponseDefect.INVALID_DATE


def test_a_reference_item_without_a_validity_end_is_open_ended() -> None:
    answer = _response(
        "FEParamGetTiposCbte",
        "<ResultGet><CbteTipo><Id>1</Id><Desc>Factura A</Desc><FchDesde>20100917</FchDesde>"
        "</CbteTipo></ResultGet>",
    )

    (item,) = parse_reference_list_response(answer, ReferenceList.VOUCHER_TYPES).items

    assert item.valid_until is None


def test_a_soap_fault_is_raised_instead_of_read_as_a_list() -> None:
    fault = (
        f'<soap:Envelope xmlns:soap="{SOAP}"><soap:Body><soap:Fault>'
        "<faultcode>soap:Server</faultcode><faultstring>boom</faultstring>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    ).encode()

    with pytest.raises(SoapFaultError):
        parse_reference_list_response(fault, ReferenceList.VOUCHER_TYPES)


def test_receiver_conditions_come_with_the_voucher_class_they_apply_to() -> None:
    answer = _response(
        "FEParamGetCondicionIvaReceptor",
        "<ResultGet>"
        "<CondicionIvaReceptor><Id>1</Id><Desc>IVA Responsable Inscripto</Desc>"
        "<Cmp_Clase>A</Cmp_Clase></CondicionIvaReceptor>"
        "<CondicionIvaReceptor><Id>5</Id><Desc>Consumidor Final</Desc>"
        "<Cmp_Clase>B</Cmp_Clase></CondicionIvaReceptor>"
        "</ResultGet>",
    )

    result = parse_receiver_vat_conditions_response(answer)

    assert result.items == (
        ReceiverVatConditionItem(
            identifier=1, description="IVA Responsable Inscripto", voucher_class="A"
        ),
        ReceiverVatConditionItem(identifier=5, description="Consumidor Final", voucher_class="B"),
    )


POINTS_OF_SALE_RESULT = (
    "<ResultGet>"
    "<PtoVenta><Nro>1</Nro><EmisionTipo>CAE</EmisionTipo><Bloqueado>N</Bloqueado>"
    "<FchBaja>NULL</FchBaja></PtoVenta>"
    "<PtoVenta><Nro>2</Nro><EmisionTipo>CAE</EmisionTipo><Bloqueado>S</Bloqueado>"
    "<FchBaja>20260301</FchBaja></PtoVenta>"
    "</ResultGet>"
)


def test_points_of_sale_say_whether_they_are_blocked_or_closed() -> None:
    result = parse_points_of_sale_response(_response("FEParamGetPtosVenta", POINTS_OF_SALE_RESULT))

    assert result.items == (
        PointOfSale(number=1, emission_type="CAE", is_blocked=False, closed_on=None),
        PointOfSale(number=2, emission_type="CAE", is_blocked=True, closed_on=date(2026, 3, 1)),
    )


def test_a_point_of_sale_with_an_unknown_blocked_mark_is_malformed() -> None:
    answer = _response(
        "FEParamGetPtosVenta",
        "<ResultGet><PtoVenta><Nro>1</Nro><EmisionTipo>CAE</EmisionTipo>"
        "<Bloqueado>maybe</Bloqueado></PtoVenta></ResultGet>",
    )

    with pytest.raises(MalformedResponseError) as error:
        parse_points_of_sale_response(answer)

    assert error.value.defect == ResponseDefect.INVALID_VALUE
    assert error.value.element == "Bloqueado"


def test_no_points_of_sale_arrive_as_the_no_data_error() -> None:
    answer = _response(
        "FEParamGetPtosVenta",
        "<Errors><Err><Code>602</Code><Msg>No data</Msg></Err></Errors>",
    )

    result = parse_points_of_sale_response(answer)

    assert result.items == ()
    assert [message.code for message in result.errors] == [602]


def test_an_exchange_rate_is_read_as_a_decimal_with_its_date() -> None:
    answer = _response(
        "FEParamGetCotizacion",
        "<ResultGet><MonId>DOL</MonId><MonCotiz>1050.500000</MonCotiz>"
        "<FchCotiz>20261009</FchCotiz></ResultGet>",
    )

    result = parse_exchange_rate_response(answer)

    assert result.items == (
        ExchangeRate(currency="DOL", rate=Decimal("1050.5"), quoted_on=date(2026, 10, 9)),
    )


def test_an_exchange_rate_without_a_date_is_read_without_one() -> None:
    answer = _response(
        "FEParamGetCotizacion",
        "<ResultGet><MonId>DOL</MonId><MonCotiz>1050.5</MonCotiz></ResultGet>",
    )

    (rate,) = parse_exchange_rate_response(answer).items

    assert rate.quoted_on is None
