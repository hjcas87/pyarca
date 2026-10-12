"""Authorize vouchers with WSFE; no call is ever repeated on its own (ADR 0004)."""

from http import HTTPStatus

from pyarca.core.recovery import (
    ConsultationInconclusiveError,
    NotAuthorized,
    resolve_ambiguous,
)
from pyarca.core.soap import MalformedResponseError, SoapFaultError
from pyarca.core.voucher import VoucherRequest
from pyarca.core.wsaa import AccessTicket, Service
from pyarca.core.wsfe import (
    ArcaMessage,
    AuthorizationResult,
    VoucherAuthorization,
    WsfeOperation,
    build_authorize_request,
    build_consult_request,
    build_last_authorized_request,
    parse_authorize_response,
    parse_consult_response,
    parse_last_authorized_response,
    soap_action,
)
from pyarca.core.wsfe_codes import ArcaErrorCode, VoucherType
from pyarca.shell.endpoints import WSFE_ENDPOINTS, Environment
from pyarca.shell.ports import TicketProvider, Transport
from pyarca.shell.transport import HttpStatusError, RequestNotSentError, ResponseLostError

CONSULTATION_FAILURES = (
    RequestNotSentError,
    ResponseLostError,
    HttpStatusError,
    SoapFaultError,
    MalformedResponseError,
    ConsultationInconclusiveError,
)


class ArcaErrorsError(Exception):
    """ARCA answered with errors instead of a result."""

    def __init__(self, errors: tuple[ArcaMessage, ...]) -> None:
        """Build the error from the codes and messages ARCA returned."""
        super().__init__(", ".join(str(message.code) for message in errors))
        self.errors = errors


class VoucherNumberMismatchError(Exception):
    """ARCA refused the voucher (error 10016): its number or date does not follow the last one.

    pyarca does not renumber: the caller may already have stored or printed the number.
    """

    def __init__(self, *, arca_message: str, last_authorized_number: int) -> None:
        """Build the error from ARCA's wording and the last number ARCA reports as authorized."""
        super().__init__(arca_message)
        self.arca_message = arca_message
        self.last_authorized_number = last_authorized_number


class VoucherOutcomeError(Exception):
    """A voucher sent to ARCA, named by point of sale, type and number, whose outcome is told."""

    def __init__(
        self, *, point_of_sale: int, voucher_type: VoucherType, voucher_number: int
    ) -> None:
        """Build the error naming the voucher."""
        super().__init__(f"{point_of_sale}-{voucher_type.name}-{voucher_number}")
        self.point_of_sale = point_of_sale
        self.voucher_type = voucher_type
        self.voucher_number = voucher_number


class VoucherNotAuthorizedError(VoucherOutcomeError):
    """ARCA has no voucher under the number: the request was not authorized.

    Authorizing the same voucher again is safe and gets the same number.
    """


class RecoveryFailedError(VoucherOutcomeError):
    """The outcome of a sent authorization is unknown and could not be looked up.

    The caller must reconcile the named voucher later, with `FECompConsultar`, and must not
    renumber in the meantime.
    """


class WsfeClient:
    """Asks WSFE for the last authorized voucher and authorizes the next one."""

    def __init__(
        self,
        *,
        ticket_provider: TicketProvider,
        transport: Transport,
        environment: Environment,
        cuit: int,
    ) -> None:
        """Wire the ports the calls need; `cuit` is the issuer's."""
        self._ticket_provider = ticket_provider
        self._transport = transport
        self._environment = environment
        self._cuit = cuit

    def last_authorized(self, *, point_of_sale: int, voucher_type: VoucherType) -> int:
        """Return the number of the last voucher ARCA authorized for the point of sale and type.

        Raises:
            ArcaErrorsError: If ARCA answers with errors.
        """
        response = self._transport.post(
            url=WSFE_ENDPOINTS[self._environment],
            body=build_last_authorized_request(
                ticket=self._ticket_provider.get_access_ticket(Service.WSFE),
                cuit=self._cuit,
                point_of_sale=point_of_sale,
                voucher_type=voucher_type,
            ),
            soap_action=soap_action(WsfeOperation.LAST_AUTHORIZED),
        )
        last = parse_last_authorized_response(response)
        if last.errors:
            raise ArcaErrorsError(last.errors)
        return last.voucher_number

    def authorize(self, voucher: VoucherRequest) -> VoucherAuthorization:
        """Authorize `voucher` under the number after the last authorized one, sending it once.

        A rejection that ARCA explains through observations is returned, not raised; only
        `result` says whether the voucher is authorized.

        Raises:
            VoucherNumberMismatchError: If ARCA answers 10016.
            ArcaErrorsError: If ARCA answers with any other error.
            RequestNotSentError: If the connection failed before the request left; sending it
                again is safe.
            VoucherNotAuthorizedError: If the outcome was ambiguous and ARCA has no such voucher.
            VoucherNumberTakenError: If the outcome was ambiguous and ARCA has another voucher
                under the number.
            RecoveryFailedError: If the outcome was ambiguous and the consultation failed too.
        """
        number = (
            self.last_authorized(
                point_of_sale=voucher.point_of_sale, voucher_type=voucher.voucher_type
            )
            + 1
        )
        ticket = self._ticket_provider.get_access_ticket(Service.WSFE)
        authorization = self._submit(voucher, number=number, ticket=ticket)
        if authorization.result == AuthorizationResult.APPROVED:
            return authorization
        self._raise_out_of_sequence(authorization, voucher)
        if authorization.errors:
            raise ArcaErrorsError(authorization.errors)
        return authorization

    def _submit(
        self, voucher: VoucherRequest, *, number: int, ticket: AccessTicket
    ) -> VoucherAuthorization:
        try:
            response = self._transport.post(
                url=WSFE_ENDPOINTS[self._environment],
                body=build_authorize_request(
                    ticket=ticket, cuit=self._cuit, voucher=voucher, voucher_number=number
                ),
                soap_action=soap_action(WsfeOperation.AUTHORIZE),
            )
            return parse_authorize_response(response)
        except (ResponseLostError, SoapFaultError, MalformedResponseError) as error:
            return self._recover(voucher, number=number, ticket=ticket, cause=error)
        except HttpStatusError as error:
            if error.status_code < HTTPStatus.INTERNAL_SERVER_ERROR:
                raise
            return self._recover(voucher, number=number, ticket=ticket, cause=error)

    def _recover(
        self, voucher: VoucherRequest, *, number: int, ticket: AccessTicket, cause: Exception
    ) -> VoucherAuthorization:
        try:
            response = self._transport.post(
                url=WSFE_ENDPOINTS[self._environment],
                body=build_consult_request(
                    ticket=ticket,
                    cuit=self._cuit,
                    point_of_sale=voucher.point_of_sale,
                    voucher_type=voucher.voucher_type,
                    voucher_number=number,
                ),
                soap_action=soap_action(WsfeOperation.CONSULT),
            )
            resolution = resolve_ambiguous(voucher, number, parse_consult_response(response))
        except CONSULTATION_FAILURES as error:
            raise RecoveryFailedError(
                point_of_sale=voucher.point_of_sale,
                voucher_type=voucher.voucher_type,
                voucher_number=number,
            ) from error
        if isinstance(resolution, NotAuthorized):
            raise VoucherNotAuthorizedError(
                point_of_sale=voucher.point_of_sale,
                voucher_type=voucher.voucher_type,
                voucher_number=number,
            ) from cause
        return resolution

    def _raise_out_of_sequence(
        self, authorization: VoucherAuthorization, voucher: VoucherRequest
    ) -> None:
        out_of_sequence = next(
            (
                message
                for message in (*authorization.errors, *authorization.observations)
                if message.code == ArcaErrorCode.VOUCHER_OUT_OF_SEQUENCE
            ),
            None,
        )
        if out_of_sequence is None:
            return
        raise VoucherNumberMismatchError(
            arca_message=out_of_sequence.message,
            last_authorized_number=self.last_authorized(
                point_of_sale=voucher.point_of_sale, voucher_type=voucher.voucher_type
            ),
        )
