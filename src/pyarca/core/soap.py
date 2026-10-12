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


class MalformedResponseError(ValueError):
    """A response does not have the structure the service documents."""

    def __init__(self, defect: ResponseDefect, element: str | None = None) -> None:
        """Build the error for a defect, naming the missing element when there is one."""
        super().__init__(defect if element is None else f"{defect}: {element}")
        self.defect = defect
        self.element = element


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
