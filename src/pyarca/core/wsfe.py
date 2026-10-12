"""Requests and responses of WSFEv1, ARCA's electronic invoicing service."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from lxml import etree

from pyarca.core.amounts import format_amount
from pyarca.core.soap import MalformedResponseError, ResponseDefect
from pyarca.core.voucher import (
    MAX_VOUCHER_NUMBER,
    InvalidVoucherError,
    VoucherDefect,
    VoucherRequest,
)
from pyarca.core.wsaa import AccessTicket
from pyarca.core.wsfe_codes import VoucherType
from pyarca.core.wsfe_xml import (
    VOUCHER_DATE_FORMAT,
    ArcaMessage,
    WsfeOperation,
    add_text,
    date_of,
    decimal,
    integer,
    messages,
    name,
    q,
    result_element,
    serialize,
    start_request,
    text,
)

SINGLE_VOUCHER_COUNT = 1
FOREIGN_SETTLEMENT_CODES = {True: "S", False: "N"}


def build_authorize_request(
    *, ticket: AccessTicket, cuit: int, voucher: VoucherRequest, voucher_number: int
) -> bytes:
    """Build the SOAP request for WSFE `FECAESolicitar`, asking to authorize one voucher.

    Args:
        ticket: The access ticket WSAA issued for WSFE.
        cuit: The issuer's CUIT.
        voucher: The voucher to authorize.
        voucher_number: The number to authorize it under; ARCA only takes the last one plus one.

    Returns:
        The SOAP envelope as UTF-8 XML bytes.

    Raises:
        InvalidVoucherError: If `voucher_number` is outside the range ARCA accepts.
    """
    _check_voucher_number(voucher_number)
    envelope, operation = start_request(WsfeOperation.AUTHORIZE, ticket=ticket, cuit=cuit)
    request = etree.SubElement(operation, name("FeCAEReq"))
    header = etree.SubElement(request, name("FeCabReq"))
    add_text(header, "CantReg", SINGLE_VOUCHER_COUNT)
    add_text(header, "PtoVta", voucher.point_of_sale)
    add_text(header, "CbteTipo", voucher.voucher_type.value)
    details = etree.SubElement(request, name("FeDetReq"))
    _add_detail(details, voucher=voucher, voucher_number=voucher_number)
    return serialize(envelope)


def build_last_authorized_request(
    *, ticket: AccessTicket, cuit: int, point_of_sale: int, voucher_type: VoucherType
) -> bytes:
    """Build the SOAP request for WSFE `FECompUltimoAutorizado`.

    Args:
        ticket: The access ticket WSAA issued for WSFE.
        cuit: The issuer's CUIT.
        point_of_sale: The point of sale to ask about.
        voucher_type: The voucher type to ask about.

    Returns:
        The SOAP envelope as UTF-8 XML bytes.
    """
    envelope, operation = start_request(WsfeOperation.LAST_AUTHORIZED, ticket=ticket, cuit=cuit)
    add_text(operation, "PtoVta", point_of_sale)
    add_text(operation, "CbteTipo", voucher_type.value)
    return serialize(envelope)


def build_consult_request(
    *,
    ticket: AccessTicket,
    cuit: int,
    point_of_sale: int,
    voucher_type: VoucherType,
    voucher_number: int,
) -> bytes:
    """Build the SOAP request for WSFE `FECompConsultar`, asking for one issued voucher.

    Args:
        ticket: The access ticket WSAA issued for WSFE.
        cuit: The issuer's CUIT.
        point_of_sale: The point of sale the voucher was issued from.
        voucher_type: The voucher type.
        voucher_number: The voucher number.

    Returns:
        The SOAP envelope as UTF-8 XML bytes.

    Raises:
        InvalidVoucherError: If `voucher_number` is outside the range ARCA accepts.
    """
    _check_voucher_number(voucher_number)
    envelope, operation = start_request(WsfeOperation.CONSULT, ticket=ticket, cuit=cuit)
    query = etree.SubElement(operation, name("FeCompConsReq"))
    add_text(query, "CbteTipo", voucher_type.value)
    add_text(query, "CbteNro", voucher_number)
    add_text(query, "PtoVta", point_of_sale)
    return serialize(envelope)


def _check_voucher_number(voucher_number: int) -> None:
    if not 1 <= voucher_number <= MAX_VOUCHER_NUMBER:
        raise InvalidVoucherError(VoucherDefect.VOUCHER_NUMBER_OUT_OF_RANGE)


# The service is an ASMX one: it rejects elements out of the order its WSDL declares.
def _add_detail(parent: etree._Element, *, voucher: VoucherRequest, voucher_number: int) -> None:
    detail = etree.SubElement(parent, name("FECAEDetRequest"))
    add_text(detail, "Concepto", voucher.concept.value)
    add_text(detail, "DocTipo", voucher.document_type.value)
    add_text(detail, "DocNro", voucher.document_number)
    add_text(detail, "CbteDesde", voucher_number)
    add_text(detail, "CbteHasta", voucher_number)
    add_text(detail, "CbteFch", voucher.voucher_date.strftime(VOUCHER_DATE_FORMAT))
    add_text(detail, "ImpTotal", format_amount(voucher.total))
    add_text(detail, "ImpTotConc", format_amount(voucher.non_taxed))
    add_text(detail, "ImpNeto", format_amount(voucher.net))
    add_text(detail, "ImpOpEx", format_amount(voucher.exempt))
    add_text(detail, "ImpTrib", format_amount(voucher.tributes_total))
    add_text(detail, "ImpIVA", format_amount(voucher.vat_total))
    _add_service_period(detail, voucher)
    _add_payment_due(detail, voucher)
    add_text(detail, "MonId", voucher.currency)
    add_text(detail, "MonCotiz", format(voucher.exchange_rate, "f"))
    if voucher.settles_in_foreign_currency is not None:
        add_text(
            detail, "CanMisMonExt", FOREIGN_SETTLEMENT_CODES[voucher.settles_in_foreign_currency]
        )
    add_text(detail, "CondicionIVAReceptorId", voucher.receiver_vat_condition.value)
    if voucher.associated_vouchers:
        _add_associated_vouchers(detail, voucher)
    if voucher.tributes:
        _add_tributes(detail, voucher)
    if voucher.vat_lines:
        _add_vat(detail, voucher)
    if voucher.optionals:
        _add_optionals(detail, voucher)


def _add_service_period(parent: etree._Element, voucher: VoucherRequest) -> None:
    period = voucher.service_period
    if period is None:
        return
    add_text(parent, "FchServDesde", period.service_from.strftime(VOUCHER_DATE_FORMAT))
    add_text(parent, "FchServHasta", period.service_to.strftime(VOUCHER_DATE_FORMAT))


def _add_payment_due(parent: etree._Element, voucher: VoucherRequest) -> None:
    if voucher.payment_due is None:
        return
    add_text(parent, "FchVtoPago", voucher.payment_due.strftime(VOUCHER_DATE_FORMAT))


def _add_associated_vouchers(parent: etree._Element, voucher: VoucherRequest) -> None:
    associated = etree.SubElement(parent, name("CbtesAsoc"))
    for item in voucher.associated_vouchers:
        element = etree.SubElement(associated, name("CbteAsoc"))
        add_text(element, "Tipo", item.voucher_type.value)
        add_text(element, "PtoVta", item.point_of_sale)
        add_text(element, "Nro", item.number)
        if item.cuit is not None:
            add_text(element, "Cuit", item.cuit)
        if item.voucher_date is not None:
            add_text(element, "CbteFch", item.voucher_date.strftime(VOUCHER_DATE_FORMAT))


def _add_tributes(parent: etree._Element, voucher: VoucherRequest) -> None:
    tributes = etree.SubElement(parent, name("Tributos"))
    for tribute in voucher.tributes:
        element = etree.SubElement(tributes, name("Tributo"))
        add_text(element, "Id", tribute.tribute_type.value)
        if tribute.description:
            add_text(element, "Desc", tribute.description)
        add_text(element, "BaseImp", format_amount(tribute.base))
        add_text(element, "Alic", format_amount(tribute.rate))
        add_text(element, "Importe", format_amount(tribute.amount))


def _add_vat(parent: etree._Element, voucher: VoucherRequest) -> None:
    vat = etree.SubElement(parent, name("Iva"))
    for line in voucher.vat_lines:
        aliquot = etree.SubElement(vat, name("AlicIva"))
        add_text(aliquot, "Id", line.rate.value)
        add_text(aliquot, "BaseImp", format_amount(line.base))
        add_text(aliquot, "Importe", format_amount(line.amount))


def _add_optionals(parent: etree._Element, voucher: VoucherRequest) -> None:
    optionals = etree.SubElement(parent, name("Opcionales"))
    for optional in voucher.optionals:
        element = etree.SubElement(optionals, name("Opcional"))
        add_text(element, "Id", optional.optional_id.value)
        add_text(element, "Valor", optional.value)


class AuthorizationResult(StrEnum):
    """`Resultado`: whether ARCA authorized the voucher; the CAE alone does not say so."""

    APPROVED = "A"
    REJECTED = "R"
    PARTIAL = "P"


@dataclass(frozen=True, slots=True, kw_only=True)
class VoucherAuthorization:
    """ARCA's answer to `FECAESolicitar` for one voucher."""

    result: AuthorizationResult
    voucher_number: int | None
    cae: str | None
    cae_due_date: date | None
    observations: tuple[ArcaMessage, ...]
    errors: tuple[ArcaMessage, ...]
    events: tuple[ArcaMessage, ...]


def parse_authorize_response(response: bytes) -> VoucherAuthorization:
    """Read ARCA's answer to `FECAESolicitar`.

    Args:
        response: The SOAP response body as returned by WSFE.

    Returns:
        The authorization. A voucher is authorized only when `result` is `APPROVED`.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response lacks what the service documents.
    """
    result = result_element(response, "FECAESolicitarResult")
    errors = messages(result, "Errors/Err")
    events = messages(result, "Events/Evt")
    detail = result.find(q("FeDetResp/FECAEDetResponse"))
    if detail is None:
        return _rejection_without_detail(errors=errors, events=events)

    outcome = _authorization_result(text(detail, "Resultado"))
    cae = (detail.findtext(q("CAE")) or "").strip() or None
    if outcome == AuthorizationResult.APPROVED and cae is None:
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, "CAE")
    return VoucherAuthorization(
        result=outcome,
        voucher_number=integer(detail, "CbteDesde"),
        cae=cae,
        cae_due_date=None if cae is None else date_of(detail, "CAEFchVto"),
        observations=messages(detail, "Observaciones/Obs"),
        errors=errors,
        events=events,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class LastAuthorized:
    """ARCA's answer to `FECompUltimoAutorizado`."""

    voucher_number: int
    errors: tuple[ArcaMessage, ...]
    events: tuple[ArcaMessage, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsultedVoucher:
    """A voucher ARCA has on record, as `FECompConsultar` returns it."""

    result: AuthorizationResult
    voucher_number: int
    voucher_date: date
    document_type: int
    document_number: int
    total: Decimal
    cae: str
    cae_due_date: date
    observations: tuple[ArcaMessage, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class VoucherConsultation:
    """ARCA's answer to `FECompConsultar`; `voucher` is empty if ARCA has none."""

    voucher: ConsultedVoucher | None
    errors: tuple[ArcaMessage, ...]
    events: tuple[ArcaMessage, ...]


def parse_last_authorized_response(response: bytes) -> LastAuthorized:
    """Read ARCA's answer to `FECompUltimoAutorizado`.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response lacks what the service documents.
    """
    result = result_element(response, "FECompUltimoAutorizadoResult")
    return LastAuthorized(
        voucher_number=integer(result, "CbteNro"),
        errors=messages(result, "Errors/Err"),
        events=messages(result, "Events/Evt"),
    )


def parse_consult_response(response: bytes) -> VoucherConsultation:
    """Read ARCA's answer to `FECompConsultar`.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response has neither the voucher nor errors.
    """
    result = result_element(response, "FECompConsultarResult")
    errors = messages(result, "Errors/Err")
    events = messages(result, "Events/Evt")
    found = result.find(q("ResultGet"))
    if found is None:
        if not errors:
            raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, "ResultGet")
        return VoucherConsultation(voucher=None, errors=errors, events=events)
    voucher = ConsultedVoucher(
        result=_authorization_result(text(found, "Resultado")),
        voucher_number=integer(found, "CbteDesde"),
        voucher_date=date_of(found, "CbteFch"),
        document_type=integer(found, "DocTipo"),
        document_number=integer(found, "DocNro"),
        total=decimal(found, "ImpTotal"),
        cae=text(found, "CodAutorizacion"),
        cae_due_date=date_of(found, "FchVto"),
        observations=messages(found, "Observaciones/Obs"),
    )
    return VoucherConsultation(voucher=voucher, errors=errors, events=events)


def _rejection_without_detail(
    *, errors: tuple[ArcaMessage, ...], events: tuple[ArcaMessage, ...]
) -> VoucherAuthorization:
    # ARCA answers with errors alone when it refuses the request before looking at the voucher.
    if not errors:
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, "FECAEDetResponse")
    return VoucherAuthorization(
        result=AuthorizationResult.REJECTED,
        voucher_number=None,
        cae=None,
        cae_due_date=None,
        observations=(),
        errors=errors,
        events=events,
    )


def _authorization_result(text: str) -> AuthorizationResult:
    try:
        return AuthorizationResult(text)
    except ValueError as error:
        raise MalformedResponseError(ResponseDefect.INVALID_VALUE, "Resultado") from error
