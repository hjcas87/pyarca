"""Logs in to the real WSAA homologation service. Run with `pytest -m homologation`.

Needs the environment variables named below: PEM files of a homologation certificate and its
CUIT. Nothing is sent unless the certificate was issued by ARCA's homologation CA.
"""

import os
from contextlib import closing
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID

from pyarca.core.wsaa import Service, WsaaFaultCode, WsaaFaultError
from pyarca.shell.clock import SystemClock
from pyarca.shell.endpoints import Environment
from pyarca.shell.signer import CmsSigner
from pyarca.shell.token_store import InMemoryTokenStore
from pyarca.shell.transport import HttpxTransport
from pyarca.shell.wsaa_client import WsaaClient

CERTIFICATE_ENV = "PYARCA_HOMOLOGATION_CERTIFICATE"
PRIVATE_KEY_ENV = "PYARCA_HOMOLOGATION_PRIVATE_KEY"
CUIT_ENV = "PYARCA_HOMOLOGATION_CUIT"
HOMOLOGATION_ISSUER = {
    NameOID.COMMON_NAME: "Computadores Test",
    NameOID.ORGANIZATION_NAME: "AFIP",
    NameOID.COUNTRY_NAME: "AR",
}


def is_homologation_certificate(certificate: x509.Certificate) -> bool:
    issuer = {attribute.oid: attribute.value for attribute in certificate.issuer}
    return issuer == HOMOLOGATION_ISSUER


def subject_names_cuit(certificate: x509.Certificate, cuit: str) -> bool:
    serial_numbers = certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
    return any(cuit in str(attribute.value) for attribute in serial_numbers)


def test_the_guard_refuses_a_certificate_not_issued_by_the_homologation_ca(
    certificate: x509.Certificate,
) -> None:
    assert not is_homologation_certificate(certificate)


@pytest.mark.homologation
def test_login_with_a_homologation_certificate() -> None:
    certificate_path = os.environ.get(CERTIFICATE_ENV)
    private_key_path = os.environ.get(PRIVATE_KEY_ENV)
    cuit = os.environ.get(CUIT_ENV)
    if not certificate_path or not private_key_path or not cuit:
        pytest.skip(f"{CERTIFICATE_ENV}, {PRIVATE_KEY_ENV} and {CUIT_ENV} must be set")
    certificate = x509.load_pem_x509_certificate(Path(certificate_path).read_bytes())
    if not is_homologation_certificate(certificate):
        pytest.fail("refusing to contact ARCA: the certificate is not from the homologation CA")
    assert subject_names_cuit(certificate, cuit)

    with closing(HttpxTransport()) as transport:
        client = WsaaClient(
            signer=CmsSigner.from_pem_files(
                certificate_path=Path(certificate_path), private_key_path=Path(private_key_path)
            ),
            transport=transport,
            clock=SystemClock(),
            token_store=InMemoryTokenStore(),
            environment=Environment.HOMOLOGATION,
        )
        try:
            ticket = client.get_access_ticket(Service.WSFE)
        except WsaaFaultError as error:
            # WSAA only reports this after accepting the signature, so signing is proven either way.
            if error.code != WsaaFaultCode.ALREADY_AUTHENTICATED:
                raise
            return

    assert ticket.token
    assert ticket.sign
    assert ticket.expires_at > SystemClock().now()
