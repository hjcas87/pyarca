import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID

from pyarca.shell.endpoints import WSAA_ENDPOINTS, WSFE_ENDPOINTS, Environment
from pyarca.shell.environment_guard import is_homologation_issuer, issuer_of
from pyarca.shell.signer import CmsSigner
from pyarca.shell.token_store import FileTokenStore
from pyarca.shell.transport import HttpxTransport

CERTIFICATE_ENV = "PYARCA_HOMOLOGATION_CERTIFICATE"
PRIVATE_KEY_ENV = "PYARCA_HOMOLOGATION_PRIVATE_KEY"
CUIT_ENV = "PYARCA_HOMOLOGATION_CUIT"
STATE_DIRECTORY = Path(__file__).parents[2] / ".homologation"

# Spelled out on purpose: a homologation run must fail if these constants are ever changed.
HOMOLOGATION_WSAA_URL = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms"
HOMOLOGATION_WSFE_URL = "https://wswhomo.afip.gov.ar/wsfev1/service.asmx"
HOMOLOGATION_URLS = frozenset({HOMOLOGATION_WSAA_URL, HOMOLOGATION_WSFE_URL})


@dataclass(frozen=True)
class HomologationIdentity:
    signer: CmsSigner
    cuit: int


@dataclass
class GuardedTransport:
    """Sends only to the homologation services and keeps every exchange for inspection."""

    inner: HttpxTransport
    exchanges: list[tuple[str, str, bytes, bytes]] = field(default_factory=list)

    def post(self, *, url: str, body: bytes, soap_action: str) -> bytes:
        if url not in HOMOLOGATION_URLS:
            pytest.fail(f"refusing to contact {url}: not a homologation service")
        response = self.inner.post(url=url, body=body, soap_action=soap_action)
        self.exchanges.append((url, soap_action, body, response))
        return response

    def close(self) -> None:
        self.inner.close()


def _subject_names_cuit(certificate: x509.Certificate, cuit: str) -> bool:
    serial_numbers = certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
    return any(cuit in str(attribute.value) for attribute in serial_numbers)


@pytest.fixture
def identity() -> HomologationIdentity:
    certificate_path = os.environ.get(CERTIFICATE_ENV)
    private_key_path = os.environ.get(PRIVATE_KEY_ENV)
    cuit = os.environ.get(CUIT_ENV)
    if not certificate_path or not private_key_path or not cuit:
        pytest.skip(f"{CERTIFICATE_ENV}, {PRIVATE_KEY_ENV} and {CUIT_ENV} must be set")
    certificate = x509.load_pem_x509_certificate(Path(certificate_path).read_bytes())
    if not is_homologation_issuer(issuer_of(certificate)):
        pytest.fail("refusing to contact ARCA: the certificate is not from the homologation CA")
    assert _subject_names_cuit(certificate, cuit)
    assert WSAA_ENDPOINTS[Environment.HOMOLOGATION] == HOMOLOGATION_WSAA_URL
    assert WSFE_ENDPOINTS[Environment.HOMOLOGATION] == HOMOLOGATION_WSFE_URL
    signer = CmsSigner.from_pem_files(
        certificate_path=Path(certificate_path), private_key_path=Path(private_key_path)
    )
    return HomologationIdentity(signer=signer, cuit=int(cuit))


@pytest.fixture
def token_store() -> FileTokenStore:
    return FileTokenStore(STATE_DIRECTORY / "tickets")


@pytest.fixture
def transport() -> Iterator[GuardedTransport]:
    guarded = GuardedTransport(inner=HttpxTransport())
    yield guarded
    guarded.close()
