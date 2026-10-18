from datetime import UTC, datetime, timedelta

import pytest

from spoor.modules.chains.adapters.base import FetchResult, ProviderError, TransferRecord
from spoor.modules.chains.models import Address, RawResponse, Token
from spoor.modules.labels.enums import LabelCategory, LabelConfidence
from spoor.modules.labels.models import Label, LabelDataset
from spoor.modules.tracing.engine import TraceEngine
from spoor.modules.tracing.enums import StopReason, TraceDirection, TraceStatus
from spoor.modules.tracing.models import TraceRun

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def addr(name):
    """A readable fake EVM address: addr('a') -> 0xaaaa...aaaa."""
    return "0x" + name * 40


def at(minutes):
    return T0 + timedelta(minutes=minutes)


class GraphAdapter:
    """Serves transfers from an in-memory graph like a real adapter, recording each query."""

    def __init__(self, edges, incomplete=(), fail_on=()):
        self.raw = RawResponse.record(
            source="graph", endpoint="https://graph.test", params={}, status_code=200, body="{}"
        )
        self.records = [
            TransferRecord(
                tx_hash="0x" + format(index, "064x"),
                log_index=0,
                block_number=index,
                timestamp=at(minute),
                from_address=addr(sender),
                to_address=addr(receiver),
                amount=amount,
                raw_response=self.raw,
            )
            for index, (sender, receiver, amount, minute) in enumerate(edges, start=1)
        ]
        self.incomplete = {addr(n) for n in incomplete}
        self.fail_on = {addr(n) for n in fail_on}
        self.queries = []

    def get_token_transfers(self, address, token, start, end, max_records):
        self.queries.append((address, start, end))
        if address in self.fail_on:
            raise ProviderError("provider down")
        matching = [
            r
            for r in self.records
            if address in (r.from_address, r.to_address) and start <= r.timestamp <= end
        ]
        return FetchResult(records=matching, complete=address not in self.incomplete)


@pytest.fixture
def usdt():
    return Token.objects.get(chain__key="bsc", symbol="USDT")


def make_run(usdt, seeds=("a",), **params):
    defaults = {"start": at(0), "end": at(1000), "max_hops": 5, "fan_out": 5}
    run = TraceRun.objects.create(token=usdt, **{**defaults, **params})
    run.seeds.set([Address.resolve(usdt.chain, addr(seed)) for seed in seeds])
    return run


def trace(usdt, edges, seeds=("a",), adapter_options=None, **params):
    run = make_run(usdt, seeds, **params)
    adapter = GraphAdapter(edges, **(adapter_options or {}))
    TraceEngine(run, adapter).execute()
    run.refresh_from_db()
    return run, adapter


def node_hops(run):
    return {n.address.address[2]: n.hop for n in run.nodes.select_related("address")}


def node(run, name):
    return run.nodes.get(address__address=addr(name))


@pytest.mark.django_db
class TestForwardTrace:
    def test_follows_outflows_hop_by_hop(self, usdt):
        run, _ = trace(usdt, [("a", "b", 100, 1), ("b", "c", 90, 2), ("c", "d", 80, 3)])

        assert run.status == TraceStatus.COMPLETED
        assert node_hops(run) == {"a": 0, "b": 1, "c": 2, "d": 3}
        assert run.edges.count() == 3

    def test_inflows_are_not_followed_forward(self, usdt):
        run, _ = trace(usdt, [("z", "a", 100, 1), ("a", "b", 50, 2)])

        assert set(node_hops(run)) == {"a", "b"}

    def test_cycles_terminate_and_keep_the_closing_edge(self, usdt):
        run, adapter = trace(usdt, [("a", "b", 100, 1), ("b", "c", 90, 2), ("c", "a", 80, 3)])

        assert node_hops(run) == {"a": 0, "b": 1, "c": 2}
        assert run.edges.count() == 3
        assert len(adapter.queries) == 3  # each address fetched once

    def test_funds_cannot_leave_before_they_arrive(self, usdt):
        """b's outflow at minute 1 predates its inflow at minute 5, so it is not the same money."""
        run, adapter = trace(usdt, [("a", "b", 100, 5), ("b", "c", 100, 1), ("b", "d", 100, 6)])

        assert set(node_hops(run)) == {"a", "b", "d"}
        b_query = next(q for q in adapter.queries if q[0] == addr("b"))
        assert b_query[1] == at(5)

    def test_earliest_inflow_sets_the_time_bound(self, usdt):
        """b is reached at minutes 10 and 3; its outflow at 4 counts because of the earlier path."""
        run, _ = trace(
            usdt,
            [("a", "b", 100, 10), ("a", "c", 100, 1), ("c", "b", 100, 3), ("b", "d", 100, 4)],
        )

        assert "d" in node_hops(run)

    def test_min_amount_filters_dust(self, usdt):
        run, _ = trace(usdt, [("a", "b", 100, 1), ("a", "c", 5, 1)], min_amount=10)

        assert set(node_hops(run)) == {"a", "b"}

    def test_fan_out_follows_the_largest_and_flags_truncation(self, usdt):
        edges = [("a", name, amount, 1) for name, amount in [("b", 10), ("c", 30), ("d", 20)]]

        run, _ = trace(usdt, edges, fan_out=2)

        assert set(node_hops(run)) == {"a", "c", "d"}
        assert node(run, "a").fan_out_truncated

    def test_stops_at_the_hop_limit(self, usdt):
        run, adapter = trace(
            usdt, [("a", "b", 1, 1), ("b", "c", 1, 2), ("c", "d", 1, 3)], max_hops=2
        )

        assert node(run, "c").stop_reason == StopReason.MAX_HOPS
        assert not node(run, "c").expanded
        assert addr("c") not in [q[0] for q in adapter.queries]

    def test_stops_at_labeled_exchanges(self, usdt):
        dataset = LabelDataset.objects.create(key="test", name="Test")
        Label.objects.create(
            dataset=dataset,
            address=Address.resolve(usdt.chain, addr("b")),
            entity="Example Exchange",
            category=LabelCategory.EXCHANGE,
            confidence=LabelConfidence.HIGH,
            source_url="https://example.test",
        )

        run, _ = trace(usdt, [("a", "b", 100, 1), ("b", "c", 100, 2)])

        assert node(run, "b").stop_reason == StopReason.LABELED_ENDPOINT
        assert node(run, "b").label.entity == "Example Exchange"
        assert "c" not in node_hops(run)

    def test_address_with_nothing_to_follow_is_marked(self, usdt):
        run, _ = trace(usdt, [("a", "b", 100, 1)])

        assert node(run, "b").stop_reason == StopReason.NO_TRANSFERS
        assert node(run, "b").expanded

    def test_incomplete_provider_results_are_flagged(self, usdt):
        run, _ = trace(usdt, [("a", "b", 100, 1)], adapter_options={"incomplete": ["a"]})

        assert node(run, "a").fetch_incomplete

    def test_records_progress(self, usdt):
        run, _ = trace(usdt, [("a", "b", 100, 1), ("b", "c", 90, 2)])

        assert run.addresses_expanded == 3
        assert run.started_at and run.finished_at


@pytest.mark.django_db
class TestBackwardTrace:
    def test_follows_inflows_that_happened_before(self, usdt):
        """c received from b at 5; b's funds came from a at 3, not from z at 9 (after)."""
        run, _ = trace(
            usdt,
            [("a", "b", 100, 3), ("z", "b", 100, 9), ("b", "c", 100, 5)],
            seeds=("c",),
            direction=TraceDirection.BACKWARD,
        )

        assert node_hops(run) == {"c": 0, "b": 1, "a": 2}


@pytest.mark.django_db
class TestFailures:
    def test_provider_failure_marks_the_run_failed_and_keeps_partial_results(self, usdt):
        run, _ = trace(
            usdt, [("a", "b", 100, 1), ("b", "c", 90, 2)], adapter_options={"fail_on": ["b"]}
        )

        assert run.status == TraceStatus.FAILED
        assert "provider down" in run.error
        assert set(node_hops(run)) == {"a", "b"}

    def test_unconfigured_chain_fails_the_run_with_the_reason(self, usdt, settings):
        settings.SPOOR_CHAIN_ADAPTERS = {}
        run = make_run(usdt)

        TraceEngine(run).execute()

        run.refresh_from_db()
        assert run.status == TraceStatus.FAILED
        assert "No adapter configured" in run.error


@pytest.mark.django_db
class TestTracePages:
    def form_data(self, usdt, **overrides):
        return {
            "token": usdt.pk,
            "address": addr("a"),
            "start": "2026-01-01T00:00",
            "end": "2026-01-02T00:00",
            "direction": TraceDirection.FORWARD,
            "max_hops": 2,
            "fan_out": 3,
            "min_amount": "1.5",
            **overrides,
        }

    def test_requires_login(self, client):
        assert client.get("/traces/").status_code == 302

    def test_starting_a_trace_queues_it_after_commit(
        self, admin_client, usdt, monkeypatch, django_capture_on_commit_callbacks
    ):
        queued = []
        monkeypatch.setattr("spoor.modules.tracing.views.run_trace.delay", queued.append)

        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.post("/traces/", self.form_data(usdt))

        run = TraceRun.objects.get()
        assert response.url == f"/traces/{run.pk}/"
        assert queued == [str(run.pk)]
        assert run.min_amount == 1_500_000_000_000_000_000  # 1.5 USDT at 18 decimals
        assert [seed.address for seed in run.seeds.all()] == [addr("a")]

    def test_min_amount_finer_than_the_token_allows_is_rejected(self, admin_client):
        tron_usdt = Token.objects.get(chain__key="tron", symbol="USDT")
        data = self.form_data(
            tron_usdt, address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", min_amount="0.0000001"
        )

        response = admin_client.post("/traces/", data)

        assert "min_amount" in response.context["form"].errors
        assert not TraceRun.objects.exists()

    def test_running_trace_keeps_polling_and_finished_trace_stops(self, admin_client, usdt):
        run = make_run(usdt)
        url = f"/traces/{run.pk}/"

        polling = admin_client.get(url, HTTP_HX_REQUEST="true").content.decode()
        TraceEngine(run, GraphAdapter([("a", "b", 100, 1)])).execute()
        finished = admin_client.get(url, HTTP_HX_REQUEST="true")

        assert 'hx-trigger="every 2s"' in polling
        assert "hx-trigger" not in finished.content.decode()
        assert finished.context["stats"] == {"addresses": 2, "transfers": 1, "endpoints": 0}
