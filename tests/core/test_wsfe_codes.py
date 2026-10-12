import pytest

from pyarca.core.wsfe_codes import (
    Concept,
    DocumentType,
    ReceiverVatCondition,
    VatRate,
    VoucherType,
)


@pytest.mark.parametrize(
    ("member", "code"),
    [
        (VoucherType.INVOICE_B, 6),
        (VoucherType.INVOICE_C, 11),
        (VoucherType.CREDIT_NOTE_C, 13),
        (VoucherType.FCE_INVOICE_B, 206),
        (DocumentType.CUIT, 80),
        (DocumentType.FINAL_CONSUMER, 99),
        (Concept.PRODUCTS, 1),
        (VatRate.RATE_21, 5),
        (VatRate.RATE_10_5, 4),
        (ReceiverVatCondition.FINAL_CONSUMER, 5),
        (ReceiverVatCondition.REGISTERED_COMPANY, 1),
    ],
)
def test_members_carry_the_code_arca_documents(member: int, code: int) -> None:
    assert member == code
