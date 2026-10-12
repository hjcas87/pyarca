from enum import Enum

import pytest

from pyarca.core.amounts import AmountDefect, InvalidAmountError
from pyarca.core.recovery import (
    ConsultationInconclusiveError,
    VoucherConflictField,
    VoucherNumberTakenError,
)
from pyarca.core.soap import (
    MalformedResponseError,
    ResponseDefect,
    SoapFaultError,
)
from pyarca.core.voucher import InvalidVoucherError, VoucherDefect
from pyarca.core.wsaa import WsaaFaultCode, WsaaFaultError
from pyarca.core.wsfe_codes import ArcaErrorCode, VoucherType
from pyarca.core.wsfe_xml import ArcaMessage
from pyarca.shell.endpoints import Environment
from pyarca.shell.environment_guard import CertificateEnvironmentMismatchError
from pyarca.shell.messages import (
    AMOUNT_DEFECT_MESSAGES,
    ARCA_ERROR_MESSAGES,
    RESPONSE_DEFECT_MESSAGES,
    UNEXPECTED_ERROR_MESSAGE,
    VOUCHER_DEFECT_MESSAGES,
    WSAA_FAULT_MESSAGES,
    arca_error_message,
    user_message,
)
from pyarca.shell.transport import HttpStatusError, RequestNotSentError, ResponseLostError
from pyarca.shell.wsfe_client import (
    ArcaErrorsError,
    RecoveryFailedError,
    VoucherNotAuthorizedError,
    VoucherNumberMismatchError,
)


@pytest.mark.parametrize(
    ("codes", "catalog"),
    [
        (VoucherDefect, VOUCHER_DEFECT_MESSAGES),
        (AmountDefect, AMOUNT_DEFECT_MESSAGES),
        (ResponseDefect, RESPONSE_DEFECT_MESSAGES),
        (WsaaFaultCode, WSAA_FAULT_MESSAGES),
        (ArcaErrorCode, ARCA_ERROR_MESSAGES),
    ],
)
def test_every_member_has_a_message_and_the_catalog_has_nothing_else(
    codes: type[Enum], catalog: dict[Enum, str]
) -> None:
    assert set(catalog) == set(codes)
    assert all(message.strip() for message in catalog.values())


def test_a_voucher_defect_is_told_in_spanish() -> None:
    error = InvalidVoucherError(VoucherDefect.CBU_INVALID)

    assert user_message(error) == VOUCHER_DEFECT_MESSAGES[VoucherDefect.CBU_INVALID]
    assert "CBU" in user_message(error)


def test_an_amount_defect_is_told_in_spanish() -> None:
    error = InvalidAmountError("total", AmountDefect.TOO_MANY_DECIMALS)

    assert user_message(error) == AMOUNT_DEFECT_MESSAGES[AmountDefect.TOO_MANY_DECIMALS]


def test_a_malformed_response_is_told_without_its_technical_detail() -> None:
    error = MalformedResponseError(ResponseDefect.MISSING_ELEMENT, "CAE")

    assert user_message(error) == RESPONSE_DEFECT_MESSAGES[ResponseDefect.MISSING_ELEMENT]


def test_a_documented_wsaa_fault_is_told_in_spanish() -> None:
    error = WsaaFaultError(code="cms.cert.expired", description="Certificado expirado")

    assert user_message(error) == WSAA_FAULT_MESSAGES[WsaaFaultCode.CERTIFICATE_EXPIRED]


def test_an_undocumented_wsaa_fault_is_told_with_its_code() -> None:
    error = WsaaFaultError(code="coe.newCode", description="whatever")

    assert "coe.newCode" in user_message(error)


def test_arca_errors_are_told_one_sentence_each() -> None:
    error = ArcaErrorsError(
        (
            ArcaMessage(code=10164, message="x"),
            ArcaMessage(code=10170, message="y"),
        )
    )

    assert user_message(error) == " ".join(
        [
            ARCA_ERROR_MESSAGES[ArcaErrorCode.PAYMENT_DUE_BEFORE_ISSUE_OR_TODAY],
            ARCA_ERROR_MESSAGES[ArcaErrorCode.FCE_OPTIONAL_REQUIRED],
        ]
    )


def test_an_arca_error_the_catalog_does_not_know_keeps_its_code_and_arcas_wording() -> None:
    sentence = arca_error_message(ArcaMessage(code=99999, message="Texto de ARCA"))

    assert "99999" in sentence
    assert "Texto de ARCA" in sentence


def test_a_known_arca_error_is_told_with_the_catalog_wording() -> None:
    sentence = arca_error_message(ArcaMessage(code=10178, message="ignored"))

    assert sentence == ARCA_ERROR_MESSAGES[ArcaErrorCode.FCE_NOT_CATEGORIZED_RECEIVER]


def test_a_number_out_of_sequence_names_the_last_authorized_one() -> None:
    error = VoucherNumberMismatchError(arca_message="x", last_authorized_number=41)

    assert "41" in user_message(error)


def test_an_unconfirmed_voucher_names_what_to_reconcile() -> None:
    error = RecoveryFailedError(
        point_of_sale=3, voucher_type=VoucherType.INVOICE_C, voucher_number=17
    )

    sentence = user_message(error)

    assert "17" in sentence
    assert "3" in sentence


def test_a_voucher_arca_does_not_have_names_its_number() -> None:
    error = VoucherNotAuthorizedError(
        point_of_sale=3, voucher_type=VoucherType.INVOICE_C, voucher_number=17
    )

    assert "17" in user_message(error)


def test_a_number_taken_by_another_voucher_names_it() -> None:
    error = VoucherNumberTakenError(voucher_number=17, differences=(VoucherConflictField.TOTAL,))

    assert "17" in user_message(error)


@pytest.mark.parametrize(
    "error",
    [
        ConsultationInconclusiveError((ArcaMessage(code=600, message="x"),)),
        RequestNotSentError(),
        ResponseLostError(),
        HttpStatusError(502),
        SoapFaultError(code="Server", description="boom"),
        CertificateEnvironmentMismatchError(environment=Environment.PRODUCTION, issuer="x"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_every_other_failure_of_the_library_has_its_own_sentence(error: Exception) -> None:
    sentence = user_message(error)

    assert sentence != UNEXPECTED_ERROR_MESSAGE


def test_a_subclass_is_told_like_the_error_it_extends() -> None:
    class CustomVoucherError(InvalidVoucherError):
        pass

    error = CustomVoucherError(VoucherDefect.TOTAL_MISMATCH)

    assert user_message(error) == VOUCHER_DEFECT_MESSAGES[VoucherDefect.TOTAL_MISMATCH]


def test_an_error_the_catalog_does_not_know_is_told_generically() -> None:
    assert user_message(RuntimeError("boom")) == UNEXPECTED_ERROR_MESSAGE
