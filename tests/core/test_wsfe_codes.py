import pytest

from pyarca.core.wsfe_codes import (
    Concept,
    DocumentType,
    ReceiverVatCondition,
    TributeType,
    VatRate,
    VoucherType,
)


@pytest.mark.parametrize(
    ("member", "code"),
    [
        (VoucherType.INVOICE_A, 1),
        (VoucherType.INVOICE_B, 6),
        (VoucherType.INVOICE_C, 11),
        (VoucherType.CREDIT_NOTE_C, 13),
        (VoucherType.RECEIPT_A, 4),
        (VoucherType.RECEIPT_B, 9),
        (VoucherType.RECEIPT_C, 15),
        (VoucherType.FCE_INVOICE_B, 206),
        (DocumentType.CUIT, 80),
        (DocumentType.FINAL_CONSUMER, 99),
        (Concept.PRODUCTS, 1),
        (VatRate.RATE_21, 5),
        (VatRate.RATE_10_5, 4),
        (VatRate.RATE_0, 3),
        (VatRate.RATE_27, 6),
        (VatRate.RATE_5, 8),
        (VatRate.RATE_2_5, 9),
        (TributeType.GROSS_INCOME, 5),
        (TributeType.VAT_PERCEPTION, 6),
        (TributeType.OTHER, 99),
        (ReceiverVatCondition.FINAL_CONSUMER, 5),
        (ReceiverVatCondition.REGISTERED_COMPANY, 1),
    ],
)
def test_members_carry_the_code_arca_documents(member: int, code: int) -> None:
    assert member == code
