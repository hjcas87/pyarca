"""Decide what an ambiguous authorization became, from what ARCA has on record (ADR 0004)."""

from dataclasses import dataclass
from enum import StrEnum

from pyarca.core.voucher import VoucherRequest
from pyarca.core.wsfe import (
    ConsultedVoucher,
    VoucherAuthorization,
    VoucherConsultation,
)
from pyarca.core.wsfe_codes import ArcaErrorCode
from pyarca.core.wsfe_xml import ArcaMessage


class VoucherConflictField(StrEnum):
    """What of a voucher on record differs from the request that was sent."""

    VOUCHER_DATE = "voucher_date"
    DOCUMENT_TYPE = "document_type"
    DOCUMENT_NUMBER = "document_number"
    TOTAL = "total"


class VoucherNumberTakenError(Exception):
    """ARCA has a different voucher under the number: another issuer took it."""

    def __init__(
        self, *, voucher_number: int, differences: tuple[VoucherConflictField, ...]
    ) -> None:
        """Build the error naming the number and what differs from the request."""
        super().__init__(f"{voucher_number}: {', '.join(differences)}")
        self.voucher_number = voucher_number
        self.differences = differences


class ConsultationInconclusiveError(Exception):
    """ARCA answered the consultation with errors that do not say whether the voucher exists."""

    def __init__(self, errors: tuple[ArcaMessage, ...]) -> None:
        """Build the error from the codes ARCA returned."""
        super().__init__(", ".join(str(message.code) for message in errors))
        self.errors = errors


@dataclass(frozen=True, slots=True, kw_only=True)
class NotAuthorized:
    """ARCA has no voucher under the number, so sending the same request again is safe."""

    voucher_number: int


def resolve_ambiguous(
    request: VoucherRequest, number: int, consultation: VoucherConsultation
) -> VoucherAuthorization | NotAuthorized:
    """Say whether the voucher sent under `number` was authorized, without ever renumbering.

    Args:
        request: The voucher that was sent.
        number: The number it was sent under.
        consultation: ARCA's answer to `FECompConsultar` for that number.

    Returns:
        The authorization found on record, or `NotAuthorized` when ARCA has no such voucher.

    Raises:
        VoucherNumberTakenError: If ARCA has a different voucher under the number.
        ConsultationInconclusiveError: If ARCA's errors do not say whether the voucher exists.
    """
    recorded = consultation.voucher
    if recorded is None:
        return _not_authorized(number, consultation)
    differences = _differences(request, recorded)
    if differences:
        raise VoucherNumberTakenError(voucher_number=number, differences=differences)
    return VoucherAuthorization(
        result=recorded.result,
        voucher_number=recorded.voucher_number,
        cae=recorded.cae,
        cae_due_date=recorded.cae_due_date,
        observations=recorded.observations,
        errors=(),
        events=consultation.events,
    )


def _not_authorized(number: int, consultation: VoucherConsultation) -> NotAuthorized:
    if any(message.code != ArcaErrorCode.NO_DATA_FOUND for message in consultation.errors):
        raise ConsultationInconclusiveError(consultation.errors)
    return NotAuthorized(voucher_number=number)


def _differences(
    request: VoucherRequest, recorded: ConsultedVoucher
) -> tuple[VoucherConflictField, ...]:
    matches = {
        VoucherConflictField.VOUCHER_DATE: request.voucher_date == recorded.voucher_date,
        VoucherConflictField.DOCUMENT_TYPE: request.document_type == recorded.document_type,
        VoucherConflictField.DOCUMENT_NUMBER: request.document_number == recorded.document_number,
        VoucherConflictField.TOTAL: request.total == recorded.total,
    }
    return tuple(field for field, matched in matches.items() if not matched)
