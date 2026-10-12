import re
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import override
from zoneinfo import ZoneInfo

import pytest
from lxml import etree

from pyarca.core.wsaa import (
    MAX_UNIQUE_ID,
    AccessTicket,
    MalformedResponseError,
    NaiveTimeError,
    ResponseDefect,
    Service,
    UniqueIdOutOfRangeError,
    WsaaFaultCode,
    WsaaFaultError,
    build_login_cms_request,
    build_login_ticket_request,
    parse_login_cms_response,
)

BUENOS_AIRES = timezone(timedelta(hours=-3))
FIXTURES = Path(__file__).parent / "fixtures/wsaa"
# Hand-written from the example in the WSAA technical specification until a homologation
# response is recorded.
LOGIN_CMS_RESPONSE = (FIXTURES / "login_cms_response.xml").read_bytes()
# Shaped after the Apache Axis faults WSAA returns; the code prefix is not in ARCA's documents.
LOGIN_CMS_FAULT = (FIXTURES / "login_cms_fault.xml").read_bytes()


class _UnknownOffset(tzinfo):
    @override
    def utcoffset(self, dt: datetime | None, /) -> timedelta | None:
        return None

    @override
    def dst(self, dt: datetime | None, /) -> timedelta | None:
        return None

    @override
    def tzname(self, dt: datetime | None, /) -> str | None:
        return None


def _with_ticket_value(tag: bytes, value: bytes) -> bytes:
    return re.sub(
        rb"(&lt;" + tag + rb"&gt;)[^&]*(&lt;/" + tag + rb"&gt;)",
        lambda match: match[1] + value + match[2],
        LOGIN_CMS_RESPONSE,
    )


def test_login_ticket_request_asks_for_the_service_in_a_window_around_now() -> None:
    request = build_login_ticket_request(
        service=Service.WSFE,
        unique_id=4325399,
        now=datetime(2026, 9, 24, 21, 0, tzinfo=BUENOS_AIRES),
    )

    assert request == (
        b"<?xml version='1.0' encoding='UTF-8'?>\n"
        b'<loginTicketRequest version="1.0">'
        b"<header>"
        b"<uniqueId>4325399</uniqueId>"
        b"<generationTime>2026-09-24T23:50:00+00:00</generationTime>"
        b"<expirationTime>2026-09-25T00:10:00+00:00</expirationTime>"
        b"</header>"
        b"<service>wsfe</service>"
        b"</loginTicketRequest>"
    )


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 9, 24, 21, 0),  # noqa: DTZ001
        datetime(2026, 9, 24, 21, 0, tzinfo=_UnknownOffset()),
    ],
    ids=["no timezone", "timezone without offset"],
)
def test_login_ticket_request_rejects_a_time_without_offset(now: datetime) -> None:
    with pytest.raises(NaiveTimeError):
        build_login_ticket_request(service=Service.WSFE, unique_id=4325399, now=now)


@pytest.mark.parametrize("unique_id", [-1, 2**32])
def test_login_ticket_request_rejects_an_id_outside_32_bits(unique_id: int) -> None:
    with pytest.raises(UniqueIdOutOfRangeError):
        build_login_ticket_request(
            service=Service.WSFE,
            unique_id=unique_id,
            now=datetime(2026, 9, 24, 21, 0, tzinfo=BUENOS_AIRES),
        )


@pytest.mark.parametrize("unique_id", [0, MAX_UNIQUE_ID])
def test_login_ticket_request_accepts_the_edges_of_the_32_bit_range(unique_id: int) -> None:
    request = build_login_ticket_request(
        service=Service.WSFE,
        unique_id=unique_id,
        now=datetime(2026, 9, 24, 21, 0, tzinfo=BUENOS_AIRES),
    )

    assert f"<uniqueId>{unique_id}</uniqueId>".encode() in request


def test_login_ticket_request_window_is_measured_in_real_time_across_a_dst_change() -> None:
    now = datetime(2026, 3, 8, 3, 5, tzinfo=ZoneInfo("America/New_York"))

    request = etree.fromstring(
        build_login_ticket_request(service=Service.WSFE, unique_id=4325399, now=now)
    )

    generation = datetime.fromisoformat(request.findtext("header/generationTime", default=""))
    expiration = datetime.fromisoformat(request.findtext("header/expirationTime", default=""))
    assert now - generation == timedelta(minutes=10)
    assert expiration - now == timedelta(minutes=10)


def test_login_cms_request_carries_the_signed_request_in_base64() -> None:
    assert build_login_cms_request(b"signed") == (
        b"<?xml version='1.0' encoding='UTF-8'?>\n"
        b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
        b' xmlns:wsaa="http://wsaa.view.sua.dvadac.desein.afip.gov">'
        b"<soapenv:Body>"
        b"<wsaa:loginCms>"
        b"<wsaa:in0>c2lnbmVk</wsaa:in0>"
        b"</wsaa:loginCms>"
        b"</soapenv:Body>"
        b"</soapenv:Envelope>"
    )


def test_login_cms_response_becomes_an_access_ticket() -> None:
    assert parse_login_cms_response(LOGIN_CMS_RESPONSE) == AccessTicket(
        token="cES0SSuWIIPlfe5/dLtb0Qeg2jQuvYuuSEDOrz+w2EnAQiEeS86gzYf7ehiU3UaYit5FRb9z/3zq",
        sign="a6QSSZBgLf0TTcktSNteeSg3qXsMVjo/F5py/Gtw7xucTrUWbsrVCdIoGE8Cm1bixpuVPlr58k6n",
        expires_at=datetime(2026, 9, 25, 9, 0, 2, 105000, tzinfo=BUENOS_AIRES),
    )


@pytest.mark.parametrize(
    "response",
    [
        LOGIN_CMS_RESPONSE.replace(b"loginCmsReturn", b"somethingElse"),
        LOGIN_CMS_RESPONSE.replace(b"&lt;token&gt;", b"&lt;other&gt;").replace(
            b"&lt;/token&gt;", b"&lt;/other&gt;"
        ),
        _with_ticket_value(b"token", b"  "),
        _with_ticket_value(b"sign", b""),
    ],
    ids=["no ticket", "ticket without token", "blank token", "empty sign"],
)
def test_login_cms_response_without_a_ticket_is_rejected(response: bytes) -> None:
    with pytest.raises(MalformedResponseError) as error:
        parse_login_cms_response(response)

    assert error.value.defect == ResponseDefect.MISSING_ELEMENT


@pytest.mark.parametrize(
    "expiration",
    [b"not a time", b"2026-09-25T09:00:02.105", b""],
    ids=["unparseable", "no offset", "empty"],
)
def test_login_cms_response_with_an_unusable_expiration_is_rejected(expiration: bytes) -> None:
    with pytest.raises(MalformedResponseError) as error:
        parse_login_cms_response(_with_ticket_value(b"expirationTime", expiration))

    assert error.value.element == "header/expirationTime"


def test_access_ticket_repr_hides_the_credentials() -> None:
    ticket = AccessTicket(
        token="secret-token", sign="secret-sign", expires_at=datetime(2026, 9, 25, tzinfo=UTC)
    )

    assert "secret" not in repr(ticket)


def test_login_cms_response_with_a_document_type_declaration_is_rejected(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("private key")
    response = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE envelope [<!ENTITY leak SYSTEM "'
        + secret.as_uri().encode()
        + b'">]>'
        + LOGIN_CMS_RESPONSE.split(b"?>", 1)[1].replace(b"<soapenv:Body>", b"<soapenv:Body>&leak;")
    )

    with pytest.raises(MalformedResponseError) as error:
        parse_login_cms_response(response)

    assert error.value.defect == ResponseDefect.DOCUMENT_TYPE


def test_login_cms_response_cut_short_is_rejected() -> None:
    with pytest.raises(MalformedResponseError) as error:
        parse_login_cms_response(LOGIN_CMS_RESPONSE[:200])

    assert error.value.defect == ResponseDefect.NOT_XML


def test_login_cms_fault_becomes_a_typed_error() -> None:
    with pytest.raises(WsaaFaultError) as error:
        parse_login_cms_response(LOGIN_CMS_FAULT)

    assert error.value.code == WsaaFaultCode.ALREADY_AUTHENTICATED
    assert error.value.description == (
        "El CEE ya posee un TA valido para el acceso al WSN solicitado"
    )
