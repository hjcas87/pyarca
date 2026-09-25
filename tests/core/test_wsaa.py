from datetime import datetime, timedelta, timezone, tzinfo
from typing import override
from zoneinfo import ZoneInfo

import pytest
from lxml import etree

from pyarca.core.wsaa import (
    MAX_UNIQUE_ID,
    NaiveTimeError,
    Service,
    UniqueIdOutOfRangeError,
    build_login_ticket_request,
)

BUENOS_AIRES = timezone(timedelta(hours=-3))


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
