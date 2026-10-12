"""The voucher a taxpayer asks ARCA to authorize, checked before anything is sent."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pyarca.core.amounts import amounts_match, validate_amount
from pyarca.core.wsfe_codes import (
    Concept,
    DocumentType,
    ReceiverVatCondition,
    VatRate,
    VoucherType,
)

PESOS = "PES"
PESOS_EXCHANGE_RATE = Decimal(1)
FINAL_CONSUMER_DOCUMENT_NUMBER = 0
MAX_VOUCHER_NUMBER = 99_999_999


class VoucherClass(StrEnum):
    """The letter of an invoice, which decides how VAT is stated."""

    B = "B"
    C = "C"


SUPPORTED_VOUCHER_CLASSES: dict[VoucherType, VoucherClass] = {
    VoucherType.INVOICE_B: VoucherClass.B,
    VoucherType.INVOICE_C: VoucherClass.C,
}

ALLOWED_RECEIVER_CONDITIONS: dict[VoucherClass, frozenset[ReceiverVatCondition]] = {
    VoucherClass.B: frozenset(
        {
            ReceiverVatCondition.EXEMPT,
            ReceiverVatCondition.FINAL_CONSUMER,
            ReceiverVatCondition.NOT_CATEGORIZED,
            ReceiverVatCondition.FOREIGN_SUPPLIER,
            ReceiverVatCondition.FOREIGN_CLIENT,
            ReceiverVatCondition.LIBERATED_LAW_19640,
            ReceiverVatCondition.NOT_SUBJECT_TO_VAT,
        }
    ),
    VoucherClass.C: frozenset(
        {
            ReceiverVatCondition.REGISTERED_COMPANY,
            ReceiverVatCondition.EXEMPT,
            ReceiverVatCondition.FINAL_CONSUMER,
            ReceiverVatCondition.MONOTAX,
            ReceiverVatCondition.NOT_CATEGORIZED,
            ReceiverVatCondition.FOREIGN_SUPPLIER,
            ReceiverVatCondition.FOREIGN_CLIENT,
            ReceiverVatCondition.LIBERATED_LAW_19640,
            ReceiverVatCondition.SOCIAL_MONOTAX,
            ReceiverVatCondition.NOT_SUBJECT_TO_VAT,
            ReceiverVatCondition.PROMOTED_INDEPENDENT_MONOTAX,
        }
    ),
}


class VoucherDefect(StrEnum):
    """Why a voucher cannot be authorized; most mirror the ARCA validation that would reject it."""

    UNSUPPORTED_VOUCHER_TYPE = "unsupported_voucher_type"
    UNSUPPORTED_CONCEPT = "unsupported_concept"
    UNSUPPORTED_CURRENCY = "unsupported_currency"
    EXCHANGE_RATE_NOT_ONE = "exchange_rate_not_one"
    FINAL_CONSUMER_DOCUMENT_NUMBER = "final_consumer_document_number"
    RECEIVER_CONDITION_NOT_ALLOWED = "receiver_condition_not_allowed"
    VAT_REQUIRED = "vat_required"
    VAT_NOT_ALLOWED = "vat_not_allowed"
    NON_NET_AMOUNT_NOT_ALLOWED = "non_net_amount_not_allowed"
    VAT_AMOUNT_MISMATCH = "vat_amount_mismatch"
    VAT_BASE_MISMATCH = "vat_base_mismatch"
    TOTAL_MISMATCH = "total_mismatch"
    VOUCHER_NUMBER_OUT_OF_RANGE = "voucher_number_out_of_range"


class InvalidVoucherError(ValueError):
    """A voucher breaks a rule ARCA enforces, or asks for something pyarca does not send yet."""

    def __init__(self, defect: VoucherDefect) -> None:
        """Build the error for the broken rule."""
        super().__init__(defect)
        self.defect = defect


@dataclass(frozen=True, slots=True, kw_only=True)
class VatLine:
    """One VAT aliquot: the taxable base it applies to and the tax charged on it."""

    rate: VatRate
    base: Decimal
    amount: Decimal

    def __post_init__(self) -> None:
        """Reject a base or amount ARCA cannot take as is."""
        validate_amount("vat_line.base", self.base)
        validate_amount("vat_line.amount", self.amount)


@dataclass(frozen=True, slots=True, kw_only=True)
class VoucherRequest:
    """A Factura B or C in pesos for products; the voucher number is chosen when it is sent."""

    point_of_sale: int
    voucher_type: VoucherType
    concept: Concept
    document_type: DocumentType
    document_number: int
    receiver_vat_condition: ReceiverVatCondition
    voucher_date: date
    total: Decimal
    non_taxed: Decimal
    net: Decimal
    exempt: Decimal
    vat_total: Decimal
    vat_lines: tuple[VatLine, ...]
    currency: str
    exchange_rate: Decimal

    def __post_init__(self) -> None:
        """Reject a voucher ARCA would refuse, naming the rule it breaks.

        Raises:
            InvalidAmountError: If an amount is not a `Decimal` that fits ARCA's format.
            InvalidVoucherError: If the voucher is not supported or its figures are inconsistent.
        """
        for name in ("total", "non_taxed", "net", "exempt", "vat_total", "exchange_rate"):
            validate_amount(name, getattr(self, name))
        _check_supported(self)
        _check_receiver(self)
        _check_class_rules(self)
        _check_total(self)


def _check_supported(request: VoucherRequest) -> None:
    if request.voucher_type not in SUPPORTED_VOUCHER_CLASSES:
        raise InvalidVoucherError(VoucherDefect.UNSUPPORTED_VOUCHER_TYPE)
    if request.concept != Concept.PRODUCTS:
        raise InvalidVoucherError(VoucherDefect.UNSUPPORTED_CONCEPT)
    if request.currency != PESOS:
        raise InvalidVoucherError(VoucherDefect.UNSUPPORTED_CURRENCY)
    if request.exchange_rate != PESOS_EXCHANGE_RATE:
        raise InvalidVoucherError(VoucherDefect.EXCHANGE_RATE_NOT_ONE)


def _check_receiver(request: VoucherRequest) -> None:
    voucher_class = SUPPORTED_VOUCHER_CLASSES[request.voucher_type]
    if request.receiver_vat_condition not in ALLOWED_RECEIVER_CONDITIONS[voucher_class]:
        raise InvalidVoucherError(VoucherDefect.RECEIVER_CONDITION_NOT_ALLOWED)
    is_final_consumer = request.document_type == DocumentType.FINAL_CONSUMER
    if is_final_consumer and request.document_number != FINAL_CONSUMER_DOCUMENT_NUMBER:
        raise InvalidVoucherError(VoucherDefect.FINAL_CONSUMER_DOCUMENT_NUMBER)


def _check_class_rules(request: VoucherRequest) -> None:
    CLASS_RULES[SUPPORTED_VOUCHER_CLASSES[request.voucher_type]](request)


def _check_invoice_b_vat(request: VoucherRequest) -> None:
    if request.net > 0 and not request.vat_lines:
        raise InvalidVoucherError(VoucherDefect.VAT_REQUIRED)
    lines = request.vat_lines
    amounts = sum((line.amount for line in lines), start=Decimal(0))
    if not amounts_match(amounts, request.vat_total, aliquots=max(len(lines), 1)):
        raise InvalidVoucherError(VoucherDefect.VAT_AMOUNT_MISMATCH)
    bases = sum((line.base for line in lines), start=Decimal(0))
    if not amounts_match(bases, request.net):
        raise InvalidVoucherError(VoucherDefect.VAT_BASE_MISMATCH)


def _check_invoice_c_amounts(request: VoucherRequest) -> None:
    if request.vat_lines or request.vat_total != 0:
        raise InvalidVoucherError(VoucherDefect.VAT_NOT_ALLOWED)
    if request.non_taxed != 0 or request.exempt != 0:
        raise InvalidVoucherError(VoucherDefect.NON_NET_AMOUNT_NOT_ALLOWED)


def _check_total(request: VoucherRequest) -> None:
    parts = request.non_taxed + request.net + request.exempt + request.vat_total
    if not amounts_match(parts, request.total):
        raise InvalidVoucherError(VoucherDefect.TOTAL_MISMATCH)


CLASS_RULES: dict[VoucherClass, Callable[[VoucherRequest], None]] = {
    VoucherClass.B: _check_invoice_b_vat,
    VoucherClass.C: _check_invoice_c_amounts,
}
