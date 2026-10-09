"""The one response envelope every JSON API endpoint returns.

    {"status": bool, "message": str, "data": <payload or null>}

Failures also carry `error_code`, and validation failures carry `errors`, the
full list of "field: detail" messages, so a form can show every problem at once
rather than only the first.
"""

from rest_framework import status as http_status
from rest_framework.response import Response


def success_response(data=None, message="Request successful.", status=http_status.HTTP_200_OK):
    return Response({"status": True, "message": message, "data": data}, status=status)


def error_response(message, error_code, status, errors=None):
    body = {"status": False, "message": message, "error_code": error_code, "data": None}
    if errors:
        body["errors"] = errors
    return Response(body, status=status)
