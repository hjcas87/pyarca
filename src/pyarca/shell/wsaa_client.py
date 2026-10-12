"""Login to WSAA, reusing the access ticket while it is valid (ADR 0005)."""

from datetime import datetime, timedelta

from pyarca.core.wsaa import (
    MAX_UNIQUE_ID,
    AccessTicket,
    Service,
    WsaaFaultCode,
    WsaaFaultError,
    build_login_cms_request,
    build_login_ticket_request,
    parse_login_cms_response,
)
from pyarca.shell.endpoints import WSAA_ENDPOINTS, Environment
from pyarca.shell.ports import Clock, Signer, TokenStore, Transport
from pyarca.shell.token_store import TicketKey

# A ticket that expires sooner than this is replaced, so it does not expire while a request
# built with it is in flight.
TICKET_SAFETY_MARGIN = timedelta(minutes=5)

WSAA_SOAP_ACTION = ""


class WsaaClient:
    """Obtains access tickets from WSAA and reuses the ones already stored."""

    def __init__(
        self,
        *,
        signer: Signer,
        transport: Transport,
        clock: Clock,
        token_store: TokenStore,
        environment: Environment,
    ) -> None:
        """Wire the ports the login needs."""
        self._signer = signer
        self._transport = transport
        self._clock = clock
        self._token_store = token_store
        self._environment = environment

    def get_access_ticket(self, service: Service) -> AccessTicket:
        """Return a valid access ticket for `service`, logging in only when needed.

        Raises:
            WsaaFaultError: If WSAA refuses the login. After `coe.alreadyAuthenticated` the store
                is read once more, since another process may have saved the ticket meanwhile.
        """
        key = TicketKey(
            certificate_id=self._signer.certificate_id,
            service=service,
            environment=self._environment,
        )
        stored = self._usable_stored_ticket(key)
        if stored is not None:
            return stored
        try:
            ticket = self._login(service)
        except WsaaFaultError as error:
            if error.code != WsaaFaultCode.ALREADY_AUTHENTICATED:
                raise
            refreshed = self._usable_stored_ticket(key)
            if refreshed is None:
                raise
            return refreshed
        self._token_store.save(key, ticket)
        return ticket

    def _usable_stored_ticket(self, key: TicketKey) -> AccessTicket | None:
        ticket = self._token_store.get(key)
        if ticket is None:
            return None
        if ticket.expires_at - self._clock.now() <= TICKET_SAFETY_MARGIN:
            return None
        return ticket

    def _login(self, service: Service) -> AccessTicket:
        now = self._clock.now()
        request = build_login_ticket_request(service=service, unique_id=_unique_id(now), now=now)
        response = self._transport.post(
            url=WSAA_ENDPOINTS[self._environment],
            body=build_login_cms_request(self._signer.sign(request)),
            soap_action=WSAA_SOAP_ACTION,
        )
        return parse_login_cms_response(response)


def _unique_id(now: datetime) -> int:
    return int(now.timestamp()) % (MAX_UNIQUE_ID + 1)
