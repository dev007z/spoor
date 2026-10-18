"""HTTP access to data providers, with every response stored as evidence first.

Each request is throttled, retried on transient failures, and recorded as a
RawResponse before its body is parsed. Cacheable requests (data that can no
longer change) are answered from the stored response without touching the network.
"""

import json
import logging
import random
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from spoor.modules.chains.adapters.base import ProviderError
from spoor.modules.chains.models import RawResponse

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def public_endpoint(url, redact_path=False):
    """The URL as it may be stored: no query string, and no path when the path holds a key."""
    parts = urlsplit(url)
    path = "/" if redact_path else parts.path
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class ProviderClient:
    def __init__(
        self,
        source,
        *,
        headers=None,
        min_interval=0.0,
        max_retries=4,
        timeout=30.0,
        redact_path=False,
        transport=None,
        sleep=time.sleep,
    ):
        self.source = source
        self.use_cache = True  # the fixture recorder turns this off to force live requests
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.redact_path = redact_path
        self.sleep = sleep
        self.last_request_at = 0.0
        self.http = httpx.Client(headers=headers or {}, timeout=timeout, transport=transport)

    def get_json(self, url, params=None, *, cacheable):
        params = params or {}
        return self.request("GET", url, params=params, stored_params=params, cacheable=cacheable)

    def post_json(self, url, payload, *, cacheable):
        return self.request(
            "POST", url, json_body=payload, stored_params={"body": payload}, cacheable=cacheable
        )

    def request(self, method, url, *, stored_params, cacheable, params=None, json_body=None):
        """Return (parsed JSON, RawResponse)."""
        endpoint = public_endpoint(url, self.redact_path)
        lookup = {"source": self.source, "endpoint": endpoint, "params": stored_params}

        if cacheable and self.use_cache:
            cached = RawResponse.get_latest(**lookup)
            if cached is not None:
                return json.loads(cached.body), cached

        response = self.send_with_retries(method, url, params=params, json_body=json_body)
        # Parse before storing: an unusable body must never become cached evidence.
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{self.source} returned non-JSON from {endpoint}") from exc
        raw = RawResponse.record(**lookup, status_code=response.status_code, body=response.text)
        return data, raw

    def send_with_retries(self, method, url, *, params, json_body):
        endpoint = public_endpoint(url, self.redact_path)
        for attempt in range(self.max_retries + 1):
            self.throttle()
            try:
                response = self.http.request(method, url, params=params, json=json_body)
            except httpx.TransportError as exc:
                failure = f"{type(exc).__name__}"
                retry_after = None
            else:
                if response.is_success:
                    return response
                if response.status_code not in RETRYABLE_STATUSES:
                    raise ProviderError(
                        f"{self.source} returned HTTP {response.status_code} from {endpoint}"
                    )
                failure = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After")

            if attempt == self.max_retries:
                raise ProviderError(
                    f"{self.source} failed after {attempt + 1} attempts ({failure}) at {endpoint}"
                )
            delay = self.backoff(attempt, retry_after)
            logger.warning(
                "Retrying %s %s after %s in %.1fs", self.source, endpoint, failure, delay
            )
            self.sleep(delay)

    def throttle(self):
        wait = self.last_request_at + self.min_interval - time.monotonic()
        if wait > 0:
            self.sleep(wait)
        self.last_request_at = time.monotonic()

    @staticmethod
    def backoff(attempt, retry_after):
        if retry_after and retry_after.isdigit():
            return float(retry_after)
        return min(2**attempt, 30) + random.uniform(0, 1)  # noqa: S311 - jitter, not security
