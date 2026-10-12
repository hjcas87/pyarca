"""HTTP transport for ARCA's SOAP services."""

from http import HTTPStatus

import httpx

from pyarca.shell.ports import Transport

CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 30.0
WRITE_TIMEOUT_SECONDS = 10.0
POOL_TIMEOUT_SECONDS = 10.0

SOAP_CONTENT_TYPE = "text/xml; charset=utf-8"
EMPTY_SOAP_ACTION = '""'

# SOAP 1.1 carries faults in the body of a 500 response.
SOAP_ANSWER_STATUSES = frozenset({HTTPStatus.OK, HTTPStatus.INTERNAL_SERVER_ERROR})


class HttpStatusError(Exception):
    """The server answered with a status that carries no SOAP message."""

    def __init__(self, status_code: int) -> None:
        """Build the error for the received status."""
        super().__init__(f"unexpected HTTP status {status_code}")
        self.status_code = status_code


class RequestNotSentError(Exception):
    """The connection failed before the request reached the server; trying again is safe."""


class ResponseLostError(Exception):
    """The request was sent but no answer arrived, so the server may have acted on it."""


class HttpxTransport(Transport):
    """Synchronous transport over httpx."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        """Build the HTTP client; `transport` replaces the network layer, mainly for tests."""
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
                write=WRITE_TIMEOUT_SECONDS,
                pool=POOL_TIMEOUT_SECONDS,
            ),
        )

    def post(self, *, url: str, body: bytes) -> bytes:
        """Post `body` to `url` and return the body of the answer, including SOAP faults.

        Raises:
            RequestNotSentError: If the connection could not be established.
            ResponseLostError: If the request was sent and the answer never arrived.
            HttpStatusError: If the status is neither 200 nor a SOAP fault's 500.
        """
        try:
            response = self._client.post(
                url,
                content=body,
                headers={"Content-Type": SOAP_CONTENT_TYPE, "SOAPAction": EMPTY_SOAP_ACTION},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise RequestNotSentError from error
        except httpx.TransportError as error:
            raise ResponseLostError from error
        if response.status_code not in SOAP_ANSWER_STATUSES:
            raise HttpStatusError(response.status_code)
        return response.content
