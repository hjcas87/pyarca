"""Requests and responses of WSAA, ARCA's authentication service."""

import base64
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from lxml import etree

LOGIN_TICKET_REQUEST_VERSION = "1.0"
SOAP_ENVELOPE_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"
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


def _format_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")
