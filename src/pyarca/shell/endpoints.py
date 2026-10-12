"""WSAA endpoints per environment. WSDLs are never fetched at runtime (ADR 0003)."""

from enum import StrEnum


class Environment(StrEnum):
    """ARCA environments a client can target."""

    HOMOLOGATION = "homologation"
    PRODUCTION = "production"


WSAA_ENDPOINTS: dict[Environment, str] = {
    Environment.HOMOLOGATION: "https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
    Environment.PRODUCTION: "https://wsaa.afip.gov.ar/ws/services/LoginCms",
}
