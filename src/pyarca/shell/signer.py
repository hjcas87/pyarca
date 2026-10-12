"""CMS signing of the login ticket request with the taxpayer's certificate."""

from pathlib import Path
from typing import Self

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7

from pyarca.shell.environment_guard import CertificateIssuer, issuer_of
from pyarca.shell.ports import Signer

# The WSAA specification (1.2.2) names SHA-1 with RSA, but `cryptography` refuses SHA-1 in PKCS7.
SIGNATURE_HASH = hashes.SHA256()


class UnsupportedKeyError(ValueError):
    """The private key is not an RSA key, the only kind ARCA certificates use."""

    def __init__(self, key_type: type) -> None:
        """Build the error naming the type of the rejected key."""
        super().__init__(f"expected an RSA private key, got {key_type.__name__}")


class CmsSigner(Signer):
    """Signs data as an attached CMS structure with an RSA key."""

    def __init__(
        self,
        *,
        certificate: x509.Certificate,
        private_key: rsa.RSAPrivateKey,
    ) -> None:
        """Hold the certificate and key that sign every request."""
        self._certificate = certificate
        self._private_key = private_key

    @classmethod
    def from_pem_files(
        cls,
        *,
        certificate_path: Path,
        private_key_path: Path,
    ) -> Self:
        """Load an unencrypted PEM certificate and RSA private key.

        Raises:
            UnsupportedKeyError: If the private key is not RSA.
        """
        certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
        private_key = serialization.load_pem_private_key(
            private_key_path.read_bytes(), password=None
        )
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise UnsupportedKeyError(type(private_key))
        return cls(certificate=certificate, private_key=private_key)

    @property
    def certificate_id(self) -> str:
        """Return the SHA-256 fingerprint of the certificate, in hex."""
        return self._certificate.fingerprint(hashes.SHA256()).hex()

    @property
    def issuer(self) -> CertificateIssuer:
        """Return the issuer of the certificate."""
        return issuer_of(self._certificate)

    def sign(self, data: bytes) -> bytes:
        """Return `data` wrapped in a CMS signed structure, DER encoded."""
        return (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(data)
            .add_signer(self._certificate, self._private_key, SIGNATURE_HASH)
            .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
        )
