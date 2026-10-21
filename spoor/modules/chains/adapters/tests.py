import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from django.test import override_settings
from django.utils import timezone

from spoor.modules.chains.adapters.base import AdapterError, ProviderDataError, ProviderError
from spoor.modules.chains.adapters.evm import TRANSFER_TOPIC, JsonRpcAdapter
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

    def test_transaction_transfers_come_from_the_events_endpoint(self, tron, usdt):
        adapter = tron_adapter(tron, ReplayTransport("tron_usdt_one_hour"))

        records = adapter.get_transaction_transfers(
            "0x3D93268A87EE31F9C57B1BF6D513ABD2833E64DCA4670BF61FCC92AF8DB46BC6", usdt
        )

        assert len(records) == 1
        assert records[0].to_address == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        assert records[0].amount == 1_000_000

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

    def test_refusals_carry_the_providers_reason(self):
        refusal = {
            "jsonrpc": "2.0",
            "error": {"code": -32602, "message": "Archive requests need a key"},
        }

        with pytest.raises(ProviderError, match="HTTP 403 .*: Archive requests need a key"):
            self.client(lambda r: httpx.Response(403, json=refusal)).get_json(
                self.URL, cacheable=False
            )

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


# Recorded with: record_adapter_fixture bsc 0x59cc9ef29ecefaea870eb6f3a7b75887fe25110b
#   --start 2026-10-18T00:31:00+00:00 --end 2026-10-18T01:01:00+00:00 --name bsc_usdt_half_hour
BSC_ADDRESS = "0x59cc9ef29ecefaea870eb6f3a7b75887fe25110b"
BSC_START = datetime(2026, 10, 18, 0, 31, tzinfo=UTC)
BSC_END = datetime(2026, 10, 18, 1, 1, tzinfo=UTC)
RPC_URL = "https://rpc.example/secret-key-in-path"


@pytest.fixture
def bsc():
    return Chain.get_chain(key="bsc")


@pytest.fixture
def bsc_usdt(bsc):
    return Token.objects.get(chain=bsc, symbol="USDT")


def rpc_adapter(chain, transport, **options):
    return JsonRpcAdapter(chain, transport=transport, rpc_url=RPC_URL, min_interval=0, **options)


@pytest.mark.django_db
class TestJsonRpcAdapterOnRecordedData:
    def fetch(self, bsc, usdt, transport):
        return rpc_adapter(bsc, transport).get_token_transfers(
            BSC_ADDRESS, usdt, BSC_START, BSC_END, max_records=500
        )

    def replay(self):
        return ReplayTransport("bsc_usdt_half_hour", redact_path=True)

    def test_returns_transfers_in_the_window_with_evidence_fields(self, bsc, bsc_usdt):
        result = self.fetch(bsc, bsc_usdt, self.replay())

        assert result.complete
        assert len(result.records) == 6
        for record in result.records:
            assert BSC_ADDRESS in (record.from_address, record.to_address)
            assert BSC_START <= record.timestamp <= BSC_END
            assert record.tx_hash.startswith("0x") and record.tx_hash == record.tx_hash.lower()

    def test_rpc_url_path_is_never_stored(self, bsc, bsc_usdt):
        result = self.fetch(bsc, bsc_usdt, self.replay())

        assert result.records[0].raw_response.endpoint == "https://rpc.example/"
        assert not RawResponse.objects.filter(endpoint__contains="secret").exists()

    def test_second_fetch_only_asks_about_the_unfinalized_head(self, bsc, bsc_usdt):
        """Finalized blocks and logs come from cache; head number, finality, head block are live."""
        transport = self.replay()
        self.fetch(bsc, bsc_usdt, transport)
        served = transport.requests_served

        self.fetch(bsc, bsc_usdt, transport)

        assert transport.requests_served == served + 3


def word(value):
    return "0x" + format(value, "064x")


def topic_for(address):
    return "0x" + address[2:].rjust(64, "0")


class FakeChain:
    """A scripted JSON-RPC node: block i has timestamp times[i]; logs are filtered like a node."""

    def __init__(self, times, logs=(), max_range=None, finalized=None):
        self.times = times
        self.logs = list(logs)
        self.transactions = {}
        self.max_range = max_range
        self.finalized = len(times) - 1 if finalized is None else finalized
        self.ranges = []

    def __call__(self, request):
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        if method == "eth_blockNumber":
            return self.ok(hex(len(self.times) - 1))
        if method == "eth_getBlockByNumber":
            tag = params[0]
            number = self.finalized if tag == "finalized" else int(tag, 16)
            return self.ok({"number": hex(number), "timestamp": hex(self.times[number])})
        if method == "eth_getTransactionByHash":
            return self.ok(self.transactions.get(params[0]))
        if method == "eth_getLogs":
            spec = params[0]
            start, end = int(spec["fromBlock"], 16), int(spec["toBlock"], 16)
            if self.max_range and end - start + 1 > self.max_range:
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": -32005, "message": "block range limit exceeded"},
                    },
                )
            self.ranges.append((start, end))
            return self.ok([log for log in self.logs if self.matches(log, start, end, spec)])
        raise AssertionError(method)

    @staticmethod
    def matches(log, start, end, spec):
        if not start <= int(log["blockNumber"], 16) <= end:
            return False
        return all(
            want is None or log["topics"][i] == want for i, want in enumerate(spec["topics"])
        )

    @staticmethod
    def ok(result):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def transfer_log(block, index, sender, receiver, amount, tx="ab", removed=False):
    return {
        "blockNumber": hex(block),
        "logIndex": hex(index),
        "transactionHash": "0x" + tx * 32,
        "topics": [TRANSFER_TOPIC, topic_for(sender), topic_for(receiver)],
        "data": word(amount),
        "removed": removed,
    }


@pytest.mark.django_db
class TestJsonRpcAdapterBehaviour:
    SUBJECT = "0x" + "aa" * 20
    OTHER = "0x" + "bb" * 20
    TIMES = [1_000_000 + 3 * i for i in range(500)]  # block i at 1_000_000 + 3i seconds

    def at(self, block):
        return datetime.fromtimestamp(self.TIMES[block], tz=UTC)

    def fetch(self, bsc, usdt, node, start=10, end=400, max_records=500, **options):
        adapter = rpc_adapter(bsc, httpx.MockTransport(node), **options)
        return adapter.get_token_transfers(
            self.SUBJECT, usdt, self.at(start), self.at(end), max_records
        )

    def test_reads_both_directions_in_block_order(self, bsc, bsc_usdt):
        node = FakeChain(
            self.TIMES,
            [
                transfer_log(200, 1, self.SUBJECT, self.OTHER, 5, tx="02"),
                transfer_log(100, 0, self.OTHER, self.SUBJECT, 7, tx="01"),
            ],
        )

        records = self.fetch(bsc, bsc_usdt, node).records

        assert [(r.block_number, r.amount) for r in records] == [(100, 7), (200, 5)]
        assert records[0].to_address == self.SUBJECT
        assert records[0].timestamp == self.at(100)

    def test_window_bounds_are_inclusive_to_the_block(self, bsc, bsc_usdt):
        node = FakeChain(
            self.TIMES,
            [
                transfer_log(9, 0, self.OTHER, self.SUBJECT, 1, tx="01"),
                transfer_log(10, 0, self.OTHER, self.SUBJECT, 1, tx="02"),
                transfer_log(400, 0, self.OTHER, self.SUBJECT, 1, tx="03"),
                transfer_log(401, 0, self.OTHER, self.SUBJECT, 1, tx="04"),
            ],
        )

        records = self.fetch(bsc, bsc_usdt, node).records

        assert [r.block_number for r in records] == [10, 400]

    def test_refused_ranges_are_split_until_the_node_accepts(self, bsc, bsc_usdt):
        node = FakeChain(
            self.TIMES, [transfer_log(150, 0, self.OTHER, self.SUBJECT, 1)], max_range=100
        )

        result = self.fetch(bsc, bsc_usdt, node, max_block_range=1000)

        assert len(result.records) == 1
        assert all(end - start + 1 <= 100 for start, end in node.ranges)
        assert RawResponse.objects.filter(body__contains="limit exceeded").count() == 0

    def test_self_transfer_is_counted_once(self, bsc, bsc_usdt):
        node = FakeChain(self.TIMES, [transfer_log(50, 0, self.SUBJECT, self.SUBJECT, 1)])

        assert len(self.fetch(bsc, bsc_usdt, node).records) == 1

    def test_reorged_logs_are_ignored(self, bsc, bsc_usdt):
        node = FakeChain(
            self.TIMES,
            [
                transfer_log(50, 0, self.OTHER, self.SUBJECT, 1, removed=True),
            ],
        )

        assert self.fetch(bsc, bsc_usdt, node).records == []

    def test_max_records_truncates_and_reports_incomplete(self, bsc, bsc_usdt):
        node = FakeChain(
            self.TIMES,
            [transfer_log(20 + i, 0, self.OTHER, self.SUBJECT, 1, tx=f"{i:02x}") for i in range(5)],
        )

        result = self.fetch(bsc, bsc_usdt, node, max_records=3)

        assert len(result.records) == 3
        assert not result.complete

    def test_unfinalized_ranges_are_never_served_from_cache(self, bsc, bsc_usdt):
        node = FakeChain(self.TIMES, finalized=100)

        self.fetch(bsc, bsc_usdt, node)
        first = len(node.ranges)
        self.fetch(bsc, bsc_usdt, node)

        refetched = node.ranges[first:]
        assert refetched and all(end > 100 for _, end in refetched)

    def test_transaction_transfers_are_that_transactions_logs_in_its_block(self, bsc, bsc_usdt):
        node = FakeChain(
            self.TIMES,
            [
                transfer_log(42, 3, self.OTHER, self.SUBJECT, 9, tx="ab"),
                transfer_log(42, 4, self.SUBJECT, self.OTHER, 5, tx="cd"),  # same block, other tx
            ],
        )
        node.transactions["0x" + "ab" * 32] = {"blockNumber": hex(42)}
        adapter = rpc_adapter(bsc, httpx.MockTransport(node))

        records = adapter.get_transaction_transfers("0x" + "AB" * 32, bsc_usdt)

        assert [(r.log_index, r.amount) for r in records] == [(3, 9)]
        assert records[0].timestamp == self.at(42)
        assert node.ranges == [(42, 42)]

    def test_unknown_transaction_is_an_error(self, bsc, bsc_usdt):
        adapter = rpc_adapter(bsc, httpx.MockTransport(FakeChain(self.TIMES)))

        with pytest.raises(ProviderError, match="not found"):
            adapter.get_transaction_transfers("0x" + "ef" * 32, bsc_usdt)

    def test_missing_rpc_url_explains_the_setting(self, bsc):
        with pytest.raises(AdapterError, match="BSC_RPC_URL"):
            JsonRpcAdapter(bsc, rpc_url="")


@pytest.mark.django_db
class TestBlockSearch:
    @pytest.mark.parametrize(
        "times",
        [
            [1_000 + 3 * i for i in range(2_000)],  # uniform
            [1_000 + 3 * i + (40 if i > 1_500 else 0) for i in range(2_000)],  # a halt
            [1_000 + (i // 4) for i in range(2_000)],  # several blocks per second
        ],
    )
    def test_matches_brute_force(self, bsc, times):
        adapter = rpc_adapter(bsc, httpx.MockTransport(FakeChain(times)))
        adapter.head, adapter.finalized = len(times) - 1, len(times) - 1

        for target in [times[0] - 5, times[0], 1_777, times[1_700] - 1, times[-1], times[-1] + 9]:
            moment = datetime.fromtimestamp(target, tz=UTC)
            expected_inclusive = next((i for i, t in enumerate(times) if t >= target), len(times))
            expected_exclusive = next((i for i, t in enumerate(times) if t > target), len(times))

            assert adapter.first_block_at_or_after(moment) == expected_inclusive
            assert adapter.first_block_at_or_after(moment, inclusive=False) == expected_exclusive
