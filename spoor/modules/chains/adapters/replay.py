"""Record real provider exchanges once, replay them in tests forever.

A recording is a JSON list of request/response exchanges. Requests are matched on
method, path, query, and body, ignoring scheme and host, so a test can point an
adapter at any base URL. Credentials are stripped before anything is written:
sensitive query parameters are dropped, headers are never saved, and adapters
that keep keys in the URL path record the path as "/".
"""

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import httpx

from spoor.modules.chains.models import SENSITIVE_PARAMS

RECORDINGS_DIR = Path(__file__).resolve().parent / "recordings"


def request_key(request, redact_path=False):
    query = sorted(
        (k, v)
        for k, v in parse_qsl(request.url.query.decode())
        if k.lower() not in SENSITIVE_PARAMS
    )
    body = json.loads(request.content) if request.content else None
    return {
        "method": request.method,
        "path": "/" if redact_path else request.url.path,
        "query": urlencode(query),
        "body": body,
    }


class RecordingTransport(httpx.BaseTransport):
    """Passes requests through to the real network and keeps a sanitized copy of each exchange."""

    def __init__(self, path, redact_path=False):
        self.path = Path(path)
        self.redact_path = redact_path
        self.inner = httpx.HTTPTransport()
        self.exchanges = []

    def handle_request(self, request):
        response = self.inner.handle_request(request)
        response.read()
        self.exchanges.append(
            {
                "request": request_key(request, self.redact_path),
                "response": {"status": response.status_code, "body": response.text},
            }
        )
        return response

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.exchanges, indent=2) + "\n")


class ReplayTransport(httpx.BaseTransport):
    """Serves a recording. Any request not in it fails the test instead of reaching the network."""

    def __init__(self, name, redact_path=False):
        exchanges = json.loads((RECORDINGS_DIR / f"{name}.json").read_text())
        self.responses = {self.freeze(e["request"]): e["response"] for e in exchanges}
        self.redact_path = redact_path
        self.requests_served = 0

    @staticmethod
    def freeze(key):
        return json.dumps(key, sort_keys=True)

    def handle_request(self, request):
        key = request_key(request, self.redact_path)
        recorded = self.responses.get(self.freeze(key))
        if recorded is None:
            raise AssertionError(f"No recorded response for request: {key}")
        self.requests_served += 1
        return httpx.Response(recorded["status"], text=recorded["body"])
