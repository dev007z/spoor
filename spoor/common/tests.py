from rest_framework.exceptions import NotFound, ValidationError

from spoor.common.exceptions import exception_handler


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
