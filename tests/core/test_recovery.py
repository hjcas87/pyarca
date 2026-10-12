from pathlib import Path

import pytest

from pyarca.core.recovery import (
    ConsultationInconclusiveError,
    NotAuthorized,
    VoucherConflictField,
    VoucherNumberTakenError,
    resolve_ambiguous,
)
from pyarca.core.voucher import VoucherRequest
from pyarca.core.wsfe import AuthorizationResult, VoucherConsultation, parse_consult_response

FIXTURES = Path(__file__).parent / "fixtures/wsfe"
VOUCHER_NUMBER = 7
CONSULTED_CAE = "76412345678901"


def _consultation(name: str) -> VoucherConsultation:
    return parse_consult_response((FIXTURES / name).read_bytes())


def test_a_voucher_on_record_that_matches_the_request_is_the_authorization(
    invoice_b: VoucherRequest,
) -> None:
    resolution = resolve_ambiguous(invoice_b, VOUCHER_NUMBER, _consultation("consult_response.xml"))

    assert not isinstance(resolution, NotAuthorized)
    assert resolution.result == AuthorizationResult.APPROVED
    assert resolution.voucher_number == VOUCHER_NUMBER
    assert resolution.cae == CONSULTED_CAE
    assert resolution.errors == ()


@pytest.mark.parametrize(
    ("recorded", "other", "field"),
    [
        ("<CbteFch>20261012<", "<CbteFch>20261013<", VoucherConflictField.VOUCHER_DATE),
        ("<DocTipo>99<", "<DocTipo>80<", VoucherConflictField.DOCUMENT_TYPE),
        ("<DocNro>0<", "<DocNro>1<", VoucherConflictField.DOCUMENT_NUMBER),
        ("<ImpTotal>121<", "<ImpTotal>122<", VoucherConflictField.TOTAL),
    ],
)
def test_a_voucher_on_record_with_other_data_is_a_conflict_naming_what_differs(
    invoice_b: VoucherRequest, recorded: str, other: str, field: VoucherConflictField
) -> None:
    document = (FIXTURES / "consult_response.xml").read_text()
    consultation = parse_consult_response(document.replace(recorded, other).encode())

    with pytest.raises(VoucherNumberTakenError) as error:
        resolve_ambiguous(invoice_b, VOUCHER_NUMBER, consultation)

    assert error.value.voucher_number == VOUCHER_NUMBER
    assert error.value.differences == (field,)


def test_no_voucher_on_record_means_it_was_not_authorized_and_never_suggests_the_next_number(
    invoice_b: VoucherRequest,
) -> None:
    resolution = resolve_ambiguous(
        invoice_b, VOUCHER_NUMBER, _consultation("consult_response_not_found.xml")
    )

    assert resolution == NotAuthorized(voucher_number=VOUCHER_NUMBER)


def test_an_error_other_than_no_data_leaves_the_outcome_unknown(invoice_b: VoucherRequest) -> None:
    document = (FIXTURES / "consult_response_not_found.xml").read_text()
    consultation = parse_consult_response(document.replace(">602<", ">600<").encode())

    with pytest.raises(ConsultationInconclusiveError) as error:
        resolve_ambiguous(invoice_b, VOUCHER_NUMBER, consultation)

    assert [message.code for message in error.value.errors] == [600]
