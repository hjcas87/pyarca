"""Requests and responses of WSFEv1, ARCA's electronic invoicing service."""

from decimal import Decimal

from lxml import etree

from pyarca.core.amounts import format_amount
from pyarca.core.soap import SOAP_ENVELOPE_NAMESPACE
from pyarca.core.voucher import (
    MAX_VOUCHER_NUMBER,
    InvalidVoucherError,
    VoucherDefect,
    VoucherRequest,
)
from pyarca.core.wsaa import AccessTicket

WSFE_NAMESPACE = "http://ar.gov.afip.dif.FEV1/"
VOUCHER_DATE_FORMAT = "%Y%m%d"
SINGLE_VOUCHER_COUNT = 1
# Tributos are not sent yet, so the other-taxes total is always zero.
NO_TRIBUTES = Decimal(0)


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
    if not 1 <= voucher_number <= MAX_VOUCHER_NUMBER:
        raise InvalidVoucherError(VoucherDefect.VOUCHER_NUMBER_OUT_OF_RANGE)

    envelope = etree.Element(
        etree.QName(SOAP_ENVELOPE_NAMESPACE, "Envelope"),
        nsmap={"soapenv": SOAP_ENVELOPE_NAMESPACE, "ar": WSFE_NAMESPACE},
    )
    body = etree.SubElement(envelope, etree.QName(SOAP_ENVELOPE_NAMESPACE, "Body"))
    operation = etree.SubElement(body, _name("FECAESolicitar"))
    _add_auth(operation, ticket=ticket, cuit=cuit)
    request = etree.SubElement(operation, _name("FeCAEReq"))
    header = etree.SubElement(request, _name("FeCabReq"))
    _add_text(header, "CantReg", SINGLE_VOUCHER_COUNT)
    _add_text(header, "PtoVta", voucher.point_of_sale)
    _add_text(header, "CbteTipo", voucher.voucher_type.value)
    details = etree.SubElement(request, _name("FeDetReq"))
    _add_detail(details, voucher=voucher, voucher_number=voucher_number)
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
    _add_text(detail, "ImpTrib", format_amount(NO_TRIBUTES))
    _add_text(detail, "ImpIVA", format_amount(voucher.vat_total))
    _add_text(detail, "MonId", voucher.currency)
    _add_text(detail, "MonCotiz", format(voucher.exchange_rate, "f"))
    _add_text(detail, "CondicionIVAReceptorId", voucher.receiver_vat_condition.value)
    if voucher.vat_lines:
        _add_vat(detail, voucher)


def _add_vat(parent: etree._Element, voucher: VoucherRequest) -> None:
    vat = etree.SubElement(parent, _name("Iva"))
    for line in voucher.vat_lines:
        aliquot = etree.SubElement(vat, _name("AlicIva"))
        _add_text(aliquot, "Id", line.rate.value)
        _add_text(aliquot, "BaseImp", format_amount(line.base))
        _add_text(aliquot, "Importe", format_amount(line.amount))


def _name(tag: str) -> etree.QName:
    return etree.QName(WSFE_NAMESPACE, tag)


def _add_text(parent: etree._Element, tag: str, value: object) -> None:
    etree.SubElement(parent, _name(tag)).text = str(value)
