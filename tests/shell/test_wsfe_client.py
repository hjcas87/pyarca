from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pyarca.core.recovery import VoucherConflictField, VoucherNumberTakenError
from pyarca.core.voucher import VoucherRequest
from pyarca.core.wsaa import AccessTicket, Service
from pyarca.core.wsfe import (
    AuthorizationResult,
    build_authorize_request,
    build_consult_request,
    build_last_authorized_request,
)
from pyarca.core.wsfe_codes import VoucherType
from pyarca.shell.endpoints import WSFE_ENDPOINTS, Environment
from pyarca.shell.transport import HttpStatusError, RequestNotSentError, ResponseLostError
from pyarca.shell.wsfe_client import (
    ArcaErrorsError,
    RecoveryFailedError,
    VoucherNotAuthorizedError,
    VoucherNumberMismatchError,
    WsfeClient,
)

FIXTURES = Path(__file__).parent.parent / "core/fixtures/wsfe"
CUIT = 20111111112
POINT_OF_SALE = 1
LAST_AUTHORIZED = 6
TICKET = AccessTicket(token="TOKEN", sign="SIGN", expires_at=datetime(2026, 10, 13, tzinfo=UTC))
URL = WSFE_ENDPOINTS[Environment.HOMOLOGATION]
ACTION_PREFIX = "http://ar.gov.afip.dif.FEV1/"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


LAST_RESPONSE = _fixture("last_authorized_response.xml")
APPROVED = _fixture("authorize_response_approved.xml")
ERRORS = _fixture("authorize_response_errors.xml")
REJECTED = _fixture("authorize_response_rejected.xml")
CONSULTED = _fixture("consult_response.xml")
NOT_FOUND = _fixture("consult_response_not_found.xml")
FAULT = _fixture("fault.xml")
NEXT_NUMBER = LAST_AUTHORIZED + 1
CONSULTED_CAE = "76412345678901"
BAD_GATEWAY = 502
BAD_REQUEST = 400


@dataclass
class FakeTicketProvider:
    requested: list[Service] = field(default_factory=list)

    def get_access_ticket(self, service: Service) -> AccessTicket:
        self.requested.append(service)
        return TICKET


@dataclass
class FakeTransport:
    answers: list[bytes | Exception]
    posts: list[tuple[str, bytes, str]] = field(default_factory=list)

    def post(self, *, url: str, body: bytes, soap_action: str) -> bytes:
        self.posts.append((url, body, soap_action))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _client(transport: FakeTransport, provider: FakeTicketProvider | None = None) -> WsfeClient:
    return WsfeClient(
        ticket_provider=provider or FakeTicketProvider(),
        transport=transport,
        environment=Environment.HOMOLOGATION,
        cuit=CUIT,
    )


def test_last_authorized_asks_wsfe_with_a_wsfe_ticket() -> None:
    provider = FakeTicketProvider()
    transport = FakeTransport([LAST_RESPONSE])

    number = _client(transport, provider).last_authorized(
        point_of_sale=POINT_OF_SALE, voucher_type=VoucherType.INVOICE_B
    )

    assert number == LAST_AUTHORIZED
    assert provider.requested == [Service.WSFE]
    assert transport.posts == [
        (
            URL,
            build_last_authorized_request(
                ticket=TICKET,
                cuit=CUIT,
                point_of_sale=POINT_OF_SALE,
                voucher_type=VoucherType.INVOICE_B,
            ),
            f"{ACTION_PREFIX}FECompUltimoAutorizado",
        )
    ]


def test_last_authorized_reports_the_errors_arca_returns() -> None:
    transport = FakeTransport([_fixture("last_authorized_response_errors.xml")])

    with pytest.raises(ArcaErrorsError) as error:
        _client(transport).last_authorized(
            point_of_sale=POINT_OF_SALE, voucher_type=VoucherType.INVOICE_B
        )

    assert [message.code for message in error.value.errors] == [600]


def test_authorize_numbers_the_voucher_one_past_the_last_authorized(
    invoice_b: VoucherRequest,
) -> None:
    transport = FakeTransport([LAST_RESPONSE, APPROVED])

    authorization = _client(transport).authorize(invoice_b)

    assert authorization.result == AuthorizationResult.APPROVED
    assert authorization.cae == "86410988009458"
    assert transport.posts[1] == (
        URL,
        build_authorize_request(
            ticket=TICKET, cuit=CUIT, voucher=invoice_b, voucher_number=LAST_AUTHORIZED + 1
        ),
        f"{ACTION_PREFIX}FECAESolicitar",
    )


def test_a_rejection_without_errors_is_returned_for_the_caller_to_read(
    invoice_b: VoucherRequest,
) -> None:
    transport = FakeTransport([LAST_RESPONSE, REJECTED])

    authorization = _client(transport).authorize(invoice_b)

    assert authorization.result == AuthorizationResult.REJECTED
    assert authorization.cae is None


@pytest.mark.parametrize(
    "answer", [ERRORS, REJECTED.replace(b">10048<", b">10016<")], ids=["error", "observation"]
)
def test_error_10016_reports_the_last_authorized_number_and_never_renumbers(
    invoice_b: VoucherRequest, answer: bytes
) -> None:
    newer_last = LAST_RESPONSE.replace(b"<CbteNro>6<", b"<CbteNro>8<")
    transport = FakeTransport([LAST_RESPONSE, answer, newer_last])

    with pytest.raises(VoucherNumberMismatchError) as error:
        _client(transport).authorize(invoice_b)

    assert error.value.last_authorized_number == LAST_AUTHORIZED + 2
    assert error.value.arca_message.startswith(("Error sample", "Rejection sample"))
    actions = [action for _, _, action in transport.posts]
    assert actions.count(f"{ACTION_PREFIX}FECAESolicitar") == 1


def test_any_other_arca_error_is_raised_with_its_codes(invoice_b: VoucherRequest) -> None:
    transport = FakeTransport([LAST_RESPONSE, ERRORS.replace(b">10016<", b">10000<")])

    with pytest.raises(ArcaErrorsError) as error:
        _client(transport).authorize(invoice_b)

    assert [message.code for message in error.value.errors] == [10000]


def _actions(transport: FakeTransport) -> list[str]:
    return [action.removeprefix(ACTION_PREFIX) for _, _, action in transport.posts]


@pytest.mark.parametrize(
    "lost", [ResponseLostError(), HttpStatusError(BAD_GATEWAY), FAULT], ids=["lost", "5xx", "fault"]
)
def test_an_ambiguous_outcome_is_resolved_by_consulting_the_same_number(
    invoice_b: VoucherRequest, lost: bytes | Exception
) -> None:
    transport = FakeTransport([LAST_RESPONSE, lost, CONSULTED])

    authorization = _client(transport).authorize(invoice_b)

    assert authorization.result == AuthorizationResult.APPROVED
    assert authorization.cae == CONSULTED_CAE
    assert authorization.voucher_number == NEXT_NUMBER
    assert _actions(transport) == ["FECompUltimoAutorizado", "FECAESolicitar", "FECompConsultar"]
    assert transport.posts[2][1] == build_consult_request(
        ticket=TICKET,
        cuit=CUIT,
        point_of_sale=POINT_OF_SALE,
        voucher_type=VoucherType.INVOICE_B,
        voucher_number=NEXT_NUMBER,
    )


def test_a_client_error_status_is_not_ambiguous_and_is_not_consulted(
    invoice_b: VoucherRequest,
) -> None:
    transport = FakeTransport([LAST_RESPONSE, HttpStatusError(BAD_REQUEST)])

    with pytest.raises(HttpStatusError):
        _client(transport).authorize(invoice_b)

    assert _actions(transport) == ["FECompUltimoAutorizado", "FECAESolicitar"]


def test_a_request_that_never_left_is_raised_untouched_for_the_caller_to_retry(
    invoice_b: VoucherRequest,
) -> None:
    transport = FakeTransport([LAST_RESPONSE, RequestNotSentError()])

    with pytest.raises(RequestNotSentError):
        _client(transport).authorize(invoice_b)

    assert _actions(transport) == ["FECompUltimoAutorizado", "FECAESolicitar"]


def test_a_voucher_arca_does_not_have_is_reported_without_sending_again_or_renumbering(
    invoice_b: VoucherRequest,
) -> None:
    transport = FakeTransport([LAST_RESPONSE, ResponseLostError(), NOT_FOUND])

    with pytest.raises(VoucherNotAuthorizedError) as error:
        _client(transport).authorize(invoice_b)

    assert error.value.voucher_number == NEXT_NUMBER
    assert error.value.point_of_sale == POINT_OF_SALE
    assert error.value.voucher_type == VoucherType.INVOICE_B
    assert isinstance(error.value.__cause__, ResponseLostError)
    assert _actions(transport).count("FECAESolicitar") == 1


def test_a_voucher_of_another_issuer_under_the_number_is_a_conflict(
    invoice_b: VoucherRequest,
) -> None:
    other_total = CONSULTED.replace(b"<ImpTotal>121<", b"<ImpTotal>999<")
    transport = FakeTransport([LAST_RESPONSE, ResponseLostError(), other_total])

    with pytest.raises(VoucherNumberTakenError) as error:
        _client(transport).authorize(invoice_b)

    assert error.value.differences == (VoucherConflictField.TOTAL,)


@pytest.mark.parametrize(
    "consult_failure",
    [
        ResponseLostError(),
        RequestNotSentError(),
        HttpStatusError(BAD_GATEWAY),
        FAULT,
        b"<malformed/>",
        NOT_FOUND.replace(b">602<", b">600<"),
    ],
    ids=["lost", "not-sent", "http-5xx", "fault", "malformed", "inconclusive"],
)
def test_a_failed_consultation_reports_what_to_reconcile_later(
    invoice_b: VoucherRequest, consult_failure: bytes | Exception
) -> None:
    transport = FakeTransport([LAST_RESPONSE, ResponseLostError(), consult_failure])

    with pytest.raises(RecoveryFailedError) as error:
        _client(transport).authorize(invoice_b)

    assert error.value.point_of_sale == POINT_OF_SALE
    assert error.value.voucher_type == VoucherType.INVOICE_B
    assert error.value.voucher_number == NEXT_NUMBER
    assert error.value.__cause__ is not None
    assert _actions(transport).count("FECAESolicitar") == 1
