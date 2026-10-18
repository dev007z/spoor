import pytest
from rest_framework.exceptions import NotFound, ValidationError

from spoor.common.exceptions import exception_handler
from spoor.common.functions import to_raw, to_units
from spoor.templatetags.spoor_format import amount, units

UINT256_MAX = 2**256 - 1


class TestAmountConversion:
    def test_to_units_is_exact_for_uint256_max(self):
        """The default decimal context would round this 78-digit value at 28 digits."""
        assert to_raw(to_units(UINT256_MAX, 18), 18) == UINT256_MAX

    def test_to_units_keeps_token_precision(self):
        assert str(to_units(1_500_000, 6)) == "1.500000"

    def test_to_raw_from_string_units(self):
        assert to_raw("1.5", 6) == 1_500_000

    def test_to_raw_rejects_precision_the_token_cannot_hold(self):
        with pytest.raises(ValueError):
            to_raw("0.0000001", 6)


class TestExceptionHandlerEnvelope:
    def test_validation_errors_are_flattened_with_field_prefixes(self):
        """Nested serializer errors become "field: detail" strings, first one as the message."""
        exc = ValidationError(
            {
                "max_hops": ["Ensure this value is less than or equal to 10."],
                "window": {"start": ["This field is required."]},
                "non_field_errors": ["Start must be before end."],
            }
        )

        response = exception_handler(exc, context={})

        assert response.status_code == 400
        assert response.data == {
            "status": False,
            "message": "max_hops: Ensure this value is less than or equal to 10.",
            "error_code": "validation_error",
            "data": None,
            "errors": [
                "max_hops: Ensure this value is less than or equal to 10.",
                "window.start: This field is required.",
                "Start must be before end.",
            ],
        }

    def test_api_exceptions_keep_their_status_and_code(self):
        response = exception_handler(NotFound("Case not found."), context={})

        assert response.status_code == 404
        assert response.data == {
            "status": False,
            "message": "Case not found.",
            "error_code": "not_found",
            "data": None,
        }

    def test_unhandled_exceptions_become_a_generic_500(self):
        """Internal error text must never leak to API clients."""
        response = exception_handler(RuntimeError("db password is hunter2"), context={})

        assert response.status_code == 500
        assert response.data["error_code"] == "server_error"
        assert "hunter2" not in response.data["message"]


class TestAmountFormatting:
    def test_display_rounds_to_six_places_and_drops_trailing_zeros(self):
        exact = to_units(205_454909702152215175, 18)

        assert amount(exact) == "205.45491"
        assert units(exact) == "205.454909702152215175"
        assert amount(to_units(1_000_000_000, 6)) == "1,000"
