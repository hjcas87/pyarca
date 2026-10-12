"""The voucher a taxpayer asks ARCA to authorize, checked before anything is sent."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pyarca.core.amounts import amounts_match, validate_amount, validate_exchange_rate
from pyarca.core.wsfe_codes import (
    Concept,
    DocumentType,
    ReceiverVatCondition,
    TributeType,
    VatRate,
    VoucherType,
)

PESOS = "PES"
PESOS_EXCHANGE_RATE = Decimal(1)
FINAL_CONSUMER_DOCUMENT_NUMBER = 0
MAX_VOUCHER_NUMBER = 99_999_999
MIN_INVOICE_A_RECEIVER_CUIT = 20_000_000_000
MAX_INVOICE_A_RECEIVER_CUIT = 60_000_000_000
MAX_TRIBUTE_DESCRIPTION_LENGTH = 80
TRIBUTE_RATE_INTEGER_DIGITS = 3
MAX_POINT_OF_SALE = 99_999
CUIT_DIGITS = 11
CURRENCY_CODE = re.compile(r"[A-Z0-9]{3}")


class VoucherClass(StrEnum):
    """The letter of an invoice, which decides how VAT is stated."""

    A = "A"
    B = "B"
    C = "C"


SUPPORTED_VOUCHER_CLASSES: dict[VoucherType, VoucherClass] = {
    VoucherType.INVOICE_A: VoucherClass.A,
    VoucherType.DEBIT_NOTE_A: VoucherClass.A,
    VoucherType.CREDIT_NOTE_A: VoucherClass.A,
    VoucherType.INVOICE_B: VoucherClass.B,
    VoucherType.DEBIT_NOTE_B: VoucherClass.B,
    VoucherType.CREDIT_NOTE_B: VoucherClass.B,
    VoucherType.INVOICE_C: VoucherClass.C,
    VoucherType.DEBIT_NOTE_C: VoucherClass.C,
    VoucherType.CREDIT_NOTE_C: VoucherClass.C,
}

_ASSOCIABLE_TO_NOTES_A = frozenset(
    {
        VoucherType.INVOICE_A,
        VoucherType.DEBIT_NOTE_A,
        VoucherType.CREDIT_NOTE_A,
        VoucherType.RECEIPT_A,
    }
)
_ASSOCIABLE_TO_NOTES_B = frozenset(
    {
        VoucherType.INVOICE_B,
        VoucherType.DEBIT_NOTE_B,
        VoucherType.CREDIT_NOTE_B,
        VoucherType.RECEIPT_B,
    }
)
_ASSOCIABLE_TO_NOTES_C = frozenset(
    {
        VoucherType.INVOICE_C,
        VoucherType.DEBIT_NOTE_C,
        VoucherType.CREDIT_NOTE_C,
        VoucherType.RECEIPT_C,
    }
)

# Developer manual, error 10040: the vouchers a debit or credit note may be associated to.
ASSOCIABLE_VOUCHER_TYPES: dict[VoucherType, frozenset[VoucherType]] = {
    VoucherType.DEBIT_NOTE_A: _ASSOCIABLE_TO_NOTES_A,
    VoucherType.CREDIT_NOTE_A: _ASSOCIABLE_TO_NOTES_A,
    VoucherType.DEBIT_NOTE_B: _ASSOCIABLE_TO_NOTES_B,
    VoucherType.CREDIT_NOTE_B: _ASSOCIABLE_TO_NOTES_B,
    VoucherType.DEBIT_NOTE_C: _ASSOCIABLE_TO_NOTES_C,
    VoucherType.CREDIT_NOTE_C: _ASSOCIABLE_TO_NOTES_C,
}

# Error 10061 does not apply to notes: a partial note may state its VAT bases proportionally.
VAT_BASE_CHECKED_TYPES = frozenset({VoucherType.INVOICE_A, VoucherType.INVOICE_B})

ALLOWED_RECEIVER_CONDITIONS: dict[VoucherClass, frozenset[ReceiverVatCondition]] = {
    VoucherClass.A: frozenset(
        {
            ReceiverVatCondition.REGISTERED_COMPANY,
            ReceiverVatCondition.MONOTAX,
            ReceiverVatCondition.SOCIAL_MONOTAX,
            ReceiverVatCondition.PROMOTED_INDEPENDENT_MONOTAX,
        }
    ),
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
    INVALID_CURRENCY_CODE = "invalid_currency_code"
    EXCHANGE_RATE_NOT_ONE = "exchange_rate_not_one"
    FOREIGN_SETTLEMENT_WITH_PESOS = "foreign_settlement_with_pesos"
    SERVICE_PERIOD_REQUIRED = "service_period_required"
    SERVICE_PERIOD_REVERSED = "service_period_reversed"
    PAYMENT_DUE_BEFORE_VOUCHER_DATE = "payment_due_before_voucher_date"
    FINAL_CONSUMER_DOCUMENT_NUMBER = "final_consumer_document_number"
    RECEIVER_CONDITION_NOT_ALLOWED = "receiver_condition_not_allowed"
    DOCUMENT_TYPE_NOT_ALLOWED = "document_type_not_allowed"
    DOCUMENT_NUMBER_OUT_OF_RANGE = "document_number_out_of_range"
    VAT_REQUIRED = "vat_required"
    VAT_NOT_ALLOWED = "vat_not_allowed"
    NON_NET_AMOUNT_NOT_ALLOWED = "non_net_amount_not_allowed"
    VAT_AMOUNT_MISMATCH = "vat_amount_mismatch"
    VAT_BASE_MISMATCH = "vat_base_mismatch"
    TOTAL_MISMATCH = "total_mismatch"
    VOUCHER_NUMBER_OUT_OF_RANGE = "voucher_number_out_of_range"
    TRIBUTES_WITHOUT_AMOUNT = "tributes_without_amount"
    TRIBUTE_DESCRIPTION_REQUIRED = "tribute_description_required"
    TRIBUTE_DESCRIPTION_TOO_LONG = "tribute_description_too_long"
    TRIBUTE_RATE_OUT_OF_RANGE = "tribute_rate_out_of_range"
    ASSOCIATED_VOUCHER_REQUIRED = "associated_voucher_required"
    ASSOCIATED_VOUCHER_NOT_ALLOWED = "associated_voucher_not_allowed"
    ASSOCIATED_VOUCHER_TYPE_INCOMPATIBLE = "associated_voucher_type_incompatible"
    ASSOCIATED_VOUCHER_DUPLICATED = "associated_voucher_duplicated"
    ASSOCIATED_VOUCHER_DATE_NOT_ALLOWED = "associated_voucher_date_not_allowed"
    ASSOCIATED_POINT_OF_SALE_OUT_OF_RANGE = "associated_point_of_sale_out_of_range"
    ASSOCIATED_NUMBER_OUT_OF_RANGE = "associated_number_out_of_range"
    ASSOCIATED_CUIT_INVALID = "associated_cuit_invalid"


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
class Tribute:
    """One tax other than VAT stated on a voucher, such as a perception."""

    tribute_type: TributeType
    description: str | None
    base: Decimal
    rate: Decimal
    amount: Decimal

    def __post_init__(self) -> None:
        """Reject a tribute ARCA cannot take as is.

        Raises:
            InvalidAmountError: If an amount does not fit ARCA's format.
            InvalidVoucherError: If the description or the rate breaks ARCA's rules.
        """
        validate_amount("tribute.base", self.base)
        validate_amount("tribute.rate", self.rate)
        validate_amount("tribute.amount", self.amount)
        if self.rate.adjusted() >= TRIBUTE_RATE_INTEGER_DIGITS:
            raise InvalidVoucherError(VoucherDefect.TRIBUTE_RATE_OUT_OF_RANGE)
        if self.tribute_type == TributeType.OTHER and not self.description:
            raise InvalidVoucherError(VoucherDefect.TRIBUTE_DESCRIPTION_REQUIRED)
        if len(self.description or "") > MAX_TRIBUTE_DESCRIPTION_LENGTH:
            raise InvalidVoucherError(VoucherDefect.TRIBUTE_DESCRIPTION_TOO_LONG)


@dataclass(frozen=True, slots=True, kw_only=True)
class AssociatedVoucher:
    """A voucher a note refers to, identified by the point of sale it was issued from."""

    voucher_type: VoucherType
    point_of_sale: int
    number: int
    cuit: int | None
    voucher_date: date | None

    def __post_init__(self) -> None:
        """Reject a reference ARCA would refuse.

        Raises:
            InvalidVoucherError: If the point of sale, number or CUIT is out of range.
        """
        if not 1 <= self.point_of_sale <= MAX_POINT_OF_SALE:
            raise InvalidVoucherError(VoucherDefect.ASSOCIATED_POINT_OF_SALE_OUT_OF_RANGE)
        if not 1 <= self.number <= MAX_VOUCHER_NUMBER:
            raise InvalidVoucherError(VoucherDefect.ASSOCIATED_NUMBER_OUT_OF_RANGE)
        if self.cuit is not None and len(str(self.cuit)) != CUIT_DIGITS:
            raise InvalidVoucherError(VoucherDefect.ASSOCIATED_CUIT_INVALID)


@dataclass(frozen=True, slots=True, kw_only=True)
class ServicePeriod:
    """The period a service is billed for and when its payment falls due."""

    service_from: date
    service_to: date
    payment_due: date

    def __post_init__(self) -> None:
        """Reject a period that ends before it starts.

        Raises:
            InvalidVoucherError: If `service_to` is earlier than `service_from`.
        """
        if self.service_to < self.service_from:
            raise InvalidVoucherError(VoucherDefect.SERVICE_PERIOD_REVERSED)


@dataclass(frozen=True, slots=True, kw_only=True)
class VoucherRequest:
    """A factura or nota A, B or C; the voucher number is chosen when it is sent."""

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
    tributes: tuple[Tribute, ...] = ()
    associated_vouchers: tuple[AssociatedVoucher, ...] = ()
    service_period: ServicePeriod | None = None
    settles_in_foreign_currency: bool | None = None

    @property
    def tributes_total(self) -> Decimal:
        """Return `ImpTrib`: the sum of the tribute amounts."""
        return sum((tribute.amount for tribute in self.tributes), start=Decimal(0))

    def __post_init__(self) -> None:
        """Reject a voucher ARCA would refuse, naming the rule it breaks.

        Raises:
            InvalidAmountError: If an amount is not a `Decimal` that fits ARCA's format.
            InvalidVoucherError: If the voucher is not supported or its figures are inconsistent.
        """
        for name in ("total", "non_taxed", "net", "exempt", "vat_total"):
            validate_amount(name, getattr(self, name))
        validate_exchange_rate(self.exchange_rate)
        _check_supported(self)
        _check_currency(self)
        _check_service_period(self)
        _check_receiver(self)
        _check_class_rules(self)
        _check_associated_vouchers(self)
        _check_tributes(self)
        _check_total(self)


def _check_supported(request: VoucherRequest) -> None:
    if request.voucher_type not in SUPPORTED_VOUCHER_CLASSES:
        raise InvalidVoucherError(VoucherDefect.UNSUPPORTED_VOUCHER_TYPE)


def _check_currency(request: VoucherRequest) -> None:
    if not CURRENCY_CODE.fullmatch(request.currency):
        raise InvalidVoucherError(VoucherDefect.INVALID_CURRENCY_CODE)
    if request.currency != PESOS:
        return
    if request.exchange_rate != PESOS_EXCHANGE_RATE:
        raise InvalidVoucherError(VoucherDefect.EXCHANGE_RATE_NOT_ONE)
    if request.settles_in_foreign_currency is not None:
        raise InvalidVoucherError(VoucherDefect.FOREIGN_SETTLEMENT_WITH_PESOS)


def _check_service_period(request: VoucherRequest) -> None:
    period = request.service_period
    if period is None:
        if request.concept != Concept.PRODUCTS:
            raise InvalidVoucherError(VoucherDefect.SERVICE_PERIOD_REQUIRED)
        return
    if period.payment_due < request.voucher_date:
        raise InvalidVoucherError(VoucherDefect.PAYMENT_DUE_BEFORE_VOUCHER_DATE)


def _check_receiver(request: VoucherRequest) -> None:
    voucher_class = SUPPORTED_VOUCHER_CLASSES[request.voucher_type]
    if request.receiver_vat_condition not in ALLOWED_RECEIVER_CONDITIONS[voucher_class]:
        raise InvalidVoucherError(VoucherDefect.RECEIVER_CONDITION_NOT_ALLOWED)
    is_final_consumer = request.document_type == DocumentType.FINAL_CONSUMER
    if is_final_consumer and request.document_number != FINAL_CONSUMER_DOCUMENT_NUMBER:
        raise InvalidVoucherError(VoucherDefect.FINAL_CONSUMER_DOCUMENT_NUMBER)


def _check_class_rules(request: VoucherRequest) -> None:
    CLASS_RULES[SUPPORTED_VOUCHER_CLASSES[request.voucher_type]](request)


def _check_invoice_a(request: VoucherRequest) -> None:
    if request.document_type != DocumentType.CUIT:
        raise InvalidVoucherError(VoucherDefect.DOCUMENT_TYPE_NOT_ALLOWED)
    if not MIN_INVOICE_A_RECEIVER_CUIT <= request.document_number <= MAX_INVOICE_A_RECEIVER_CUIT:
        raise InvalidVoucherError(VoucherDefect.DOCUMENT_NUMBER_OUT_OF_RANGE)
    _check_itemized_vat(request)


def _check_itemized_vat(request: VoucherRequest) -> None:
    if request.net > 0 and not request.vat_lines:
        raise InvalidVoucherError(VoucherDefect.VAT_REQUIRED)
    lines = request.vat_lines
    amounts = sum((line.amount for line in lines), start=Decimal(0))
    if not amounts_match(amounts, request.vat_total, aliquots=max(len(lines), 1)):
        raise InvalidVoucherError(VoucherDefect.VAT_AMOUNT_MISMATCH)
    bases = sum((line.base for line in lines), start=Decimal(0))
    checks_base = request.voucher_type in VAT_BASE_CHECKED_TYPES
    if checks_base and not amounts_match(bases, request.net):
        raise InvalidVoucherError(VoucherDefect.VAT_BASE_MISMATCH)


def _check_invoice_c_amounts(request: VoucherRequest) -> None:
    if request.vat_lines or request.vat_total != 0:
        raise InvalidVoucherError(VoucherDefect.VAT_NOT_ALLOWED)
    if request.non_taxed != 0 or request.exempt != 0:
        raise InvalidVoucherError(VoucherDefect.NON_NET_AMOUNT_NOT_ALLOWED)


def _check_associated_vouchers(request: VoucherRequest) -> None:
    associable = ASSOCIABLE_VOUCHER_TYPES.get(request.voucher_type)
    if associable is None:
        if request.associated_vouchers:
            raise InvalidVoucherError(VoucherDefect.ASSOCIATED_VOUCHER_NOT_ALLOWED)
        return
    if not request.associated_vouchers:
        raise InvalidVoucherError(VoucherDefect.ASSOCIATED_VOUCHER_REQUIRED)
    identities = {
        (voucher.voucher_type, voucher.point_of_sale, voucher.number)
        for voucher in request.associated_vouchers
    }
    if len(identities) != len(request.associated_vouchers):
        raise InvalidVoucherError(VoucherDefect.ASSOCIATED_VOUCHER_DUPLICATED)
    for voucher in request.associated_vouchers:
        _check_associated(voucher, associable=associable, note_date=request.voucher_date)


def _check_associated(
    voucher: AssociatedVoucher, *, associable: frozenset[VoucherType], note_date: date
) -> None:
    if voucher.voucher_type not in associable:
        raise InvalidVoucherError(VoucherDefect.ASSOCIATED_VOUCHER_TYPE_INCOMPATIBLE)
    if _is_dated_in_a_later_month(voucher.voucher_date, note_date):
        raise InvalidVoucherError(VoucherDefect.ASSOCIATED_VOUCHER_DATE_NOT_ALLOWED)


def _is_dated_in_a_later_month(associated_date: date | None, note_date: date) -> bool:
    if associated_date is None or associated_date <= note_date:
        return False
    return (associated_date.year, associated_date.month) != (note_date.year, note_date.month)


def _check_tributes(request: VoucherRequest) -> None:
    if request.tributes and request.tributes_total == 0:
        raise InvalidVoucherError(VoucherDefect.TRIBUTES_WITHOUT_AMOUNT)


def _check_total(request: VoucherRequest) -> None:
    parts = (
        request.non_taxed
        + request.net
        + request.exempt
        + request.vat_total
        + request.tributes_total
    )
    if not amounts_match(parts, request.total):
        raise InvalidVoucherError(VoucherDefect.TOTAL_MISMATCH)


CLASS_RULES: dict[VoucherClass, Callable[[VoucherRequest], None]] = {
    VoucherClass.A: _check_invoice_a,
    VoucherClass.B: _check_itemized_vat,
    VoucherClass.C: _check_invoice_c_amounts,
}
