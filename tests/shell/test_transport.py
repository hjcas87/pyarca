from http import HTTPStatus

import httpx
import pytest

from pyarca.shell.endpoints import WSAA_ENDPOINTS, Environment
from pyarca.shell.transport import (
    HttpStatusError,
    HttpxTransport,
    RequestNotSentError,
    ResponseLostError,
)

URL = WSAA_ENDPOINTS[Environment.HOMOLOGATION]


def test_endpoints_point_each_environment_to_its_wsaa() -> None:
    assert WSAA_ENDPOINTS == {
        Environment.HOMOLOGATION: "https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
        Environment.PRODUCTION: "https://wsaa.afip.gov.ar/ws/services/LoginCms",
    }


def test_transport_posts_the_soap_body_and_returns_the_response_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"<response/>")

    response = HttpxTransport(transport=httpx.MockTransport(handler)).post(
        url=URL, body=b"<request/>"
    )

    assert response == b"<response/>"
    (request,) = seen
    assert str(request.url) == URL
    assert request.content == b"<request/>"
    assert request.headers["content-type"] == "text/xml; charset=utf-8"
    assert request.headers["soapaction"] == '""'


def test_transport_returns_the_body_of_a_soap_fault() -> None:
    transport = HttpxTransport(
        transport=httpx.MockTransport(lambda _: httpx.Response(500, content=b"<fault/>"))
    )

    assert transport.post(url=URL, body=b"<request/>") == b"<fault/>"


def test_transport_reports_an_unexpected_status() -> None:
    transport = HttpxTransport(
        transport=httpx.MockTransport(lambda _: httpx.Response(HTTPStatus.SERVICE_UNAVAILABLE))
    )

    with pytest.raises(HttpStatusError) as error:
        transport.post(url=URL, body=b"<request/>")

    assert error.value.status_code == HTTPStatus.SERVICE_UNAVAILABLE


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.ConnectError("refused"), RequestNotSentError),
        (httpx.ConnectTimeout("slow"), RequestNotSentError),
        (httpx.ReadTimeout("slow"), ResponseLostError),
        (httpx.RemoteProtocolError("dropped"), ResponseLostError),
    ],
)
def test_transport_tells_a_request_never_sent_from_a_lost_response(
    failure: httpx.TransportError, expected: type[Exception]
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise failure

    transport = HttpxTransport(transport=httpx.MockTransport(handler))

    with pytest.raises(expected):
        transport.post(url=URL, body=b"<request/>")
