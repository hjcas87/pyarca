from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs7

from pyarca.shell.signer import CmsSigner, UnsupportedKeyError

SHA256_OID_DER = bytes.fromhex("0609608648016503040201")
DATA = b"<loginTicketRequest/>"


def test_signer_wraps_the_data_in_a_cms_signed_with_sha256(
    certificate_path: Path, private_key_path: Path, certificate: x509.Certificate
) -> None:
    signer = CmsSigner.from_pem_files(
        certificate_path=certificate_path, private_key_path=private_key_path
    )

    signed = signer.sign(DATA)

    assert DATA in signed
    assert pkcs7.load_der_pkcs7_certificates(signed) == [certificate]
    assert SHA256_OID_DER in signed


def test_signer_rejects_a_key_that_is_not_rsa(
    certificate_path: Path, elliptic_key_path: Path
) -> None:
    with pytest.raises(UnsupportedKeyError):
        CmsSigner.from_pem_files(
            certificate_path=certificate_path, private_key_path=elliptic_key_path
        )


def test_signer_identifies_its_certificate_by_fingerprint(
    certificate_path: Path, private_key_path: Path, certificate: x509.Certificate
) -> None:
    signer = CmsSigner.from_pem_files(
        certificate_path=certificate_path, private_key_path=private_key_path
    )

    assert signer.certificate_id == certificate.fingerprint(hashes.SHA256()).hex()
