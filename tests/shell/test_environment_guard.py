from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pyarca.shell.endpoints import Environment
from pyarca.shell.environment_guard import (
    CertificateEnvironmentMismatchError,
    check_certificate_environment,
    is_homologation_issuer,
    issuer_of,
)
from pyarca.shell.signer import CmsSigner


def test_a_homologation_certificate_is_recognized_by_its_issuer(
    homologation_certificate: x509.Certificate, certificate: x509.Certificate
) -> None:
    assert is_homologation_issuer(issuer_of(homologation_certificate))
    assert not is_homologation_issuer(issuer_of(certificate))


def test_the_issuer_must_match_exactly_not_just_contain_the_homologation_names(
    homologation_certificate: x509.Certificate,
) -> None:
    issuer = dict(issuer_of(homologation_certificate))
    issuer[x509.oid.NameOID.ORGANIZATIONAL_UNIT_NAME] = "extra"

    assert not is_homologation_issuer(issuer)


@pytest.mark.parametrize(
    ("homologation", "environment", "allowed"),
    [
        (True, Environment.HOMOLOGATION, True),
        (True, Environment.PRODUCTION, False),
        (False, Environment.HOMOLOGATION, False),
        (False, Environment.PRODUCTION, True),
    ],
)
def test_a_certificate_is_only_used_with_the_environment_it_belongs_to(
    homologation_certificate: x509.Certificate,
    certificate: x509.Certificate,
    homologation: bool,  # noqa: FBT001
    environment: Environment,
    allowed: bool,  # noqa: FBT001
) -> None:
    issuer = issuer_of(homologation_certificate if homologation else certificate)

    if allowed:
        check_certificate_environment(issuer, environment)
        return
    with pytest.raises(CertificateEnvironmentMismatchError) as error:
        check_certificate_environment(issuer, environment)
    assert error.value.environment == environment
    assert error.value.issuer in {"Computadores Test, AFIP, AR", "test signer"}


def test_the_signer_exposes_the_issuer_of_its_certificate(
    tmp_path: Path, homologation_certificate: x509.Certificate, private_key_path: Path
) -> None:
    certificate_path = tmp_path / "homologation.crt"
    certificate_path.write_bytes(homologation_certificate.public_bytes(serialization.Encoding.PEM))

    signer = CmsSigner.from_pem_files(
        certificate_path=certificate_path, private_key_path=private_key_path
    )

    assert signer.issuer == issuer_of(homologation_certificate)
