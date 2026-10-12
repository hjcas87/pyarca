"""SOAP 1.1 plumbing shared by the requests and responses of every ARCA service."""

from enum import StrEnum

from lxml import etree

SOAP_ENVELOPE_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"


class ResponseDefect(StrEnum):
    """Why a response was rejected before reading its content."""

    NOT_XML = "not_xml"
    DOCUMENT_TYPE = "document_type"
    MISSING_ELEMENT = "missing_element"
    INVALID_TIME = "invalid_time"
    INVALID_DATE = "invalid_date"
    INVALID_NUMBER = "invalid_number"
    INVALID_VALUE = "invalid_value"


class MalformedResponseError(ValueError):
    """A response does not have the structure the service documents."""

    def __init__(self, defect: ResponseDefect, element: str | None = None) -> None:
        """Build the error for a defect, naming the missing element when there is one."""
        super().__init__(defect if element is None else f"{defect}: {element}")
        self.defect = defect
        self.element = element


class SoapFaultError(Exception):
    """The service answered with a SOAP fault instead of a result."""

    def __init__(self, *, code: str, description: str) -> None:
        """Build the error from the fault code, without its namespace prefix, and its text."""
        super().__init__(code)
        self.code = code
        self.description = description


def parse_xml(document: bytes) -> etree._Element:
    """Parse a response without network access or entity resolution.

    Raises:
        MalformedResponseError: If `document` is not XML or declares a document type.
    """
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(document, parser=parser)
    except etree.XMLSyntaxError as error:
        raise MalformedResponseError(ResponseDefect.NOT_XML) from error
    # SOAP 1.1 forbids document type declarations, and entity expansion is how they are abused.
    if root.getroottree().docinfo.doctype:
        raise MalformedResponseError(ResponseDefect.DOCUMENT_TYPE)
    return root


def required_text(element: etree._Element, path: str) -> str:
    """Return the text at `path` below `element`.

    Raises:
        MalformedResponseError: If the element is missing or blank.
    """
    text = element.findtext(path)
    if text is None or not text.strip():
        raise MalformedResponseError(ResponseDefect.MISSING_ELEMENT, path)
    return text


def find_fault(envelope: etree._Element) -> SoapFaultError | None:
    """Return the SOAP fault carried by `envelope`, if it carries one."""
    fault = envelope.find(f".//{{{SOAP_ENVELOPE_NAMESPACE}}}Fault")
    if fault is None:
        return None
    # The fault code is a qualified name such as `soap:Server`; only its local part identifies it.
    code = required_text(fault, "faultcode").rpartition(":")[2]
    return SoapFaultError(code=code, description=fault.findtext("faultstring", default=""))
