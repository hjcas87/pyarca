from datetime import datetime, timedelta, timezone

import pytest

from pyarca.core.wsaa import (
    NaiveTimeError,
    Service,
    UniqueIdOutOfRangeError,
    build_login_ticket_request,
)

BUENOS_AIRES = timezone(timedelta(hours=-3))


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
        b"<generationTime>2026-09-24T20:50:00-03:00</generationTime>"
        b"<expirationTime>2026-09-24T21:10:00-03:00</expirationTime>"
        b"</header>"
        b"<service>wsfe</service>"
        b"</loginTicketRequest>"
    )


def test_login_ticket_request_rejects_a_time_without_offset() -> None:
    with pytest.raises(NaiveTimeError):
        build_login_ticket_request(
            service=Service.WSFE,
            unique_id=4325399,
            now=datetime(2026, 9, 24, 21, 0),  # noqa: DTZ001
        )


@pytest.mark.parametrize("unique_id", [-1, 2**32])
def test_login_ticket_request_rejects_an_id_outside_32_bits(unique_id: int) -> None:
    with pytest.raises(UniqueIdOutOfRangeError):
        build_login_ticket_request(
            service=Service.WSFE,
            unique_id=unique_id,
            now=datetime(2026, 9, 24, 21, 0, tzinfo=BUENOS_AIRES),
        )
