"""Reference data and health checks of WSFEv1: what the library's users look up before invoicing."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from lxml import etree

from pyarca.core.soap import MalformedResponseError, ResponseDefect
from pyarca.core.voucher import VoucherClass
from pyarca.core.wsaa import AccessTicket
from pyarca.core.wsfe_xml import (
    VOUCHER_DATE_FORMAT,
    ArcaMessage,
    WsfeOperation,
    add_text,
    date_of,
    decimal,
    integer,
    messages,
    q,
    result_element,
    serialize,
    start_anonymous_request,
    start_request,
    text,
)

NO_DATE = "NULL"
HEALTHY_SERVER = "OK"
BLOCKED_MARKS = {"S": True, "N": False}


class ReferenceList(StrEnum):
    """The `FEParamGet*` lists whose items share the {Id, Desc, FchDesde, FchHasta} shape."""

    VOUCHER_TYPES = "FEParamGetTiposCbte"
    DOCUMENT_TYPES = "FEParamGetTiposDoc"
    VAT_RATES = "FEParamGetTiposIva"
    CURRENCIES = "FEParamGetTiposMonedas"
    OPTIONAL_TYPES = "FEParamGetTiposOpcional"
    TRIBUTE_TYPES = "FEParamGetTiposTributos"


REFERENCE_ITEM_TAGS: dict[ReferenceList, str] = {
    ReferenceList.VOUCHER_TYPES: "CbteTipo",
    ReferenceList.DOCUMENT_TYPES: "DocTipo",
    ReferenceList.VAT_RATES: "IvaTipo",
    ReferenceList.CURRENCIES: "Moneda",
    ReferenceList.OPTIONAL_TYPES: "OpcionalTipo",
    ReferenceList.TRIBUTE_TYPES: "TributoTipo",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerStatus:
    """ARCA's answer to `FEDummy`: the state of the servers behind WSFE."""

    application: str
    database: str
    authentication: str

    @property
    def is_operational(self) -> bool:
        """Tell whether every server reports itself up."""
        return {self.application, self.database, self.authentication} == {HEALTHY_SERVER}


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceItem:
    """One entry of a reference list; `identifier` is text because some lists use codes."""

    identifier: str
    description: str
    valid_from: date | None
    valid_until: date | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceiverVatConditionItem:
    """A receiver VAT condition and the voucher class (A, B, C, M or 49) that accepts it."""

    identifier: int
    description: str
    voucher_class: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PointOfSale:
    """A point of sale enabled for electronic invoicing."""

    number: int
    emission_type: str
    is_blocked: bool
    closed_on: date | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExchangeRate:
    """ARCA's indicative quotation of a currency."""

    currency: str
    rate: Decimal
    quoted_on: date | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ParameterResult[T]:
    """ARCA's answer to a `FEParamGet*` call: the items found, or the errors that explain none."""

    items: tuple[T, ...]
    errors: tuple[ArcaMessage, ...]
    events: tuple[ArcaMessage, ...]


def build_ping_request() -> bytes:
    """Build the SOAP request for WSFE `FEDummy`, which needs no credentials."""
    envelope, _ = start_anonymous_request(WsfeOperation.PING)
    return serialize(envelope)


def build_reference_list_request(table: ReferenceList, *, ticket: AccessTicket, cuit: int) -> bytes:
    """Build the SOAP request that asks for one of the reference lists.

    Args:
        table: The list to ask for.
        ticket: The access ticket WSAA issued for WSFE.
        cuit: The issuer's CUIT.
    """
    envelope, _ = start_request(table, ticket=ticket, cuit=cuit)
    return serialize(envelope)


def build_points_of_sale_request(*, ticket: AccessTicket, cuit: int) -> bytes:
    """Build the SOAP request for WSFE `FEParamGetPtosVenta`."""
    envelope, _ = start_request(WsfeOperation.POINTS_OF_SALE, ticket=ticket, cuit=cuit)
    return serialize(envelope)


def build_receiver_vat_conditions_request(
    *, ticket: AccessTicket, cuit: int, voucher_class: VoucherClass | None
) -> bytes:
    """Build the SOAP request for WSFE `FEParamGetCondicionIvaReceptor`.

    Args:
        ticket: The access ticket WSAA issued for WSFE.
        cuit: The issuer's CUIT.
        voucher_class: The voucher class to list the conditions of; every class when `None`.
    """
    envelope, operation = start_request(
        WsfeOperation.RECEIVER_VAT_CONDITIONS, ticket=ticket, cuit=cuit
    )
    if voucher_class is not None:
        add_text(operation, "ClaseCmp", voucher_class.value)
    return serialize(envelope)


def build_exchange_rate_request(
    *, ticket: AccessTicket, cuit: int, currency: str, on: date | None
) -> bytes:
    """Build the SOAP request for WSFE `FEParamGetCotizacion`.

    Args:
        ticket: The access ticket WSAA issued for WSFE.
        cuit: The issuer's CUIT.
        currency: The currency code, as `FEParamGetTiposMonedas` lists it.
        on: The date to quote the currency at; ARCA's latest quotation when `None`.
    """
    envelope, operation = start_request(WsfeOperation.EXCHANGE_RATE, ticket=ticket, cuit=cuit)
    add_text(operation, "MonId", currency)
    if on is not None:
        add_text(operation, "FchCotiz", on.strftime(VOUCHER_DATE_FORMAT))
    return serialize(envelope)


def parse_ping_response(response: bytes) -> ServerStatus:
    """Read ARCA's answer to `FEDummy`.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response lacks what the service documents.
    """
    result = result_element(response, "FEDummyResult")
    return ServerStatus(
        application=text(result, "AppServer"),
        database=text(result, "DbServer"),
        authentication=text(result, "AuthServer"),
    )


def parse_reference_list_response(
    response: bytes, table: ReferenceList
) -> ParameterResult[ReferenceItem]:
    """Read ARCA's answer to one of the reference lists.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response lacks what the service documents.
    """
    return _parse_items(response, table, REFERENCE_ITEM_TAGS[table], _reference_item)


def parse_receiver_vat_conditions_response(
    response: bytes,
) -> ParameterResult[ReceiverVatConditionItem]:
    """Read ARCA's answer to `FEParamGetCondicionIvaReceptor`.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response lacks what the service documents.
    """
    return _parse_items(
        response,
        WsfeOperation.RECEIVER_VAT_CONDITIONS,
        "CondicionIvaReceptor",
        _receiver_vat_condition,
    )


def parse_points_of_sale_response(response: bytes) -> ParameterResult[PointOfSale]:
    """Read ARCA's answer to `FEParamGetPtosVenta`; no points of sale arrive as error 602.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response lacks what the service documents.
    """
    return _parse_items(response, WsfeOperation.POINTS_OF_SALE, "PtoVenta", _point_of_sale)


def parse_exchange_rate_response(response: bytes) -> ParameterResult[ExchangeRate]:
    """Read ARCA's answer to `FEParamGetCotizacion`.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response lacks what the service documents.
    """
    result = result_element(response, f"{WsfeOperation.EXCHANGE_RATE}Result")
    errors = messages(result, "Errors/Err")
    events = messages(result, "Events/Evt")
    found = result.find(q("ResultGet"))
    if found is None:
        return _without_result(errors=errors, events=events)
    rate = ExchangeRate(
        currency=text(found, "MonId"),
        rate=decimal(found, "MonCotiz"),
        quoted_on=_optional_date(found, "FchCotiz"),
    )
    return ParameterResult(items=(rate,), errors=errors, events=events)


def _parse_items[T](
    response: bytes,
    operation: StrEnum,
    item_tag: str,
    build: Callable[[etree._Element], T],
) -> ParameterResult[T]:
    result = result_element(response, f"{operation}Result")
    errors = messages(result, "Errors/Err")
    events = messages(result, "Events/Evt")
    found = result.find(q("ResultGet"))
    if found is None:
        return _without_result(errors=errors, events=events)
    items = tuple(build(item) for item in found.findall(q(item_tag)))
    return ParameterResult(items=items, errors=errors, events=events)


def _without_result[T](
    *, errors: tuple[ArcaMessage, ...], events: tuple[ArcaMessage, ...]
) -> ParameterResult[T]:
    # ARCA answers with errors alone when it has nothing to list.
    if not errors:
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, "ResultGet")
    return ParameterResult(items=(), errors=errors, events=events)


def _reference_item(element: etree._Element) -> ReferenceItem:
    return ReferenceItem(
        identifier=text(element, "Id"),
        description=text(element, "Desc"),
        valid_from=_optional_date(element, "FchDesde"),
        valid_until=_optional_date(element, "FchHasta"),
    )


def _receiver_vat_condition(element: etree._Element) -> ReceiverVatConditionItem:
    return ReceiverVatConditionItem(
        identifier=integer(element, "Id"),
        description=text(element, "Desc"),
        voucher_class=text(element, "Cmp_Clase"),
    )


def _point_of_sale(element: etree._Element) -> PointOfSale:
    blocked = text(element, "Bloqueado")
    if blocked not in BLOCKED_MARKS:
        raise MalformedResponseError(ResponseDefect.INVALID_VALUE, "Bloqueado")
    return PointOfSale(
        number=integer(element, "Nro"),
        emission_type=text(element, "EmisionTipo"),
        is_blocked=BLOCKED_MARKS[blocked],
        closed_on=_optional_date(element, "FchBaja"),
    )


def _optional_date(element: etree._Element, tag: str) -> date | None:
    raw = (element.findtext(q(tag)) or "").strip()
    if raw in {"", NO_DATE}:
        return None
    return date_of(element, tag)
