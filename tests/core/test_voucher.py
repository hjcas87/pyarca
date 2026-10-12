from collections.abc import Callable
from dataclasses import fields
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest

from pyarca.core.amounts import AmountDefect, InvalidAmountError
from pyarca.core.voucher import (
    InvalidVoucherError,
    VatLine,
    VoucherDefect,
    VoucherRequest,
)
from pyarca.core.wsfe_codes import (
    Concept,
    DocumentType,
    ReceiverVatCondition,
    VatRate,
    VoucherType,
)

PESOS = "PES"


BASE_INVOICE_B = VoucherRequest(
    point_of_sale=1,
    voucher_type=VoucherType.INVOICE_B,
    concept=Concept.PRODUCTS,
    document_type=DocumentType.FINAL_CONSUMER,
    document_number=0,
    receiver_vat_condition=ReceiverVatCondition.FINAL_CONSUMER,
    voucher_date=date(2026, 10, 12),
    total=Decimal("121.00"),
    non_taxed=Decimal(0),
    net=Decimal("100.00"),
    exempt=Decimal(0),
    vat_total=Decimal("21.00"),
    vat_lines=(VatLine(rate=VatRate.RATE_21, base=Decimal("100.00"), amount=Decimal("21.00")),),
    currency=PESOS,
    exchange_rate=Decimal(1),
)


def _with(changes: dict[str, object]) -> VoucherRequest:
    values = {field.name: getattr(BASE_INVOICE_B, field.name) for field in fields(BASE_INVOICE_B)}
    return VoucherRequest(**cast("dict[str, Any]", {**values, **changes}))


def _invoice_b(**overrides: object) -> VoucherRequest:
    return _with(overrides)


def _invoice_c(**overrides: object) -> VoucherRequest:
    defaults: dict[str, object] = {
        "voucher_type": VoucherType.INVOICE_C,
        "total": Decimal("100.00"),
        "vat_total": Decimal(0),
        "vat_lines": (),
    }
    return _with({**defaults, **overrides})


def _defect_of(build: Callable[[], object]) -> VoucherDefect:
    with pytest.raises(InvalidVoucherError) as error:
        build()
    return error.value.defect


def test_a_consistent_invoice_b_is_accepted() -> None:
    assert _invoice_b().total == Decimal("121.00")


def test_a_consistent_invoice_c_is_accepted() -> None:
    assert _invoice_c().vat_lines == ()


def test_amounts_inside_arcas_margin_are_accepted() -> None:
    request = _invoice_b(total=Decimal("121.01"))

    assert request.total == Decimal("121.01")


def test_a_float_amount_is_rejected_instead_of_converted() -> None:
    with pytest.raises(InvalidAmountError) as error:
        _invoice_b(total=121.0)

    assert error.value.field == "total"
    assert error.value.defect == AmountDefect.NOT_DECIMAL


def test_a_vat_line_amount_with_more_than_two_decimals_is_rejected() -> None:
    with pytest.raises(InvalidAmountError) as error:
        VatLine(rate=VatRate.RATE_21, base=Decimal("100.00"), amount=Decimal("21.001"))

    assert error.value.field == "vat_line.amount"
    assert error.value.defect == AmountDefect.TOO_MANY_DECIMALS


def test_a_total_that_is_not_the_sum_of_its_parts_is_rejected() -> None:
    assert _defect_of(lambda: _invoice_b(total=Decimal("130.00"))) == VoucherDefect.TOTAL_MISMATCH


def test_vat_lines_that_do_not_add_up_to_the_vat_total_are_rejected() -> None:
    lines = (VatLine(rate=VatRate.RATE_21, base=Decimal("100.00"), amount=Decimal("20.00")),)

    assert _defect_of(lambda: _invoice_b(vat_lines=lines)) == VoucherDefect.VAT_AMOUNT_MISMATCH


def test_vat_bases_that_do_not_add_up_to_the_net_are_rejected() -> None:
    lines = (VatLine(rate=VatRate.RATE_21, base=Decimal("90.00"), amount=Decimal("21.00")),)

    assert _defect_of(lambda: _invoice_b(vat_lines=lines)) == VoucherDefect.VAT_BASE_MISMATCH


def test_an_invoice_b_with_net_and_no_vat_lines_is_rejected() -> None:
    defect = _defect_of(
        lambda: _invoice_b(vat_lines=(), vat_total=Decimal(0), total=Decimal("100.00"))
    )

    assert defect == VoucherDefect.VAT_REQUIRED


def test_an_invoice_c_with_vat_lines_is_rejected() -> None:
    assert _defect_of(lambda: _invoice_c(vat_lines=_invoice_b().vat_lines)) == (
        VoucherDefect.VAT_NOT_ALLOWED
    )


@pytest.mark.parametrize(
    ("field", "defect"),
    [
        ("vat_total", VoucherDefect.VAT_NOT_ALLOWED),
        ("non_taxed", VoucherDefect.NON_NET_AMOUNT_NOT_ALLOWED),
        ("exempt", VoucherDefect.NON_NET_AMOUNT_NOT_ALLOWED),
    ],
)
def test_an_invoice_c_must_state_only_its_net_amount(field: str, defect: VoucherDefect) -> None:
    request = {field: Decimal("10.00"), "total": Decimal("110.00")}

    assert _defect_of(lambda: _invoice_c(**request)) == defect


def test_a_receiver_condition_not_allowed_for_the_class_is_rejected() -> None:
    defect = _defect_of(
        lambda: _invoice_b(receiver_vat_condition=ReceiverVatCondition.REGISTERED_COMPANY)
    )

    assert defect == VoucherDefect.RECEIVER_CONDITION_NOT_ALLOWED


def test_an_invoice_c_accepts_a_registered_company_receiver() -> None:
    request = _invoice_c(
        receiver_vat_condition=ReceiverVatCondition.REGISTERED_COMPANY,
        document_type=DocumentType.CUIT,
        document_number=20111111112,
    )

    assert request.receiver_vat_condition == ReceiverVatCondition.REGISTERED_COMPANY


def test_a_final_consumer_must_carry_document_number_zero() -> None:
    assert _defect_of(lambda: _invoice_b(document_number=1)) == (
        VoucherDefect.FINAL_CONSUMER_DOCUMENT_NUMBER
    )


@pytest.mark.parametrize(
    ("overrides", "defect"),
    [
        ({"voucher_type": VoucherType.INVOICE_A}, VoucherDefect.UNSUPPORTED_VOUCHER_TYPE),
        ({"concept": Concept.SERVICES}, VoucherDefect.UNSUPPORTED_CONCEPT),
        ({"currency": "USD"}, VoucherDefect.UNSUPPORTED_CURRENCY),
        ({"exchange_rate": Decimal(2)}, VoucherDefect.EXCHANGE_RATE_NOT_ONE),
    ],
)
def test_what_this_version_cannot_authorize_is_rejected(
    overrides: dict[str, object], defect: VoucherDefect
) -> None:
    assert _defect_of(lambda: _invoice_b(**overrides)) == defect


def test_a_float_exchange_rate_is_rejected() -> None:
    with pytest.raises(InvalidAmountError):
        _invoice_b(exchange_rate=1.0)
