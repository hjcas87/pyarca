from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

RSA_PUBLIC_EXPONENT = 65537
RSA_KEY_SIZE = 2048
CERTIFICATE_VALID_FROM = datetime(2026, 1, 1, tzinfo=UTC)
CERTIFICATE_VALID_UNTIL = datetime(2036, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=RSA_PUBLIC_EXPONENT, key_size=RSA_KEY_SIZE)


@pytest.fixture(scope="session")
def certificate(rsa_key: rsa.RSAPrivateKey) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test signer")])
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(rsa_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(CERTIFICATE_VALID_FROM)
        .not_valid_after(CERTIFICATE_VALID_UNTIL)
        .sign(rsa_key, hashes.SHA256())
    )


@pytest.fixture
def certificate_path(tmp_path: Path, certificate: x509.Certificate) -> Path:
    path = tmp_path / "certificate.crt"
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return path


@pytest.fixture
def private_key_path(tmp_path: Path, rsa_key: rsa.RSAPrivateKey) -> Path:
    path = tmp_path / "private.key"
    path.write_bytes(
        rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


@pytest.fixture
def elliptic_key_path(tmp_path: Path) -> Path:
    path = tmp_path / "elliptic.key"
    path.write_bytes(
        ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path
