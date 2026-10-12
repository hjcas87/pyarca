"""Keeps a certificate from being used against the wrong ARCA environment."""

from collections.abc import Mapping

from cryptography import x509
from cryptography.x509 import ObjectIdentifier
from cryptography.x509.oid import NameOID

from pyarca.shell.endpoints import Environment

type CertificateIssuer = Mapping[ObjectIdentifier, str]

HOMOLOGATION_ISSUER: CertificateIssuer = {
    NameOID.COMMON_NAME: "Computadores Test",
    NameOID.ORGANIZATION_NAME: "AFIP",
    NameOID.COUNTRY_NAME: "AR",
}


class CertificateEnvironmentMismatchError(Exception):
    """A certificate was about to be used with an environment it does not belong to."""

    def __init__(self, *, environment: Environment, issuer: str) -> None:
        """Build the error naming the environment and the issuer of the certificate."""
        super().__init__(f"a certificate issued by {issuer} cannot be used in {environment}")
        self.environment = environment
        self.issuer = issuer


def issuer_of(certificate: x509.Certificate) -> CertificateIssuer:
    """Return the issuer of `certificate` as attribute values keyed by their OID."""
    return {attribute.oid: str(attribute.value) for attribute in certificate.issuer}


def is_homologation_issuer(issuer: CertificateIssuer) -> bool:
    """Tell whether `issuer` is exactly ARCA's homologation CA."""
    return dict(issuer) == dict(HOMOLOGATION_ISSUER)


def check_certificate_environment(issuer: CertificateIssuer, environment: Environment) -> None:
    """Allow homologation only to homologation certificates and production only to others.

    Raises:
        CertificateEnvironmentMismatchError: If the certificate belongs to the other environment.
    """
    belongs_to_homologation = is_homologation_issuer(issuer)
    if belongs_to_homologation == (environment == Environment.HOMOLOGATION):
        return
    raise CertificateEnvironmentMismatchError(
        environment=environment, issuer=", ".join(issuer.values())
    )
