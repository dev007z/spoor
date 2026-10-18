import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from django.test import override_settings
from django.utils import timezone

from spoor.modules.chains.adapters.base import ProviderDataError, ProviderError
from spoor.modules.chains.adapters.http import ProviderClient, public_endpoint
from spoor.modules.chains.adapters.registry import AdapterNotConfiguredError, get_adapter
from spoor.modules.chains.adapters.replay import ReplayTransport
from spoor.modules.chains.adapters.tron import TronGridAdapter
from spoor.modules.chains.models import Chain, RawResponse, Token, Transfer

# Recorded with: record_adapter_fixture tron TDFNs6Q6MSLAvnnArevR4AnMhy77mDvehx
#   --start 2026-10-17T21:00:00+00:00 --end 2026-10-17T22:00:00+00:00 --name tron_usdt_one_hour
RECORDED_ADDRESS = "TDFNs6Q6MSLAvnnArevR4AnMhy77mDvehx"
RECORDED_START = datetime(2026, 10, 17, 21, tzinfo=UTC)
RECORDED_END = datetime(2026, 10, 17, 22, tzinfo=UTC)

SYNTHETIC_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
OTHER_ADDRESS_LOG_FORM = "0x" + "11" * 20


@pytest.fixture
def tron():
    return Chain.get_chain(key="tron")


@pytest.fixture
def usdt(tron):
    return Token.objects.get(chain=tron, symbol="USDT")


def tron_adapter(tron, transport):
    return TronGridAdapter(tron, transport=transport, min_interval=0)


@pytest.mark.django_db
class TestTronGridAdapterOnRecordedData:
    def fetch(self, tron, usdt, transport):
        return tron_adapter(tron, transport).get_token_transfers(
            RECORDED_ADDRESS, usdt, RECORDED_START, RECORDED_END, max_records=500
        )

    def test_returns_every_listed_transfer_with_evidence_fields(self, tron, usdt):
        result = self.fetch(tron, usdt, ReplayTransport("tron_usdt_one_hour"))

        assert result.complete
        assert len(result.records) == 9
        for record in result.records:
            assert RECORDED_ADDRESS in (record.from_address, record.to_address)
            assert RECORDED_START <= record.timestamp <= RECORDED_END
            assert record.block_number > 0
            assert record.log_index >= 0
            assert record.raw_response.endpoint.endswith(
                f"/v1/transactions/{record.tx_hash}/events"
            )

    def test_addresses_and_hashes_are_canonical(self, tron, usdt):
        """Events give addresses in 20-byte hex; records must use the stored base58 form."""
        result = self.fetch(tron, usdt, ReplayTransport("tron_usdt_one_hour"))

        for record in result.records:
            assert record.from_address.startswith("T")
            assert record.to_address.startswith("T")
            assert record.tx_hash == tron.normalize_tx_hash(record.tx_hash)

    def test_second_fetch_of_a_closed_window_makes_no_requests(self, tron, usdt):
        transport = ReplayTransport("tron_usdt_one_hour")
        first = self.fetch(tron, usdt, transport)
        served_after_first = transport.requests_served

        second = self.fetch(tron, usdt, transport)

        assert transport.requests_served == served_after_first
        assert second.records == first.records

    def test_records_store_once_and_keep_their_original_evidence(self, tron, usdt):
        result = self.fetch(tron, usdt, ReplayTransport("tron_usdt_one_hour"))

        Transfer.store_records(tron, usdt, result.records)
        Transfer.store_records(tron, usdt, result.records)

        stored = Transfer.objects.filter(chain=tron)
        assert stored.count() == 9
        assert {t.raw_response_id for t in stored} == {r.raw_response.pk for r in result.records}


def listing_page(tx_hashes, fingerprint=None):
    return {
        "success": True,
        "data": [
            {"transaction_id": tx, "type": "Transfer", "from": SYNTHETIC_ADDRESS, "value": "1"}
            for tx in tx_hashes
        ],
        "meta": {"fingerprint": fingerprint} if fingerprint else {},
    }


def events_page(tx_hash, transfers=1):
    return {
        "success": True,
        "data": [
            {
                "transaction_id": tx_hash,
                "block_number": 100,
                "block_timestamp": 1_792_270_800_000,
                "contract_address": SYNTHETIC_ADDRESS,
                "event_index": index,
                "event_name": "Transfer",
                "result": {
                    "from": "0xa614f803b6fd780986a42c78ec9c7f77e6ded13c",
                    "to": OTHER_ADDRESS_LOG_FORM,
                    "value": "1000000",
                },
            }
            for index in range(transfers)
        ],
        "meta": {},
    }


class FakeTronGrid:
    """A scripted TronGrid: listing pages by cursor, events by transaction."""

    def __init__(self, pages, events):
        self.pages = pages
        self.events = events
        self.listing_requests = 0

    def __call__(self, request):
        if request.url.path.endswith("/transactions/trc20"):
            self.listing_requests += 1
            cursor = request.url.params.get("fingerprint")
            return httpx.Response(200, json=self.pages[cursor])
        tx_hash = request.url.path.split("/")[3]
        return httpx.Response(200, json=self.events[tx_hash])


@pytest.mark.django_db
class TestTronGridAdapterBehaviour:
    """The USDT contract stands in as the traced address; it is a valid, well-known TRON address."""

    TX_A, TX_B, TX_C = ("a" * 64, "b" * 64, "c" * 64)
    WINDOW = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))

    def fetch(self, tron, usdt, fake, max_records=500, window=WINDOW):
        adapter = tron_adapter(tron, httpx.MockTransport(fake))
        return adapter.get_token_transfers(SYNTHETIC_ADDRESS, usdt, *window, max_records)

    def test_follows_fingerprint_pagination(self, tron, usdt):
        fake = FakeTronGrid(
            pages={
                None: listing_page([self.TX_A], fingerprint="page-2"),
                "page-2": listing_page([self.TX_B]),
            },
            events={self.TX_A: events_page(self.TX_A), self.TX_B: events_page(self.TX_B)},
        )

        result = self.fetch(tron, usdt, fake)

        assert [r.tx_hash for r in result.records] == [self.TX_A, self.TX_B]
        assert result.complete

    def test_max_records_truncates_and_reports_incomplete(self, tron, usdt):
        fake = FakeTronGrid(
            pages={None: listing_page([self.TX_A, self.TX_B, self.TX_C])},
            events={self.TX_A: events_page(self.TX_A), self.TX_B: events_page(self.TX_B)},
        )

        result = self.fetch(tron, usdt, fake, max_records=2)

        assert len(result.records) == 2
        assert not result.complete

    def test_several_transfers_in_one_transaction_are_kept_apart(self, tron, usdt):
        fake = FakeTronGrid(
            pages={None: listing_page([self.TX_A, self.TX_A])},
            events={self.TX_A: events_page(self.TX_A, transfers=2)},
        )

        result = self.fetch(tron, usdt, fake)

        assert [r.log_index for r in result.records] == [0, 1]

    def test_listing_and_events_disagreeing_is_an_error(self, tron, usdt):
        """Evidence that contradicts itself must stop the trace, not be partly used."""
        fake = FakeTronGrid(
            pages={None: listing_page([self.TX_A, self.TX_A])},
            events={self.TX_A: events_page(self.TX_A, transfers=1)},
        )

        with pytest.raises(ProviderDataError):
            self.fetch(tron, usdt, fake)

    def test_open_window_listing_is_refetched(self, tron, usdt):
        """A window reaching into the last few minutes can still gain transfers."""
        fake = FakeTronGrid(pages={None: listing_page([])}, events={})
        now = timezone.now()
        open_window = (now - timedelta(hours=1), now)

        self.fetch(tron, usdt, fake, window=open_window)
        self.fetch(tron, usdt, fake, window=open_window)

        assert fake.listing_requests == 2


@pytest.mark.django_db
class TestProviderClient:
    URL = "https://provider.test/v1/data"

    def client(self, handler, sleeps=None, **kwargs):
        return ProviderClient(
            "test",
            transport=httpx.MockTransport(handler),
            sleep=(sleeps.append if sleeps is not None else lambda _: None),
            **kwargs,
        )

    def test_retries_rate_limits_then_succeeds(self):
        responses = iter([httpx.Response(429), httpx.Response(429), httpx.Response(200, json={})])
        sleeps = []

        data, raw = self.client(lambda r: next(responses), sleeps).get_json(
            self.URL, cacheable=False
        )

        assert data == {}
        assert len(sleeps) == 2

    def test_honours_retry_after(self):
        responses = iter(
            [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={})]
        )
        sleeps = []

        self.client(lambda r: next(responses), sleeps).get_json(self.URL, cacheable=False)

        assert sleeps == [7.0]

    def test_gives_up_after_max_retries(self):
        with pytest.raises(ProviderError):
            self.client(lambda r: httpx.Response(503), max_retries=2).get_json(
                self.URL, cacheable=False
            )

    def test_client_errors_are_not_retried(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(404)

        with pytest.raises(ProviderError):
            self.client(handler).get_json(self.URL, cacheable=False)
        assert len(calls) == 1

    def test_failed_responses_are_not_stored_as_evidence(self):
        with pytest.raises(ProviderError):
            self.client(lambda r: httpx.Response(404)).get_json(self.URL, cacheable=False)
        assert RawResponse.objects.count() == 0

    def test_credentials_in_query_or_headers_are_never_stored(self):
        client = self.client(
            lambda r: httpx.Response(200, json={"ok": True}), headers={"X-Api-Key": "SECRET"}
        )

        _, raw = client.get_json(self.URL, {"apikey": "SECRET", "page": 1}, cacheable=False)

        assert raw.params == {"page": 1}
        assert "SECRET" not in json.dumps(raw.params) + raw.endpoint

    def test_url_path_is_redacted_when_it_holds_a_key(self):
        url = "https://rpc.provider.test/v1/SECRETKEY"
        assert public_endpoint(url, redact_path=True) == "https://rpc.provider.test/"
        assert public_endpoint(url + "?x=1") == url

    def test_non_json_body_is_an_error_and_never_cached(self):
        with pytest.raises(ProviderError):
            self.client(lambda r: httpx.Response(200, text="<html>")).get_json(
                self.URL, cacheable=True
            )
        assert RawResponse.objects.count() == 0


@pytest.mark.django_db
class TestRegistry:
    @override_settings(SPOOR_CHAIN_ADAPTERS={})
    def test_unconfigured_chain_raises(self, tron):
        with pytest.raises(AdapterNotConfiguredError):
            get_adapter(tron)

    @override_settings(
        SPOOR_CHAIN_ADAPTERS={
            "tron": {
                "class": "spoor.modules.chains.adapters.tron.TronGridAdapter",
                "options": {"base_url": "https://trongrid.example"},
            }
        }
    )
    def test_settings_options_and_overrides_reach_the_adapter(self, tron):
        adapter = get_adapter(tron, min_interval=0)

        assert isinstance(adapter, TronGridAdapter)
        assert adapter.base_url == "https://trongrid.example"
        assert adapter.client.min_interval == 0
