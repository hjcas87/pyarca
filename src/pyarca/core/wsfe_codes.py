"""Closed sets of codes WSFEv1 documents, as ARCA's developer manual lists them."""

from enum import IntEnum


class VoucherType(IntEnum):
    """`CbteTipo`: the kind of voucher being authorized."""

    INVOICE_A = 1
    DEBIT_NOTE_A = 2
    CREDIT_NOTE_A = 3
    INVOICE_B = 6
    DEBIT_NOTE_B = 7
    CREDIT_NOTE_B = 8
    INVOICE_C = 11
    DEBIT_NOTE_C = 12
    CREDIT_NOTE_C = 13
    FCE_INVOICE_A = 201
    FCE_DEBIT_NOTE_A = 202
    FCE_CREDIT_NOTE_A = 203
    FCE_INVOICE_B = 206
    FCE_DEBIT_NOTE_B = 207
    FCE_CREDIT_NOTE_B = 208
    FCE_INVOICE_C = 211
    FCE_DEBIT_NOTE_C = 212
    FCE_CREDIT_NOTE_C = 213


class DocumentType(IntEnum):
    """`DocTipo`: the kind of identity document of the receiver."""

    CUIT = 80
    CUIL = 86
    CDI = 87
    DNI = 96
    FINAL_CONSUMER = 99


class Concept(IntEnum):
    """`Concepto`: what the voucher bills."""

    PRODUCTS = 1
    SERVICES = 2
    PRODUCTS_AND_SERVICES = 3


class VatRate(IntEnum):
    """`AlicIva.Id`: the VAT aliquot of a line, named by its percentage."""

    RATE_0 = 3
    RATE_10_5 = 4
    RATE_21 = 5
    RATE_27 = 6
    RATE_5 = 8
    RATE_2_5 = 9


class TributeType(IntEnum):
    """`Tributo.Id`: the kind of other tax, as `FEParamGetTiposTributos` lists them."""

    NATIONAL_TAXES = 1
    PROVINCIAL_TAXES = 2
    MUNICIPAL_TAXES = 3
    INTERNAL_TAXES = 4
    GROSS_INCOME = 5
    VAT_PERCEPTION = 6
    GROSS_INCOME_PERCEPTION = 7
    MUNICIPAL_PERCEPTION = 8
    OTHER_PERCEPTIONS = 9
    VAT_PERCEPTION_NOT_CATEGORIZED = 13
    OTHER = 99


class ReceiverVatCondition(IntEnum):
    """`CondicionIVAReceptorId` (RG 5616): the receiver's standing before VAT."""

    REGISTERED_COMPANY = 1
    EXEMPT = 4
    FINAL_CONSUMER = 5
    MONOTAX = 6
    NOT_CATEGORIZED = 7
    FOREIGN_SUPPLIER = 8
    FOREIGN_CLIENT = 9
    LIBERATED_LAW_19640 = 10
    SOCIAL_MONOTAX = 13
    NOT_SUBJECT_TO_VAT = 15
    PROMOTED_INDEPENDENT_MONOTAX = 16


class ArcaErrorCode(IntEnum):
    """Codes of ARCA errors and observations that callers act on."""

    VOUCHER_OUT_OF_SEQUENCE = 10016
    NO_DATA_FOUND = 602
