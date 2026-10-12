from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pyarca.core.wsaa import (
    AccessTicket,
    Service,
    WsaaFaultCode,
    WsaaFaultError,
    build_login_cms_request,
    build_login_ticket_request,
)
from pyarca.shell.clock import SystemClock
from pyarca.shell.endpoints import WSAA_ENDPOINTS, Environment
from pyarca.shell.token_store import InMemoryTokenStore, TicketKey
from pyarca.shell.wsaa_client import TICKET_SAFETY_MARGIN, WsaaClient

FIXTURES = Path(__file__).parent.parent / "core/fixtures/wsaa"
LOGIN_CMS_RESPONSE = (FIXTURES / "login_cms_response.xml").read_bytes()
LOGIN_CMS_FAULT = (FIXTURES / "login_cms_fault.xml").read_bytes()
TICKET_EXPIRATION = datetime(2026, 9, 25, 12, 0, 2, 105000, tzinfo=UTC)
NOW = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
CERTIFICATE_ID = "certificate-1"
KEY = TicketKey(
    certificate_id=CERTIFICATE_ID, service=Service.WSFE, environment=Environment.HOMOLOGATION
)
STORED_TICKET = AccessTicket(
    token="stored-token", sign="stored-sign", expires_at=NOW + timedelta(hours=6)
)


@dataclass
class FakeSigner:
    certificate_id: str = CERTIFICATE_ID

    def sign(self, data: bytes) -> bytes:
        return b"signed:" + data


@dataclass
class FakeClock:
    current: datetime = NOW

    def now(self) -> datetime:
        return self.current


@dataclass
class FakeTransport:
    response: bytes
    posts: list[tuple[str, bytes]] = field(default_factory=list)
    on_post: list[AccessTicket] = field(default_factory=list)
    store: InMemoryTokenStore | None = None

    def post(self, *, url: str, body: bytes) -> bytes:
        self.posts.append((url, body))
        if self.store is not None and self.on_post:
            self.store.save(KEY, self.on_post[0])
        return self.response


def _client(
    transport: FakeTransport, store: InMemoryTokenStore, clock: FakeClock | None = None
) -> WsaaClient:
    return WsaaClient(
        signer=FakeSigner(),
        transport=transport,
        clock=clock or FakeClock(),
        token_store=store,
        environment=Environment.HOMOLOGATION,
    )


def test_login_signs_the_request_sends_it_and_stores_the_ticket() -> None:
    transport = FakeTransport(response=LOGIN_CMS_RESPONSE)
    store = InMemoryTokenStore()

    ticket = _client(transport, store).get_access_ticket(Service.WSFE)

    signed_request = FakeSigner().sign(
        build_login_ticket_request(service=Service.WSFE, unique_id=int(NOW.timestamp()), now=NOW)
    )
    assert transport.posts == [
        (WSAA_ENDPOINTS[Environment.HOMOLOGATION], build_login_cms_request(signed_request))
    ]
    assert ticket.expires_at == TICKET_EXPIRATION
    assert store.get(KEY) == ticket


def test_a_stored_ticket_that_is_still_valid_is_reused_without_logging_in() -> None:
    transport = FakeTransport(response=LOGIN_CMS_RESPONSE)
    store = InMemoryTokenStore()
    store.save(KEY, STORED_TICKET)

    assert _client(transport, store).get_access_ticket(Service.WSFE) == STORED_TICKET
    assert transport.posts == []


def test_a_ticket_inside_the_safety_margin_is_replaced() -> None:
    transport = FakeTransport(response=LOGIN_CMS_RESPONSE)
    store = InMemoryTokenStore()
    store.save(KEY, AccessTicket(token="old", sign="old", expires_at=NOW + TICKET_SAFETY_MARGIN))

    ticket = _client(transport, store).get_access_ticket(Service.WSFE)

    assert ticket.expires_at == TICKET_EXPIRATION
    assert len(transport.posts) == 1


def test_a_fault_is_raised_and_nothing_is_stored() -> None:
    transport = FakeTransport(
        response=LOGIN_CMS_FAULT.replace(b"alreadyAuthenticated", b"notAuthorized")
    )
    store = InMemoryTokenStore()

    with pytest.raises(WsaaFaultError) as error:
        _client(transport, store).get_access_ticket(Service.WSFE)

    assert error.value.code == WsaaFaultCode.NOT_AUTHORIZED
    assert store.get(KEY) is None
    assert len(transport.posts) == 1


def test_already_authenticated_uses_the_ticket_another_process_saved() -> None:
    store = InMemoryTokenStore()
    transport = FakeTransport(response=LOGIN_CMS_FAULT, on_post=[STORED_TICKET], store=store)

    assert _client(transport, store).get_access_ticket(Service.WSFE) == STORED_TICKET
    assert len(transport.posts) == 1


def test_already_authenticated_without_a_stored_ticket_is_raised() -> None:
    transport = FakeTransport(response=LOGIN_CMS_FAULT)

    with pytest.raises(WsaaFaultError) as error:
        _client(transport, InMemoryTokenStore()).get_access_ticket(Service.WSFE)

    assert error.value.code == WsaaFaultCode.ALREADY_AUTHENTICATED
    assert len(transport.posts) == 1


def test_stored_tickets_are_scoped_by_certificate_service_and_environment() -> None:
    store = InMemoryTokenStore()
    store.save(KEY, STORED_TICKET)

    other_certificate = TicketKey(
        certificate_id="other", service=KEY.service, environment=KEY.environment
    )
    other_environment = TicketKey(
        certificate_id=CERTIFICATE_ID, service=KEY.service, environment=Environment.PRODUCTION
    )
    assert store.get(other_certificate) is None
    assert store.get(other_environment) is None


def test_the_system_clock_returns_an_aware_time() -> None:
    assert SystemClock().now().utcoffset() is not None
