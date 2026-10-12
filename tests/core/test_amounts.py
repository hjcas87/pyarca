from decimal import Decimal

import pytest

from pyarca.core.amounts import (
    AmountDefect,
    InvalidAmountError,
    amounts_match,
    validate_amount,
    validate_exchange_rate,
)

FIELD = "total"


@pytest.mark.parametrize(
    "value",
    [Decimal(0), Decimal("0.01"), Decimal("1.50"), Decimal("1.500"), Decimal("9999999999999.99")],
)
def test_an_amount_within_arca_precision_is_returned_unchanged(value: Decimal) -> None:
    assert validate_amount(FIELD, value) == value


@pytest.mark.parametrize(
    ("value", "defect"),
    [
        (1.5, AmountDefect.NOT_DECIMAL),
        (1, AmountDefect.NOT_DECIMAL),
        ("1.5", AmountDefect.NOT_DECIMAL),
        (Decimal("NaN"), AmountDefect.NOT_FINITE),
        (Decimal("Infinity"), AmountDefect.NOT_FINITE),
        (Decimal("-0.01"), AmountDefect.NEGATIVE),
        (Decimal("0.001"), AmountDefect.TOO_MANY_DECIMALS),
        (Decimal(10000000000000), AmountDefect.TOO_MANY_INTEGER_DIGITS),
    ],
)
def test_an_amount_arca_would_misread_is_rejected_instead_of_converted_or_rounded(
    value: object, defect: AmountDefect
) -> None:
    with pytest.raises(InvalidAmountError) as error:
        validate_amount(FIELD, value)

    assert error.value.field == FIELD
    assert error.value.defect == defect


@pytest.mark.parametrize(
    ("expected", "actual", "aliquots"),
    [
        (Decimal("100.00"), Decimal("100.00"), 1),
        (Decimal("100.00"), Decimal("100.01"), 1),
        (Decimal("100.00"), Decimal("99.99"), 1),
        (Decimal("100.00"), Decimal("100.03"), 3),
        (Decimal("1000000.00"), Decimal("1000100.00"), 1),
    ],
)
def test_amounts_inside_arcas_margin_match(
    expected: Decimal, actual: Decimal, aliquots: int
) -> None:
    assert amounts_match(expected, actual, aliquots=aliquots)


@pytest.mark.parametrize(
    ("expected", "actual", "aliquots"),
    [
        (Decimal("100.00"), Decimal("100.02"), 1),
        (Decimal("100.00"), Decimal("100.04"), 3),
        (Decimal("1000000.00"), Decimal("1000100.02"), 1),
    ],
)
def test_amounts_outside_arcas_margin_do_not_match(
    expected: Decimal, actual: Decimal, aliquots: int
) -> None:
    assert not amounts_match(expected, actual, aliquots=aliquots)


@pytest.mark.parametrize(
    "value",
    [Decimal(1), Decimal("0.000001"), Decimal("1050.123456"), Decimal("9999.999999")],
)
def test_an_exchange_rate_within_arca_precision_is_returned_unchanged(value: Decimal) -> None:
    assert validate_exchange_rate(value) == value


@pytest.mark.parametrize(
    ("value", "defect"),
    [
        (1.5, AmountDefect.NOT_DECIMAL),
        (Decimal("NaN"), AmountDefect.NOT_FINITE),
        (Decimal(0), AmountDefect.NOT_POSITIVE),
        (Decimal(-1), AmountDefect.NOT_POSITIVE),
        (Decimal("1.0000001"), AmountDefect.TOO_MANY_DECIMALS),
        (Decimal(10000), AmountDefect.TOO_MANY_INTEGER_DIGITS),
    ],
)
def test_an_exchange_rate_arca_would_misread_is_rejected(
    value: object, defect: AmountDefect
) -> None:
    with pytest.raises(InvalidAmountError) as error:
        validate_exchange_rate(value)

    assert error.value.field == "exchange_rate"
    assert error.value.defect == defect
