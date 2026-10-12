"""XML plumbing shared by every WSFEv1 request and response."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from lxml import etree

from pyarca.core.soap import (
    SOAP_ENVELOPE_NAMESPACE,
    MalformedResponseError,
    ResponseDefect,
    find_fault,
    parse_xml,
)
from pyarca.core.wsaa import AccessTicket

WSFE_NAMESPACE = "http://ar.gov.afip.dif.FEV1/"
VOUCHER_DATE_FORMAT = "%Y%m%d"


class WsfeOperation(StrEnum):
    """The WSFE operations pyarca calls; each is also the tail of its SOAPAction."""

    AUTHORIZE = "FECAESolicitar"
    LAST_AUTHORIZED = "FECompUltimoAutorizado"
    CONSULT = "FECompConsultar"


def soap_action(operation: WsfeOperation) -> str:
    """Return the SOAPAction ARCA expects for `operation`."""
    return f"{WSFE_NAMESPACE}{operation}"


@dataclass(frozen=True, slots=True, kw_only=True)
class ArcaMessage:
    """An observation, error or event ARCA reports, with its code and its own wording."""

    code: int
    message: str


def start_request(
    operation: WsfeOperation, *, ticket: AccessTicket, cuit: int
) -> tuple[etree._Element, etree._Element]:
    """Open the SOAP envelope of an authenticated `operation` and return it with its element."""
    envelope = etree.Element(
        etree.QName(SOAP_ENVELOPE_NAMESPACE, "Envelope"),
        nsmap={"soapenv": SOAP_ENVELOPE_NAMESPACE, "ar": WSFE_NAMESPACE},
    )
    body = etree.SubElement(envelope, etree.QName(SOAP_ENVELOPE_NAMESPACE, "Body"))
    element = etree.SubElement(body, name(operation.value))
    _add_auth(element, ticket=ticket, cuit=cuit)
    return envelope, element


def serialize(envelope: etree._Element) -> bytes:
    """Write the envelope as UTF-8 XML with its declaration."""
    return etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")


def _add_auth(parent: etree._Element, *, ticket: AccessTicket, cuit: int) -> None:
    auth = etree.SubElement(parent, name("Auth"))
    add_text(auth, "Token", ticket.token)
    add_text(auth, "Sign", ticket.sign)
    add_text(auth, "Cuit", cuit)


def name(tag: str) -> etree.QName:
    """Qualify `tag` with the WSFE namespace."""
    return etree.QName(WSFE_NAMESPACE, tag)


def add_text(parent: etree._Element, tag: str, value: object) -> None:
    """Append a WSFE child element holding `value` as text."""
    etree.SubElement(parent, name(tag)).text = str(value)


def result_element(response: bytes, tag: str) -> etree._Element:
    """Return the `tag` element of a response, raising its SOAP fault instead if it carries one.

    Raises:
        SoapFaultError: If the service answered with a SOAP fault.
        MalformedResponseError: If the response is not XML or lacks `tag`.
    """
    envelope = parse_xml(response)
    fault = find_fault(envelope)
    if fault is not None:
        raise fault
    result = envelope.find(f".//{q(tag)}")
    if result is None:
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, tag)
    return result


def q(path: str) -> str:
    """Qualify each tag of a `/`-separated path with the WSFE namespace."""
    return "/".join(f"{{{WSFE_NAMESPACE}}}{tag}" for tag in path.split("/"))


def text(element: etree._Element, tag: str) -> str:
    """Return the stripped text of the child `tag`.

    Raises:
        MalformedResponseError: If the child is missing or blank.
    """
    value = element.findtext(q(tag))
    if value is None or not value.strip():
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, tag)
    return value.strip()


def integer(element: etree._Element, tag: str) -> int:
    """Return the child `tag` as an integer.

    Raises:
        MalformedResponseError: If the child is missing or not an integer.
    """
    try:
        return int(text(element, tag))
    except ValueError as error:
        raise MalformedResponseError(ResponseDefect.INVALID_NUMBER, tag) from error


def decimal(element: etree._Element, tag: str) -> Decimal:
    """Return the child `tag` as a decimal.

    Raises:
        MalformedResponseError: If the child is missing or not a number.
    """
    try:
        return Decimal(text(element, tag))
    except InvalidOperation as error:
        raise MalformedResponseError(ResponseDefect.INVALID_NUMBER, tag) from error


def date_of(element: etree._Element, tag: str) -> date:
    """Return the child `tag` as a date written `yyyymmdd`.

    Raises:
        MalformedResponseError: If the child is missing or not such a date.
    """
    try:
        return datetime.strptime(text(element, tag), VOUCHER_DATE_FORMAT).date()  # noqa: DTZ007
    except ValueError as error:
        raise MalformedResponseError(ResponseDefect.INVALID_DATE, tag) from error


def messages(element: etree._Element, path: str) -> tuple[ArcaMessage, ...]:
    """Return the errors, events or observations found at `path` below `element`."""
    return tuple(
        ArcaMessage(code=integer(message, "Code"), message=message.findtext(q("Msg"), ""))
        for message in element.findall(q(path))
    )
