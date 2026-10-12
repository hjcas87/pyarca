from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from pyarca.core.voucher import PESOS, PESOS_EXCHANGE_RATE, Tribute, VatLine, VoucherRequest
from pyarca.core.wsfe_codes import (
    Concept,
    DocumentType,
    ReceiverVatCondition,
    TributeType,
    VatRate,
    VoucherType,
)

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


@pytest.fixture(scope="session")
def homologation_certificate(rsa_key: rsa.RSAPrivateKey) -> x509.Certificate:
    issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Computadores Test"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AFIP"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
        ]
    )
    return (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "taxpayer")]))
        .issuer_name(issuer)
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


@pytest.fixture
def invoice_b() -> VoucherRequest:
    return VoucherRequest(
        point_of_sale=1,
        voucher_type=VoucherType.INVOICE_B,
        concept=Concept.PRODUCTS,
        document_type=DocumentType.FINAL_CONSUMER,
        document_number=0,
        receiver_vat_condition=ReceiverVatCondition.FINAL_CONSUMER,
        voucher_date=date(2026, 10, 12),
        total=Decimal("121.00"),
        non_taxed=Decimal(0),
        net=Decimal("100.00"),
        exempt=Decimal(0),
        vat_total=Decimal("21.00"),
        vat_lines=(VatLine(rate=VatRate.RATE_21, base=Decimal("100.00"), amount=Decimal("21.00")),),
        currency=PESOS,
        exchange_rate=PESOS_EXCHANGE_RATE,
    )


@pytest.fixture
def invoice_c() -> VoucherRequest:
    return VoucherRequest(
        point_of_sale=1,
        voucher_type=VoucherType.INVOICE_C,
        concept=Concept.PRODUCTS,
        document_type=DocumentType.FINAL_CONSUMER,
        document_number=0,
        receiver_vat_condition=ReceiverVatCondition.FINAL_CONSUMER,
        voucher_date=date(2026, 10, 12),
        total=Decimal("100.00"),
        non_taxed=Decimal(0),
        net=Decimal("100.00"),
        exempt=Decimal(0),
        vat_total=Decimal(0),
        vat_lines=(),
        currency=PESOS,
        exchange_rate=PESOS_EXCHANGE_RATE,
    )


@pytest.fixture
def invoice_a() -> VoucherRequest:
    return VoucherRequest(
        point_of_sale=1,
        voucher_type=VoucherType.INVOICE_A,
        concept=Concept.PRODUCTS,
        document_type=DocumentType.CUIT,
        document_number=20111111112,
        receiver_vat_condition=ReceiverVatCondition.REGISTERED_COMPANY,
        voucher_date=date(2026, 10, 12),
        total=Decimal("184.05"),
        non_taxed=Decimal(0),
        net=Decimal("150.00"),
        exempt=Decimal(0),
        vat_total=Decimal("26.25"),
        vat_lines=(
            VatLine(rate=VatRate.RATE_21, base=Decimal("100.00"), amount=Decimal("21.00")),
            VatLine(rate=VatRate.RATE_10_5, base=Decimal("50.00"), amount=Decimal("5.25")),
        ),
        tributes=(
            Tribute(
                tribute_type=TributeType.OTHER,
                description="Impuesto Municipal Matanza",
                base=Decimal("150.00"),
                rate=Decimal("5.20"),
                amount=Decimal("7.80"),
            ),
        ),
        currency=PESOS,
        exchange_rate=PESOS_EXCHANGE_RATE,
    )
