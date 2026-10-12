"""Amount rules shared by every ARCA voucher: Decimal only, never rounded (ADR 0002)."""

from decimal import Decimal
from enum import StrEnum

MAX_INTEGER_DIGITS = 13
DECIMAL_PLACES = Decimal("0.01")
EXCHANGE_RATE_INTEGER_DIGITS = 4
EXCHANGE_RATE_PLACES = Decimal("0.000001")

# ARCA accepts a total that differs from the sum of its parts by at most this relative error...
RELATIVE_TOLERANCE = Decimal("0.0001")
# ...or this absolute error, multiplied by the number of VAT aliquots when summing VAT.
ABSOLUTE_TOLERANCE = Decimal("0.01")


class AmountDefect(StrEnum):
    """Why an amount cannot be sent to ARCA."""

    NOT_DECIMAL = "not_decimal"
    NOT_FINITE = "not_finite"
    NEGATIVE = "negative"
    NOT_POSITIVE = "not_positive"
    TOO_MANY_INTEGER_DIGITS = "too_many_integer_digits"
    TOO_MANY_DECIMALS = "too_many_decimals"


class InvalidAmountError(ValueError):
    """An amount does not fit ARCA's format; pyarca never converts or rounds it."""

    def __init__(self, field: str, defect: AmountDefect) -> None:
        """Build the error naming the offending field and why it was rejected."""
        super().__init__(f"{field}: {defect}")
        self.field = field
        self.defect = defect


def validate_amount(field: str, value: object) -> Decimal:
    """Return `value` when ARCA can take it as is: 13 integer digits, 2 decimals, not negative.

    Raises:
        InvalidAmountError: If `value` is not a `Decimal` or does not fit, so a caller's float
            or over-precise figure is reported instead of silently altered.
    """
    if not isinstance(value, Decimal):
        raise InvalidAmountError(field, AmountDefect.NOT_DECIMAL)
    if not value.is_finite():
        raise InvalidAmountError(field, AmountDefect.NOT_FINITE)
    if value < 0:
        raise InvalidAmountError(field, AmountDefect.NEGATIVE)
    if value.adjusted() >= MAX_INTEGER_DIGITS:
        raise InvalidAmountError(field, AmountDefect.TOO_MANY_INTEGER_DIGITS)
    if value != value.quantize(DECIMAL_PLACES):
        raise InvalidAmountError(field, AmountDefect.TOO_MANY_DECIMALS)
    return value


def validate_exchange_rate(value: object) -> Decimal:
    """Return `value` when ARCA can take it as `MonCotiz`: above zero, 4 integer digits, 6 decimals.

    Raises:
        InvalidAmountError: If `value` is not a `Decimal` or does not fit.
    """
    field = "exchange_rate"
    if not isinstance(value, Decimal):
        raise InvalidAmountError(field, AmountDefect.NOT_DECIMAL)
    if not value.is_finite():
        raise InvalidAmountError(field, AmountDefect.NOT_FINITE)
    if value <= 0:
        raise InvalidAmountError(field, AmountDefect.NOT_POSITIVE)
    if value.adjusted() >= EXCHANGE_RATE_INTEGER_DIGITS:
        raise InvalidAmountError(field, AmountDefect.TOO_MANY_INTEGER_DIGITS)
    if value != value.quantize(EXCHANGE_RATE_PLACES):
        raise InvalidAmountError(field, AmountDefect.TOO_MANY_DECIMALS)
    return value


def amounts_match(expected: Decimal, actual: Decimal, *, aliquots: int = 1) -> bool:
    """Tell whether `actual` is within ARCA's margin of `expected`.

    Args:
        expected: The amount computed from the parts.
        actual: The amount the voucher states.
        aliquots: Number of VAT aliquots summed into `actual`; widens the absolute margin.
    """
    difference = abs(expected - actual)
    return difference <= ABSOLUTE_TOLERANCE * aliquots or difference <= RELATIVE_TOLERANCE * abs(
        expected
    )


def format_amount(value: Decimal) -> str:
    """Write a validated amount the way ARCA reads it: exactly two decimals, no exponent."""
    return format(value.quantize(DECIMAL_PLACES), "f")
