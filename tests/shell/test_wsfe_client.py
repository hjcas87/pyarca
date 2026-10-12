from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pyarca.core.voucher import VoucherRequest
from pyarca.core.wsaa import AccessTicket, Service
from pyarca.core.wsfe import (
    AuthorizationResult,
    build_authorize_request,
    build_last_authorized_request,
)
from pyarca.core.wsfe_codes import VoucherType
from pyarca.shell.endpoints import WSFE_ENDPOINTS, Environment
from pyarca.shell.transport import ResponseLostError
from pyarca.shell.wsfe_client import (
    ArcaErrorsError,
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


def test_a_lost_response_is_not_retried_nor_renumbered(invoice_b: VoucherRequest) -> None:
    transport = FakeTransport([LAST_RESPONSE, ResponseLostError()])

    with pytest.raises(ResponseLostError):
        _client(transport).authorize(invoice_b)

    assert [action for _, _, action in transport.posts] == [
        f"{ACTION_PREFIX}FECompUltimoAutorizado",
        f"{ACTION_PREFIX}FECAESolicitar",
    ]
