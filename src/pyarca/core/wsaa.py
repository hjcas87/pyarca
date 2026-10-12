"""Requests and responses of WSAA, ARCA's authentication service."""

import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from lxml import etree

from pyarca.core.soap import (
    SOAP_ENVELOPE_NAMESPACE,
    MalformedResponseError,
    ResponseDefect,
    parse_xml,
    required_text,
)

LOGIN_TICKET_REQUEST_VERSION = "1.0"
WSAA_NAMESPACE = "http://wsaa.view.sua.dvadac.desein.afip.gov"
MAX_UNIQUE_ID = 2**32 - 1

# WSAA rejects a request generated after its own current time, so the generation time is set
# before `now` to absorb a local clock running ahead of ARCA's.
CLOCK_SKEW_MARGIN = timedelta(minutes=10)

# Anyone holding a signed request can exchange it for an access ticket until it expires, so it
# lives only long enough to reach WSAA.
REQUEST_LIFETIME = timedelta(minutes=10)


class Service(StrEnum):
    """ARCA business web services an access ticket can be requested for."""

    WSFE = "wsfe"


class WsaaFaultCode(StrEnum):
    """Fault codes documented in the WSAA technical specification."""

    NOT_AUTHORIZED = "coe.notAuthorized"
    ALREADY_AUTHENTICATED = "coe.alreadyAuthenticated"
    CMS_INVALID = "cms.bad"
    CMS_BASE64_INVALID = "cms.bad.base64"
    CERTIFICATE_NOT_FOUND = "cms.cert.notFound"
    SIGNATURE_INVALID = "cms.sign.invalid"
    CERTIFICATE_EXPIRED = "cms.cert.expired"
    CERTIFICATE_NOT_YET_VALID = "cms.cert.invalid"
    CERTIFICATE_UNTRUSTED = "cms.cert.untrusted"
    XML_INVALID = "xml.bad"
    SOURCE_INVALID = "xml.source.invalid"
    DESTINATION_INVALID = "xml.destination.invalid"
    VERSION_NOT_SUPPORTED = "xml.version.notSupported"
    GENERATION_TIME_INVALID = "xml.generationTime.invalid"
    REQUEST_EXPIRED = "xml.expirationTime.expired"
    EXPIRATION_TIME_INVALID = "xml.expirationTime.invalid"
    SERVICE_UNAVAILABLE = "wsn.unavailable"
    SERVICE_NOT_FOUND = "wsn.notFound"
    WSAA_UNAVAILABLE = "wsaa.unavailable"
    WSAA_INTERNAL_ERROR = "wsaa.internalError"


class WsaaFaultError(Exception):
    """WSAA refused the login with a SOAP fault."""

    def __init__(self, *, code: str, description: str) -> None:
        """Build the error from the fault code and ARCA's description.

        `code` is a plain string because ARCA adds codes without notice; documented ones compare
        equal to `WsaaFaultCode` members.
        """
        super().__init__(code)
        self.code = code
        self.description = description


class NaiveTimeError(ValueError):
    """A time without timezone reached a request; ARCA rejects times without offset."""

    def __init__(self) -> None:
        """Build the error."""
        super().__init__("the time must carry a timezone")


class UniqueIdOutOfRangeError(ValueError):
    """The login ticket request id does not fit in 32 unsigned bits."""

    def __init__(self, unique_id: int) -> None:
        """Build the error for the rejected id."""
        super().__init__(f"unique_id must fit in 32 unsigned bits, got {unique_id}")
        self.unique_id = unique_id


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessTicket:
    """Credentials WSAA issues for one service, valid until `expires_at`."""

    token: str = field(repr=False)
    sign: str = field(repr=False)
    expires_at: datetime


def build_login_ticket_request(*, service: Service, unique_id: int, now: datetime) -> bytes:
    """Build the login ticket request (TRA) that is signed and sent to WSAA.

    Args:
        service: The web service the access ticket is for.
        unique_id: Unsigned 32-bit id that, with the generation time, identifies the request.
        now: The current time, timezone-aware.

    Returns:
        The request as UTF-8 XML bytes.

    Raises:
        NaiveTimeError: If `now` has no UTC offset.
        UniqueIdOutOfRangeError: If `unique_id` does not fit in 32 unsigned bits.
    """
    if now.utcoffset() is None:
        raise NaiveTimeError
    if not 0 <= unique_id <= MAX_UNIQUE_ID:
        raise UniqueIdOutOfRangeError(unique_id)

    # Arithmetic in a zone with DST moves the wall clock, not the instant; UTC has no transitions.
    now_utc = now.astimezone(UTC)
    root = etree.Element("loginTicketRequest", version=LOGIN_TICKET_REQUEST_VERSION)
    header = etree.SubElement(root, "header")
    etree.SubElement(header, "uniqueId").text = str(unique_id)
    etree.SubElement(header, "generationTime").text = _format_time(now_utc - CLOCK_SKEW_MARGIN)
    etree.SubElement(header, "expirationTime").text = _format_time(now_utc + REQUEST_LIFETIME)
    etree.SubElement(root, "service").text = service
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_login_cms_request(signed_request: bytes) -> bytes:
    """Build the SOAP request for WSAA `loginCms`.

    Args:
        signed_request: The login ticket request signed as CMS, in DER.

    Returns:
        The SOAP envelope as UTF-8 XML bytes.
    """
    envelope = etree.Element(
        etree.QName(SOAP_ENVELOPE_NAMESPACE, "Envelope"),
        nsmap={"soapenv": SOAP_ENVELOPE_NAMESPACE, "wsaa": WSAA_NAMESPACE},
    )
    body = etree.SubElement(envelope, etree.QName(SOAP_ENVELOPE_NAMESPACE, "Body"))
    login = etree.SubElement(body, etree.QName(WSAA_NAMESPACE, "loginCms"))
    signed_request_text = base64.b64encode(signed_request).decode("ascii")
    etree.SubElement(login, etree.QName(WSAA_NAMESPACE, "in0")).text = signed_request_text
    return etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")


def parse_login_cms_response(response: bytes) -> AccessTicket:
    """Read the access ticket out of a WSAA `loginCms` response.

    Args:
        response: The SOAP response body as returned by WSAA.

    Returns:
        The access ticket, expiring when WSAA says it does.

    Raises:
        WsaaFaultError: If WSAA answered with a SOAP fault.
        MalformedResponseError: If the response is not a well-formed login ticket response.
    """
    envelope = parse_xml(response)
    fault = envelope.find(f".//{{{SOAP_ENVELOPE_NAMESPACE}}}Fault")
    if fault is not None:
        raise _fault_error(fault)

    login_ticket = envelope.findtext(f".//{{{WSAA_NAMESPACE}}}loginCmsReturn")
    if login_ticket is None:
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, "loginCmsReturn")

    ticket = parse_xml(login_ticket.encode())
    return AccessTicket(
        token=required_text(ticket, "credentials/token"),
        sign=required_text(ticket, "credentials/sign"),
        expires_at=_required_time(ticket, "header/expirationTime"),
    )


def _fault_error(fault: etree._Element) -> WsaaFaultError:
    # The fault code is a qualified name such as `ns1:coe.alreadyAuthenticated`; only its local
    # part identifies the error.
    code = required_text(fault, "faultcode").rpartition(":")[2]
    return WsaaFaultError(code=code, description=fault.findtext("faultstring", default=""))


def _required_time(element: etree._Element, path: str) -> datetime:
    text = required_text(element, path)
    try:
        value = datetime.fromisoformat(text)
    except ValueError as error:
        raise MalformedResponseError(ResponseDefect.INVALID_TIME, path) from error
    if value.utcoffset() is None:
        raise MalformedResponseError(ResponseDefect.INVALID_TIME, path)
    return value


def _format_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")
