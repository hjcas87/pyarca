from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from pyarca.core.voucher import VoucherClass
from pyarca.core.wsaa import AccessTicket, Service
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
)
from pyarca.shell.endpoints import WSFE_ENDPOINTS, Environment
from pyarca.shell.wsfe_client import ArcaErrorsError, WsfeClient

CUIT = 20111111112
TICKET = AccessTicket(token="TOKEN", sign="SIGN", expires_at=datetime(2026, 10, 13, tzinfo=UTC))
URL = WSFE_ENDPOINTS[Environment.HOMOLOGATION]
ACTION_PREFIX = "http://ar.gov.afip.dif.FEV1/"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
WSFE = "http://ar.gov.afip.dif.FEV1/"


def _answer(operation: str, result: str) -> bytes:
    return (
        f'<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>'
        f'<{operation}Response xmlns="{WSFE}"><{operation}Result>{result}</{operation}Result>'
        f"</{operation}Response></soap:Body></soap:Envelope>"
    ).encode()


def _list_answer(operation: str, item: str) -> bytes:
    return _answer(
        operation,
        f"<ResultGet><{item}><Id>X</Id><Desc>Item</Desc><FchDesde>20100917</FchDesde>"
        f"<FchHasta>NULL</FchHasta></{item}></ResultGet>",
    )


@dataclass
class FakeTicketProvider:
    requested: list[Service] = field(default_factory=list)

    def get_access_ticket(self, service: Service) -> AccessTicket:
        self.requested.append(service)
        return TICKET


@dataclass
class FakeTransport:
    answer: bytes
    posts: list[tuple[str, bytes, str]] = field(default_factory=list)

    def post(self, *, url: str, body: bytes, soap_action: str) -> bytes:
        self.posts.append((url, body, soap_action))
        return self.answer


def _client(transport: FakeTransport, provider: FakeTicketProvider | None = None) -> WsfeClient:
    return WsfeClient(
        ticket_provider=provider or FakeTicketProvider(),
        transport=transport,
        environment=Environment.HOMOLOGATION,
        cuit=CUIT,
    )


def test_ping_asks_wsfe_without_logging_in() -> None:
    provider = FakeTicketProvider()
    transport = FakeTransport(
        _answer(
            "FEDummy", "<AppServer>OK</AppServer><DbServer>OK</DbServer><AuthServer>OK</AuthServer>"
        )
    )

    status = _client(transport, provider).ping()

    assert status == ServerStatus(application="OK", database="OK", authentication="OK")
    assert provider.requested == []
    assert transport.posts == [(URL, build_ping_request(), f"{ACTION_PREFIX}FEDummy")]


@pytest.mark.parametrize(
    ("method", "table", "operation", "item"),
    [
        ("voucher_types", ReferenceList.VOUCHER_TYPES, "FEParamGetTiposCbte", "CbteTipo"),
        ("document_types", ReferenceList.DOCUMENT_TYPES, "FEParamGetTiposDoc", "DocTipo"),
        ("vat_rates", ReferenceList.VAT_RATES, "FEParamGetTiposIva", "IvaTipo"),
        ("currencies", ReferenceList.CURRENCIES, "FEParamGetTiposMonedas", "Moneda"),
        ("optional_types", ReferenceList.OPTIONAL_TYPES, "FEParamGetTiposOpcional", "OpcionalTipo"),
        ("tribute_types", ReferenceList.TRIBUTE_TYPES, "FEParamGetTiposTributos", "TributoTipo"),
    ],
)
def test_each_reference_list_is_asked_with_a_wsfe_ticket(
    method: str, table: ReferenceList, operation: str, item: str
) -> None:
    provider = FakeTicketProvider()
    transport = FakeTransport(_list_answer(operation, item))

    items = getattr(_client(transport, provider), method)()

    assert items == (
        ReferenceItem(
            identifier="X",
            description="Item",
            valid_from=date(2010, 9, 17),
            valid_until=None,
        ),
    )
    assert provider.requested == [Service.WSFE]
    assert transport.posts == [
        (
            URL,
            build_reference_list_request(table, ticket=TICKET, cuit=CUIT),
            f"{ACTION_PREFIX}{operation}",
        )
    ]


def test_receiver_conditions_may_be_asked_for_one_voucher_class() -> None:
    transport = FakeTransport(
        _answer(
            "FEParamGetCondicionIvaReceptor",
            "<ResultGet><CondicionIvaReceptor><Id>5</Id><Desc>Consumidor Final</Desc>"
            "<Cmp_Clase>B</Cmp_Clase></CondicionIvaReceptor></ResultGet>",
        )
    )

    conditions = _client(transport).receiver_vat_conditions(voucher_class=VoucherClass.B)

    assert conditions == (
        ReceiverVatConditionItem(identifier=5, description="Consumidor Final", voucher_class="B"),
    )
    assert transport.posts[0][1] == build_receiver_vat_conditions_request(
        ticket=TICKET, cuit=CUIT, voucher_class=VoucherClass.B
    )


def test_points_of_sale_are_listed() -> None:
    transport = FakeTransport(
        _answer(
            "FEParamGetPtosVenta",
            "<ResultGet><PtoVenta><Nro>1</Nro><EmisionTipo>CAE</EmisionTipo>"
            "<Bloqueado>N</Bloqueado></PtoVenta></ResultGet>",
        )
    )

    points = _client(transport).points_of_sale()

    assert points == (PointOfSale(number=1, emission_type="CAE", is_blocked=False, closed_on=None),)
    assert transport.posts[0][1] == build_points_of_sale_request(ticket=TICKET, cuit=CUIT)


def test_having_no_points_of_sale_is_an_empty_list_not_an_error() -> None:
    transport = FakeTransport(
        _answer(
            "FEParamGetPtosVenta", "<Errors><Err><Code>602</Code><Msg>No data</Msg></Err></Errors>"
        )
    )

    assert _client(transport).points_of_sale() == ()


def test_an_exchange_rate_is_asked_for_a_currency_and_a_date() -> None:
    transport = FakeTransport(
        _answer(
            "FEParamGetCotizacion",
            "<ResultGet><MonId>DOL</MonId><MonCotiz>1050.5</MonCotiz>"
            "<FchCotiz>20261009</FchCotiz></ResultGet>",
        )
    )

    rate = _client(transport).exchange_rate(currency="DOL", on=date(2026, 10, 9))

    assert rate == ExchangeRate(currency="DOL", rate=Decimal("1050.5"), quoted_on=date(2026, 10, 9))
    assert transport.posts[0][1] == build_exchange_rate_request(
        ticket=TICKET, cuit=CUIT, currency="DOL", on=date(2026, 10, 9)
    )


def test_an_exchange_rate_without_a_date_asks_for_the_latest() -> None:
    transport = FakeTransport(
        _answer(
            "FEParamGetCotizacion",
            "<ResultGet><MonId>DOL</MonId><MonCotiz>1050.5</MonCotiz></ResultGet>",
        )
    )

    _client(transport).exchange_rate(currency="DOL")

    assert transport.posts[0][1] == build_exchange_rate_request(
        ticket=TICKET, cuit=CUIT, currency="DOL", on=None
    )


CALLS: list[tuple[str, Callable[[WsfeClient], object]]] = [
    ("FEParamGetTiposCbte", lambda client: client.voucher_types()),
    ("FEParamGetPtosVenta", lambda client: client.points_of_sale()),
    ("FEParamGetCondicionIvaReceptor", lambda client: client.receiver_vat_conditions()),
    ("FEParamGetCotizacion", lambda client: client.exchange_rate(currency="XXX")),
]


@pytest.mark.parametrize(("operation", "call"), CALLS)
def test_errors_other_than_no_data_are_raised_with_their_codes(
    operation: str, call: Callable[[WsfeClient], object]
) -> None:
    errors = "<Errors><Err><Code>12000</Code><Msg>Bad currency</Msg></Err></Errors>"
    transport = FakeTransport(_answer(operation, errors))

    with pytest.raises(ArcaErrorsError) as error:
        call(_client(transport))

    assert [message.code for message in error.value.errors] == [12000]
