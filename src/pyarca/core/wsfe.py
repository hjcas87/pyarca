"""Requests and responses of WSFEv1, ARCA's electronic invoicing service."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from lxml import etree

from pyarca.core.amounts import format_amount
from pyarca.core.soap import (
    SOAP_ENVELOPE_NAMESPACE,
    MalformedResponseError,
    ResponseDefect,
    find_fault,
    parse_xml,
)
from pyarca.core.voucher import (
    MAX_VOUCHER_NUMBER,
    InvalidVoucherError,
    VoucherDefect,
    VoucherRequest,
)
from pyarca.core.wsaa import AccessTicket
from pyarca.core.wsfe_codes import VoucherType

WSFE_NAMESPACE = "http://ar.gov.afip.dif.FEV1/"
VOUCHER_DATE_FORMAT = "%Y%m%d"
SINGLE_VOUCHER_COUNT = 1
FOREIGN_SETTLEMENT_CODES = {True: "S", False: "N"}


class WsfeOperation(StrEnum):
    """The WSFE operations pyarca calls; each is also the tail of its SOAPAction."""

    AUTHORIZE = "FECAESolicitar"
    LAST_AUTHORIZED = "FECompUltimoAutorizado"
    CONSULT = "FECompConsultar"


def soap_action(operation: WsfeOperation) -> str:
    """Return the SOAPAction ARCA expects for `operation`."""
    return f"{WSFE_NAMESPACE}{operation}"


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
    envelope, operation = _start_request(WsfeOperation.AUTHORIZE, ticket=ticket, cuit=cuit)
    request = etree.SubElement(operation, _name("FeCAEReq"))
    header = etree.SubElement(request, _name("FeCabReq"))
    _add_text(header, "CantReg", SINGLE_VOUCHER_COUNT)
    _add_text(header, "PtoVta", voucher.point_of_sale)
    _add_text(header, "CbteTipo", voucher.voucher_type.value)
    details = etree.SubElement(request, _name("FeDetReq"))
    _add_detail(details, voucher=voucher, voucher_number=voucher_number)
    return _serialize(envelope)


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
    envelope, operation = _start_request(WsfeOperation.LAST_AUTHORIZED, ticket=ticket, cuit=cuit)
    _add_text(operation, "PtoVta", point_of_sale)
    _add_text(operation, "CbteTipo", voucher_type.value)
    return _serialize(envelope)


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
    envelope, operation = _start_request(WsfeOperation.CONSULT, ticket=ticket, cuit=cuit)
    query = etree.SubElement(operation, _name("FeCompConsReq"))
    _add_text(query, "CbteTipo", voucher_type.value)
    _add_text(query, "CbteNro", voucher_number)
    _add_text(query, "PtoVta", point_of_sale)
    return _serialize(envelope)


def _check_voucher_number(voucher_number: int) -> None:
    if not 1 <= voucher_number <= MAX_VOUCHER_NUMBER:
        raise InvalidVoucherError(VoucherDefect.VOUCHER_NUMBER_OUT_OF_RANGE)


def _start_request(
    operation: WsfeOperation, *, ticket: AccessTicket, cuit: int
) -> tuple[etree._Element, etree._Element]:
    envelope = etree.Element(
        etree.QName(SOAP_ENVELOPE_NAMESPACE, "Envelope"),
        nsmap={"soapenv": SOAP_ENVELOPE_NAMESPACE, "ar": WSFE_NAMESPACE},
    )
    body = etree.SubElement(envelope, etree.QName(SOAP_ENVELOPE_NAMESPACE, "Body"))
    element = etree.SubElement(body, _name(operation.value))
    _add_auth(element, ticket=ticket, cuit=cuit)
    return envelope, element


def _serialize(envelope: etree._Element) -> bytes:
    return etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")


def _add_auth(parent: etree._Element, *, ticket: AccessTicket, cuit: int) -> None:
    auth = etree.SubElement(parent, _name("Auth"))
    _add_text(auth, "Token", ticket.token)
    _add_text(auth, "Sign", ticket.sign)
    _add_text(auth, "Cuit", cuit)


# The service is an ASMX one: it rejects elements out of the order its WSDL declares.
def _add_detail(parent: etree._Element, *, voucher: VoucherRequest, voucher_number: int) -> None:
    detail = etree.SubElement(parent, _name("FECAEDetRequest"))
    _add_text(detail, "Concepto", voucher.concept.value)
    _add_text(detail, "DocTipo", voucher.document_type.value)
    _add_text(detail, "DocNro", voucher.document_number)
    _add_text(detail, "CbteDesde", voucher_number)
    _add_text(detail, "CbteHasta", voucher_number)
    _add_text(detail, "CbteFch", voucher.voucher_date.strftime(VOUCHER_DATE_FORMAT))
    _add_text(detail, "ImpTotal", format_amount(voucher.total))
    _add_text(detail, "ImpTotConc", format_amount(voucher.non_taxed))
    _add_text(detail, "ImpNeto", format_amount(voucher.net))
    _add_text(detail, "ImpOpEx", format_amount(voucher.exempt))
    _add_text(detail, "ImpTrib", format_amount(voucher.tributes_total))
    _add_text(detail, "ImpIVA", format_amount(voucher.vat_total))
    _add_service_period(detail, voucher)
    _add_text(detail, "MonId", voucher.currency)
    _add_text(detail, "MonCotiz", format(voucher.exchange_rate, "f"))
    if voucher.settles_in_foreign_currency is not None:
        _add_text(
            detail, "CanMisMonExt", FOREIGN_SETTLEMENT_CODES[voucher.settles_in_foreign_currency]
        )
    _add_text(detail, "CondicionIVAReceptorId", voucher.receiver_vat_condition.value)
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
    _add_text(parent, "FchServDesde", period.service_from.strftime(VOUCHER_DATE_FORMAT))
    _add_text(parent, "FchServHasta", period.service_to.strftime(VOUCHER_DATE_FORMAT))
    _add_text(parent, "FchVtoPago", period.payment_due.strftime(VOUCHER_DATE_FORMAT))


def _add_associated_vouchers(parent: etree._Element, voucher: VoucherRequest) -> None:
    associated = etree.SubElement(parent, _name("CbtesAsoc"))
    for item in voucher.associated_vouchers:
        element = etree.SubElement(associated, _name("CbteAsoc"))
        _add_text(element, "Tipo", item.voucher_type.value)
        _add_text(element, "PtoVta", item.point_of_sale)
        _add_text(element, "Nro", item.number)
        if item.cuit is not None:
            _add_text(element, "Cuit", item.cuit)
        if item.voucher_date is not None:
            _add_text(element, "CbteFch", item.voucher_date.strftime(VOUCHER_DATE_FORMAT))


def _add_tributes(parent: etree._Element, voucher: VoucherRequest) -> None:
    tributes = etree.SubElement(parent, _name("Tributos"))
    for tribute in voucher.tributes:
        element = etree.SubElement(tributes, _name("Tributo"))
        _add_text(element, "Id", tribute.tribute_type.value)
        if tribute.description:
            _add_text(element, "Desc", tribute.description)
        _add_text(element, "BaseImp", format_amount(tribute.base))
        _add_text(element, "Alic", format_amount(tribute.rate))
        _add_text(element, "Importe", format_amount(tribute.amount))


def _add_vat(parent: etree._Element, voucher: VoucherRequest) -> None:
    vat = etree.SubElement(parent, _name("Iva"))
    for line in voucher.vat_lines:
        aliquot = etree.SubElement(vat, _name("AlicIva"))
        _add_text(aliquot, "Id", line.rate.value)
        _add_text(aliquot, "BaseImp", format_amount(line.base))
        _add_text(aliquot, "Importe", format_amount(line.amount))


def _add_optionals(parent: etree._Element, voucher: VoucherRequest) -> None:
    optionals = etree.SubElement(parent, _name("Opcionales"))
    for optional in voucher.optionals:
        element = etree.SubElement(optionals, _name("Opcional"))
        _add_text(element, "Id", optional.optional_id.value)
        _add_text(element, "Valor", optional.value)


def _name(tag: str) -> etree.QName:
    return etree.QName(WSFE_NAMESPACE, tag)


def _add_text(parent: etree._Element, tag: str, value: object) -> None:
    etree.SubElement(parent, _name(tag)).text = str(value)


class AuthorizationResult(StrEnum):
    """`Resultado`: whether ARCA authorized the voucher; the CAE alone does not say so."""

    APPROVED = "A"
    REJECTED = "R"
    PARTIAL = "P"


@dataclass(frozen=True, slots=True, kw_only=True)
class ArcaMessage:
    """An observation, error or event ARCA reports, with its code and its own wording."""

    code: int
    message: str


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
    result = _result_element(response, "FECAESolicitarResult")
    errors = _messages(result, "Errors/Err")
    events = _messages(result, "Events/Evt")
    detail = result.find(_q("FeDetResp/FECAEDetResponse"))
    if detail is None:
        return _rejection_without_detail(errors=errors, events=events)

    outcome = _authorization_result(_text(detail, "Resultado"))
    cae = (detail.findtext(_q("CAE")) or "").strip() or None
    if outcome == AuthorizationResult.APPROVED and cae is None:
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, "CAE")
    return VoucherAuthorization(
        result=outcome,
        voucher_number=_integer(detail, "CbteDesde"),
        cae=cae,
        cae_due_date=None if cae is None else _date(detail, "CAEFchVto"),
        observations=_messages(detail, "Observaciones/Obs"),
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
    result = _result_element(response, "FECompUltimoAutorizadoResult")
    return LastAuthorized(
        voucher_number=_integer(result, "CbteNro"),
        errors=_messages(result, "Errors/Err"),
        events=_messages(result, "Events/Evt"),
    )


def parse_consult_response(response: bytes) -> VoucherConsultation:
    """Read ARCA's answer to `FECompConsultar`.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response has neither the voucher nor errors.
    """
    result = _result_element(response, "FECompConsultarResult")
    errors = _messages(result, "Errors/Err")
    events = _messages(result, "Events/Evt")
    found = result.find(_q("ResultGet"))
    if found is None:
        if not errors:
            raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, "ResultGet")
        return VoucherConsultation(voucher=None, errors=errors, events=events)
    voucher = ConsultedVoucher(
        result=_authorization_result(_text(found, "Resultado")),
        voucher_number=_integer(found, "CbteDesde"),
        voucher_date=_date(found, "CbteFch"),
        document_type=_integer(found, "DocTipo"),
        document_number=_integer(found, "DocNro"),
        total=_decimal(found, "ImpTotal"),
        cae=_text(found, "CodAutorizacion"),
        cae_due_date=_date(found, "FchVto"),
        observations=_messages(found, "Observaciones/Obs"),
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


def _result_element(response: bytes, tag: str) -> etree._Element:
    envelope = parse_xml(response)
    fault = find_fault(envelope)
    if fault is not None:
        raise fault
    result = envelope.find(f".//{_q(tag)}")
    if result is None:
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, tag)
    return result


def _q(path: str) -> str:
    return "/".join(f"{{{WSFE_NAMESPACE}}}{tag}" for tag in path.split("/"))


def _text(element: etree._Element, tag: str) -> str:
    text = element.findtext(_q(tag))
    if text is None or not text.strip():
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, tag)
    return text.strip()


def _authorization_result(text: str) -> AuthorizationResult:
    try:
        return AuthorizationResult(text)
    except ValueError as error:
        raise MalformedResponseError(ResponseDefect.INVALID_VALUE, "Resultado") from error


def _integer(element: etree._Element, tag: str) -> int:
    try:
        return int(_text(element, tag))
    except ValueError as error:
        raise MalformedResponseError(ResponseDefect.INVALID_NUMBER, tag) from error


def _decimal(element: etree._Element, tag: str) -> Decimal:
    try:
        return Decimal(_text(element, tag))
    except InvalidOperation as error:
        raise MalformedResponseError(ResponseDefect.INVALID_NUMBER, tag) from error


def _date(element: etree._Element, tag: str) -> date:
    try:
        return datetime.strptime(_text(element, tag), VOUCHER_DATE_FORMAT).date()  # noqa: DTZ007
    except ValueError as error:
        raise MalformedResponseError(ResponseDefect.INVALID_DATE, tag) from error


def _messages(element: etree._Element, path: str) -> tuple[ArcaMessage, ...]:
    return tuple(
        ArcaMessage(code=_integer(message, "Code"), message=message.findtext(_q("Msg"), ""))
        for message in element.findall(_q(path))
    )
