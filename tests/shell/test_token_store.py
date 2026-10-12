import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pyarca.core.wsaa import AccessTicket, Service
from pyarca.shell.endpoints import Environment
from pyarca.shell.token_store import FileTokenStore, StoredTicketError, TicketKey

KEY = TicketKey(
    certificate_id="certificate-1", service=Service.WSFE, environment=Environment.HOMOLOGATION
)
OWNER_ONLY_FILE = 0o600
DISK_FULL = "disk full"
OWNER_ONLY_DIRECTORY = 0o700
TICKET = AccessTicket(
    token="secret-token", sign="secret-sign", expires_at=datetime(2026, 10, 13, 1, 2, 3, tzinfo=UTC)
)


def test_a_saved_ticket_is_read_back_by_another_store_on_the_same_directory(
    tmp_path: Path,
) -> None:
    FileTokenStore(tmp_path / "tickets").save(KEY, TICKET)

    assert FileTokenStore(tmp_path / "tickets").get(KEY) == TICKET


def test_there_is_no_ticket_before_one_is_saved(tmp_path: Path) -> None:
    assert FileTokenStore(tmp_path / "tickets").get(KEY) is None


def test_saving_again_replaces_the_ticket(tmp_path: Path) -> None:
    store = FileTokenStore(tmp_path)
    newer = AccessTicket(token="new", sign="new", expires_at=TICKET.expires_at)

    store.save(KEY, TICKET)
    store.save(KEY, newer)

    assert store.get(KEY) == newer


def test_tickets_are_kept_apart_by_certificate_service_and_environment(tmp_path: Path) -> None:
    store = FileTokenStore(tmp_path)
    store.save(KEY, TICKET)

    other_certificate = TicketKey(
        certificate_id="other", service=KEY.service, environment=KEY.environment
    )
    other_environment = TicketKey(
        certificate_id=KEY.certificate_id, service=KEY.service, environment=Environment.PRODUCTION
    )
    assert store.get(other_certificate) is None
    assert store.get(other_environment) is None


def test_only_the_owner_can_read_the_stored_ticket(tmp_path: Path) -> None:
    directory = tmp_path / "tickets"
    FileTokenStore(directory).save(KEY, TICKET)

    (ticket_file,) = directory.iterdir()
    assert stat.S_IMODE(ticket_file.stat().st_mode) == OWNER_ONLY_FILE
    assert stat.S_IMODE(directory.stat().st_mode) == OWNER_ONLY_DIRECTORY


def test_saving_leaves_no_partial_file_behind(tmp_path: Path) -> None:
    FileTokenStore(tmp_path).save(KEY, TICKET)

    assert [path.suffix for path in tmp_path.iterdir()] == [".json"]


def test_the_file_name_does_not_expose_the_certificate_id(tmp_path: Path) -> None:
    FileTokenStore(tmp_path).save(KEY, TICKET)

    (ticket_file,) = tmp_path.iterdir()
    assert KEY.certificate_id not in ticket_file.name


@pytest.mark.parametrize("content", [b"not json", b"{}", b'{"token": "t", "sign": "s"}'])
def test_an_unreadable_ticket_file_is_reported_instead_of_ignored(
    tmp_path: Path, content: bytes
) -> None:
    store = FileTokenStore(tmp_path)
    store.save(KEY, TICKET)
    (ticket_file,) = tmp_path.iterdir()
    ticket_file.write_bytes(content)

    with pytest.raises(StoredTicketError):
        store.get(KEY)


def test_a_failed_save_leaves_neither_a_partial_ticket_nor_a_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object) -> Path:
        raise OSError(DISK_FULL)

    monkeypatch.setattr(Path, "replace", refuse)

    with pytest.raises(OSError, match=DISK_FULL):
        FileTokenStore(tmp_path).save(KEY, TICKET)

    assert list(tmp_path.iterdir()) == []
