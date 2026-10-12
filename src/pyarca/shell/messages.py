"""The Spanish wording an application shows its users for pyarca's errors (ADR 0001).

Exceptions carry identity and English developer text; the sentences live here, so changing a
sentence never touches logic and adding a code never touches wording outside this module.
"""

from collections.abc import Callable
from typing import cast

from pyarca.core.amounts import AmountDefect, InvalidAmountError
from pyarca.core.recovery import ConsultationInconclusiveError, VoucherNumberTakenError
from pyarca.core.soap import MalformedResponseError, ResponseDefect, SoapFaultError
from pyarca.core.voucher import InvalidVoucherError, VoucherDefect
from pyarca.core.wsaa import WsaaFaultCode, WsaaFaultError
from pyarca.core.wsfe_codes import ArcaErrorCode
from pyarca.core.wsfe_xml import ArcaMessage
from pyarca.shell.environment_guard import CertificateEnvironmentMismatchError
from pyarca.shell.transport import HttpStatusError, RequestNotSentError, ResponseLostError
from pyarca.shell.wsfe_client import (
    ArcaErrorsError,
    RecoveryFailedError,
    VoucherNotAuthorizedError,
    VoucherNumberMismatchError,
)

UNEXPECTED_ERROR_MESSAGE = "Ocurrió un error inesperado al comunicarse con ARCA."
UNKNOWN_ARCA_ERROR_MESSAGE = "ARCA informó un error (código {code}): {message}"
UNKNOWN_WSAA_FAULT_MESSAGE = "ARCA rechazó el ingreso al servicio (código {code})."

VOUCHER_DEFECT_MESSAGES: dict[VoucherDefect, str] = {
    VoucherDefect.UNSUPPORTED_VOUCHER_TYPE: "Este tipo de comprobante todavía no se puede emitir.",
    VoucherDefect.INVALID_CURRENCY_CODE: "El código de moneda no es válido.",
    VoucherDefect.EXCHANGE_RATE_NOT_ONE: "La cotización de los pesos debe ser 1.",
    VoucherDefect.FOREIGN_SETTLEMENT_WITH_PESOS: (
        "Un comprobante en pesos no puede indicar si se cancela en moneda extranjera."
    ),
    VoucherDefect.SERVICE_PERIOD_REQUIRED: (
        "Los servicios requieren el período facturado y la fecha de vencimiento del pago."
    ),
    VoucherDefect.SERVICE_PERIOD_REVERSED: (
        "El período del servicio no puede terminar antes de empezar."
    ),
    VoucherDefect.PAYMENT_DUE_BEFORE_VOUCHER_DATE: (
        "El vencimiento del pago no puede ser anterior a la fecha del comprobante."
    ),
    VoucherDefect.FINAL_CONSUMER_DOCUMENT_NUMBER: (
        "El consumidor final se identifica con el número de documento 0."
    ),
    VoucherDefect.RECEIVER_CONDITION_NOT_ALLOWED: (
        "La condición frente al IVA del receptor no corresponde a este tipo de comprobante."
    ),
    VoucherDefect.DOCUMENT_TYPE_NOT_ALLOWED: (
        "Este tipo de comprobante solo se puede emitir a un receptor identificado con CUIT."
    ),
    VoucherDefect.DOCUMENT_NUMBER_OUT_OF_RANGE: "El CUIT del receptor no es válido.",
    VoucherDefect.VAT_REQUIRED: "Si hay importe neto, hay que detallar las alícuotas de IVA.",
    VoucherDefect.VAT_NOT_ALLOWED: "Este tipo de comprobante no discrimina IVA.",
    VoucherDefect.NON_NET_AMOUNT_NOT_ALLOWED: (
        "Este tipo de comprobante no admite importes no gravados ni exentos."
    ),
    VoucherDefect.VAT_AMOUNT_MISMATCH: (
        "El IVA total no coincide con la suma del IVA de cada alícuota."
    ),
    VoucherDefect.VAT_BASE_MISMATCH: (
        "La base imponible de las alícuotas no coincide con el importe neto."
    ),
    VoucherDefect.TOTAL_MISMATCH: "El importe total no coincide con la suma de sus partes.",
    VoucherDefect.VOUCHER_NUMBER_OUT_OF_RANGE: "El número de comprobante está fuera de rango.",
    VoucherDefect.TRIBUTES_WITHOUT_AMOUNT: "Los tributos informados deben sumar un importe.",
    VoucherDefect.TRIBUTE_DESCRIPTION_REQUIRED: "Falta la descripción de un tributo.",
    VoucherDefect.TRIBUTE_DESCRIPTION_TOO_LONG: (
        "La descripción de un tributo supera los 80 caracteres."
    ),
    VoucherDefect.TRIBUTE_RATE_OUT_OF_RANGE: "La alícuota de un tributo es demasiado grande.",
    VoucherDefect.ASSOCIATED_VOUCHER_REQUIRED: (
        "Una nota de crédito o de débito debe indicar el comprobante al que se asocia."
    ),
    VoucherDefect.ASSOCIATED_VOUCHER_NOT_ALLOWED: (
        "Este tipo de comprobante no puede estar asociado a otros."
    ),
    VoucherDefect.ASSOCIATED_VOUCHER_TYPE_INCOMPATIBLE: (
        "El comprobante asociado no es de un tipo que esta nota pueda asociar."
    ),
    VoucherDefect.ASSOCIATED_VOUCHER_DUPLICATED: "Un comprobante asociado está repetido.",
    VoucherDefect.ASSOCIATED_VOUCHER_DATE_NOT_ALLOWED: (
        "El comprobante asociado no puede ser de un mes posterior al de la nota."
    ),
    VoucherDefect.ASSOCIATED_POINT_OF_SALE_OUT_OF_RANGE: (
        "El punto de venta del comprobante asociado no es válido."
    ),
    VoucherDefect.ASSOCIATED_NUMBER_OUT_OF_RANGE: (
        "El número del comprobante asociado no es válido."
    ),
    VoucherDefect.ASSOCIATED_CUIT_INVALID: "El CUIT del comprobante asociado no es válido.",
    VoucherDefect.CBU_INVALID: "El CBU debe tener 22 dígitos.",
    VoucherDefect.CBU_ALIAS_INVALID: (
        "El alias del CBU debe tener entre 6 y 20 caracteres: letras, números, puntos o guiones."
    ),
    VoucherDefect.TRANSFER_MODE_INVALID: (
        "La modalidad de transferencia debe ser Sistema de Circulación Abierta (SCA) "
        "o Agente de Depósito Colectivo (ADC)."
    ),
    VoucherDefect.ANNULMENT_CODE_INVALID: "El código de anulación debe ser S o N.",
    VoucherDefect.COMMERCIAL_REFERENCE_INVALID: (
        "La referencia comercial debe tener entre 1 y 50 caracteres."
    ),
    VoucherDefect.OPTIONAL_DUPLICATED: "Un dato adicional del comprobante está repetido.",
    VoucherDefect.OPTIONAL_NOT_ALLOWED: (
        "Este tipo de comprobante no admite uno de los datos adicionales informados."
    ),
    VoucherDefect.CBU_REQUIRED: "Las facturas de crédito electrónica requieren el CBU del emisor.",
    VoucherDefect.TRANSFER_MODE_REQUIRED: (
        "Las facturas de crédito electrónica requieren la modalidad de transferencia."
    ),
    VoucherDefect.PAYMENT_DUE_REQUIRED: (
        "Las facturas de crédito electrónica requieren la fecha de vencimiento del pago."
    ),
    VoucherDefect.PAYMENT_DUE_GIVEN_TWICE: (
        "El vencimiento del pago se informó dos veces: en el período del servicio y aparte."
    ),
    VoucherDefect.FCE_RECEIVER_NOT_ALLOWED: (
        "Los comprobantes de crédito electrónica no se pueden emitir a sujetos no categorizados."
    ),
    VoucherDefect.ANNULMENT_CODE_REQUIRED: (
        "Las notas de crédito electrónica requieren indicar si anulan el comprobante asociado."
    ),
    VoucherDefect.PAYMENT_DUE_NOT_ALLOWED: (
        "Una nota de crédito electrónica solo informa vencimiento de pago si es de anulación."
    ),
}

AMOUNT_DEFECT_MESSAGES: dict[AmountDefect, str] = {
    AmountDefect.NOT_DECIMAL: "Un importe no tiene un formato numérico válido.",
    AmountDefect.NOT_FINITE: "Un importe no es un número válido.",
    AmountDefect.NEGATIVE: "Los importes no pueden ser negativos.",
    AmountDefect.NOT_POSITIVE: "La cotización debe ser mayor que cero.",
    AmountDefect.TOO_MANY_INTEGER_DIGITS: "Un importe tiene demasiados dígitos enteros.",
    AmountDefect.TOO_MANY_DECIMALS: "Un importe tiene más decimales de los que ARCA admite.",
}

RESPONSE_DEFECT_MESSAGES: dict[ResponseDefect, str] = {
    ResponseDefect.NOT_XML: "ARCA respondió algo que no se pudo interpretar.",
    ResponseDefect.DOCUMENT_TYPE: "ARCA respondió algo que no se pudo interpretar.",
    ResponseDefect.MISSING_ELEMENT: "La respuesta de ARCA está incompleta.",
    ResponseDefect.INVALID_TIME: "La respuesta de ARCA trae una hora ilegible.",
    ResponseDefect.INVALID_DATE: "La respuesta de ARCA trae una fecha ilegible.",
    ResponseDefect.INVALID_NUMBER: "La respuesta de ARCA trae un número ilegible.",
    ResponseDefect.INVALID_VALUE: "La respuesta de ARCA trae un valor inesperado.",
}

WSAA_FAULT_MESSAGES: dict[WsaaFaultCode, str] = {
    WsaaFaultCode.NOT_AUTHORIZED: (
        "El certificado no está autorizado para usar este servicio de ARCA."
    ),
    WsaaFaultCode.ALREADY_AUTHENTICATED: (
        "Ya existe un acceso vigente para este servicio; hay que reutilizarlo hasta que venza."
    ),
    WsaaFaultCode.CMS_INVALID: "La firma de la solicitud de acceso no es válida.",
    WsaaFaultCode.CMS_BASE64_INVALID: "La solicitud de acceso no está codificada correctamente.",
    WsaaFaultCode.CERTIFICATE_NOT_FOUND: "ARCA no reconoce el certificado utilizado.",
    WsaaFaultCode.SIGNATURE_INVALID: "La firma de la solicitud de acceso no es válida.",
    WsaaFaultCode.CERTIFICATE_EXPIRED: "El certificado venció; hay que generar uno nuevo.",
    WsaaFaultCode.CERTIFICATE_NOT_YET_VALID: "El certificado todavía no es válido.",
    WsaaFaultCode.CERTIFICATE_UNTRUSTED: (
        "El certificado no fue emitido por una autoridad en la que ARCA confíe."
    ),
    WsaaFaultCode.XML_INVALID: "La solicitud de acceso está mal formada.",
    WsaaFaultCode.SOURCE_INVALID: "El emisor de la solicitud de acceso no es válido.",
    WsaaFaultCode.DESTINATION_INVALID: "El destino de la solicitud de acceso no es válido.",
    WsaaFaultCode.VERSION_NOT_SUPPORTED: "La versión de la solicitud de acceso no es compatible.",
    WsaaFaultCode.GENERATION_TIME_INVALID: (
        "La hora de la solicitud de acceso no es válida; hay que revisar el reloj del equipo."
    ),
    WsaaFaultCode.REQUEST_EXPIRED: (
        "La solicitud de acceso venció antes de llegar; hay que revisar el reloj del equipo."
    ),
    WsaaFaultCode.EXPIRATION_TIME_INVALID: ("La vigencia de la solicitud de acceso no es válida."),
    WsaaFaultCode.SERVICE_UNAVAILABLE: "El servicio de ARCA no está disponible en este momento.",
    WsaaFaultCode.SERVICE_NOT_FOUND: "ARCA no reconoce el servicio solicitado.",
    WsaaFaultCode.WSAA_UNAVAILABLE: (
        "El servicio de autenticación de ARCA no está disponible en este momento."
    ),
    WsaaFaultCode.WSAA_INTERNAL_ERROR: (
        "El servicio de autenticación de ARCA tuvo un error interno; conviene reintentar luego."
    ),
}

ARCA_ERROR_MESSAGES: dict[ArcaErrorCode, str] = {
    ArcaErrorCode.NO_DATA_FOUND: "ARCA no tiene datos para esta consulta.",
    ArcaErrorCode.DOCUMENT_TYPE_MUST_BE_CUIT: (
        "Los comprobantes clase A solo se pueden emitir a un receptor identificado con CUIT."
    ),
    ArcaErrorCode.RECEIVER_IDENTIFICATION_REQUIRED: (
        "El importe supera el tope para consumidor final sin identificar; "
        "hay que informar el documento del receptor."
    ),
    ArcaErrorCode.VOUCHER_OUT_OF_SEQUENCE: (
        "El número del comprobante o su fecha no siguen al último comprobante autorizado."
    ),
    ArcaErrorCode.ASSOCIATED_VOUCHER_TYPE_NOT_ALLOWED: (
        "ARCA no admite asociar ese tipo de comprobante a este."
    ),
    ArcaErrorCode.TOTAL_DOES_NOT_ADD_UP: (
        "El importe total no coincide con la suma de neto, no gravado, exento, IVA y tributos."
    ),
    ArcaErrorCode.VAT_ARRAY_REQUIRED: "Si hay importe neto, hay que detallar las alícuotas de IVA.",
    ArcaErrorCode.PAYMENT_DUE_BEFORE_ISSUE_OR_TODAY: (
        "El vencimiento del pago no puede ser anterior a la fecha del comprobante ni a la de hoy."
    ),
    ArcaErrorCode.FCE_OPTIONAL_REQUIRED: (
        "Los comprobantes de crédito electrónica requieren al menos uno de estos datos: "
        "CBU, código de anulación o modalidad de transferencia."
    ),
    ArcaErrorCode.FCE_PAYMENT_DUE_NOT_ALLOWED: (
        "Solo las facturas de crédito electrónica, y las notas de anulación, "
        "informan vencimiento del pago."
    ),
    ArcaErrorCode.FCE_NOT_CATEGORIZED_RECEIVER: (
        "Los comprobantes de crédito electrónica no se pueden emitir a sujetos no categorizados."
    ),
    ArcaErrorCode.RECEIVER_VAT_CONDITION_UNKNOWN: (
        "La condición frente al IVA del receptor no existe."
    ),
    ArcaErrorCode.RECEIVER_VAT_CONDITION_NOT_VALID_FOR_CLASS: (
        "La condición frente al IVA del receptor no corresponde a la clase de comprobante."
    ),
}

NUMBER_OUT_OF_SEQUENCE_MESSAGE = (
    "El comprobante no sigue al último autorizado por ARCA, que es el {last_authorized_number}."
)
VOUCHER_NOT_AUTHORIZED_MESSAGE = (
    "ARCA no autorizó el comprobante número {voucher_number}; se puede volver a emitir."
)
RECOVERY_FAILED_MESSAGE = (
    "No se pudo confirmar si ARCA autorizó el comprobante número {voucher_number} "
    "del punto de venta {point_of_sale}; hay que consultarlo antes de emitir otro."
)
VOUCHER_NUMBER_TAKEN_MESSAGE = (
    "El número {voucher_number} ya fue usado por otro comprobante en ARCA."
)
CONSULTATION_INCONCLUSIVE_MESSAGE = (
    "ARCA respondió la consulta con errores y no se pudo confirmar si el comprobante existe."
)
REQUEST_NOT_SENT_MESSAGE = "No se pudo conectar con ARCA; no se envió nada y se puede reintentar."
RESPONSE_LOST_MESSAGE = "ARCA no respondió; no se sabe si procesó la solicitud."
HTTP_STATUS_MESSAGE = "ARCA respondió con un estado inesperado ({status_code})."
SOAP_FAULT_MESSAGE = "El servicio de ARCA respondió con una falla interna."
ENVIRONMENT_MISMATCH_MESSAGE = (
    "El certificado no corresponde al ambiente elegido: "
    "uno de homologación no sirve en producción, ni uno de producción en homologación."
)


def arca_error_message(message: ArcaMessage) -> str:
    """Return the Spanish sentence for an error ARCA reported, or ARCA's own wording if unknown."""
    known = _ARCA_ERRORS_BY_CODE.get(message.code)
    if known is not None:
        return known
    return UNKNOWN_ARCA_ERROR_MESSAGE.format(code=message.code, message=message.message)


def user_message(error: Exception) -> str:
    """Return the Spanish sentence to show a user for an error pyarca raised."""
    for error_type in type(error).__mro__:
        describe = _DESCRIBERS.get(error_type)
        if describe is not None:
            return describe(error)
    return UNEXPECTED_ERROR_MESSAGE


def _wsaa_fault_message(error: WsaaFaultError) -> str:
    known = _WSAA_FAULTS_BY_CODE.get(error.code)
    if known is not None:
        return known
    return UNKNOWN_WSAA_FAULT_MESSAGE.format(code=error.code)


def _describer[E: Exception](
    error_type: type[E], describe: Callable[[E], str]
) -> tuple[type[Exception], Callable[[Exception], str]]:
    def describe_any(error: Exception) -> str:
        return describe(cast("E", error))

    return error_type, describe_any


_ARCA_ERRORS_BY_CODE: dict[int, str] = {
    code.value: sentence for code, sentence in ARCA_ERROR_MESSAGES.items()
}
_WSAA_FAULTS_BY_CODE: dict[str, str] = {
    code.value: sentence for code, sentence in WSAA_FAULT_MESSAGES.items()
}

_DESCRIBERS: dict[type[Exception], Callable[[Exception], str]] = dict(
    [
        _describer(InvalidVoucherError, lambda error: VOUCHER_DEFECT_MESSAGES[error.defect]),
        _describer(InvalidAmountError, lambda error: AMOUNT_DEFECT_MESSAGES[error.defect]),
        _describer(MalformedResponseError, lambda error: RESPONSE_DEFECT_MESSAGES[error.defect]),
        _describer(WsaaFaultError, _wsaa_fault_message),
        _describer(
            ArcaErrorsError,
            lambda error: " ".join(arca_error_message(message) for message in error.errors),
        ),
        _describer(
            VoucherNumberMismatchError,
            lambda error: NUMBER_OUT_OF_SEQUENCE_MESSAGE.format(
                last_authorized_number=error.last_authorized_number
            ),
        ),
        _describer(
            VoucherNotAuthorizedError,
            lambda error: VOUCHER_NOT_AUTHORIZED_MESSAGE.format(
                voucher_number=error.voucher_number
            ),
        ),
        _describer(
            RecoveryFailedError,
            lambda error: RECOVERY_FAILED_MESSAGE.format(
                voucher_number=error.voucher_number, point_of_sale=error.point_of_sale
            ),
        ),
        _describer(
            VoucherNumberTakenError,
            lambda error: VOUCHER_NUMBER_TAKEN_MESSAGE.format(voucher_number=error.voucher_number),
        ),
        _describer(ConsultationInconclusiveError, lambda _: CONSULTATION_INCONCLUSIVE_MESSAGE),
        _describer(RequestNotSentError, lambda _: REQUEST_NOT_SENT_MESSAGE),
        _describer(ResponseLostError, lambda _: RESPONSE_LOST_MESSAGE),
        _describer(
            HttpStatusError,
            lambda error: HTTP_STATUS_MESSAGE.format(status_code=error.status_code),
        ),
        _describer(SoapFaultError, lambda _: SOAP_FAULT_MESSAGE),
        _describer(CertificateEnvironmentMismatchError, lambda _: ENVIRONMENT_MISMATCH_MESSAGE),
    ]
)
