"""DRF exception handler that renders every API failure in the shared envelope."""

import logging

from rest_framework import status as http_status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler as drf_exception_handler

from spoor.common.responses import error_response

logger = logging.getLogger(__name__)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled API exception", exc_info=exc)
        return error_response(
            message="An unexpected error occurred.",
            error_code="server_error",
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ValidationError):
        errors = flatten_errors(exc.detail)
        return error_response(
            message=errors[0] if errors else "Invalid input.",
            error_code="validation_error",
            status=response.status_code,
            errors=errors,
        )

    error_code = exc.default_code if isinstance(exc, APIException) else "error"
    return error_response(
        message=str(getattr(exc, "detail", exc)),
        error_code=error_code,
        status=response.status_code,
    )


def flatten_errors(detail, path=""):
    """Turn DRF's nested error detail into flat "field: detail" messages."""
    if isinstance(detail, dict):
        messages = []
        for field, value in detail.items():
            key = str(field) if not path else f"{path}.{field}"
            messages.extend(flatten_errors(value, key))
        return messages

    if isinstance(detail, list):
        messages = []
        for index, value in enumerate(detail):
            key = f"{path}[{index}]" if isinstance(value, dict | list) else path
            messages.extend(flatten_errors(value, key))
        return messages

    field = "" if path == "non_field_errors" else path
    return [f"{field}: {detail}" if field else str(detail)]
