from datetime import UTC, datetime, timedelta

import pytest
from django.test import Client

from spoor.modules.cases.enums import CaseEventType, CaseType
from spoor.modules.cases.models import Case
from spoor.modules.chains.adapters.base import FetchResult, ProviderError, TransferRecord
from spoor.modules.chains.models import Address, RawResponse, Token
from spoor.modules.labels.enums import LabelCategory, LabelConfidence
from spoor.modules.labels.models import Label, LabelDataset
from spoor.modules.tracing.engine import TraceEngine
from spoor.modules.tracing.enums import StopReason, TraceDirection, TraceStatus
from spoor.modules.tracing.graph import MAX_EDGE_WIDTH, build_graph, edge_width
from spoor.modules.tracing.heuristics import CollectionWallet, evaluate_run
from spoor.modules.tracing.models import TraceRun

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def addr(name):
    """A readable fake EVM address: addr('a') -> 0xaaaa...aaaa, addr('a1') -> 0xa1a1...a1."""
    return "0x" + (name * 40)[:40]


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

    def get_transaction_transfers(self, tx_hash, token):
        return [r for r in self.records if r.tx_hash == tx_hash]


def tx(index):
    """The hash GraphAdapter gives the index-th edge (1-based)."""
    return "0x" + format(index, "064x")


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
class TestTransactionSeeds:
    def test_forward_starts_from_the_transactions_recipients(self, usdt):
        """Seeded from a→b, the trace follows b onward but not a's other outflows."""
        edges = [("a", "b", 100, 1), ("a", "x", 500, 1), ("b", "c", 90, 2)]
        run = TraceRun.create_run(usdt, seed_tx_hash=tx(1), start=at(0), end=at(1000))

        TraceEngine(run, GraphAdapter(edges)).execute()

        run.refresh_from_db()
        assert run.status == TraceStatus.COMPLETED
        assert node_hops(run) == {"a": 0, "b": 1, "c": 2}
        assert [s.address for s in run.seeds.all()] == [addr("a")]

    def test_backward_starts_from_the_transactions_senders(self, usdt):
        edges = [("z", "a", 100, 1), ("a", "b", 100, 2)]
        run = TraceRun.create_run(
            usdt,
            seed_tx_hash=tx(2),
            start=at(0),
            end=at(1000),
            direction=TraceDirection.BACKWARD,
        )

        TraceEngine(run, GraphAdapter(edges)).execute()

        assert node_hops(run) == {"b": 0, "a": 1, "z": 2}

    def test_transaction_without_token_transfers_fails_the_run(self, usdt):
        run = TraceRun.create_run(usdt, seed_tx_hash=tx(99), start=at(0), end=at(1000))

        TraceEngine(run, GraphAdapter([("a", "b", 1, 1)])).execute()

        run.refresh_from_db()
        assert run.status == TraceStatus.FAILED
        assert "has no USDT transfers" in run.error


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

    def test_starting_a_trace_in_a_case_records_it_in_the_case(
        self, admin_client, admin_user, usdt, monkeypatch
    ):
        monkeypatch.setattr("spoor.modules.tracing.views.run_trace.delay", lambda run_id: None)
        case = Case.create_case(admin_user, name="Case", case_type=CaseType.OTHER)

        admin_client.post("/traces/", self.form_data(usdt, case=case.pk))

        run = TraceRun.objects.get()
        assert run.case == case
        assert run.created_by == admin_user
        started = case.events.get(event_type=CaseEventType.TRACE_STARTED)
        assert started.details == {"trace_run": str(run.pk)}

    def test_case_is_preselected_when_starting_from_a_case(self, admin_client, admin_user):
        case = Case.create_case(admin_user, name="Case", case_type=CaseType.OTHER)

        response = admin_client.get(f"/traces/?case={case.pk}")

        assert response.context["form"].initial["case"] == str(case.pk)

    def test_a_transaction_hash_seeds_from_that_transaction(
        self, admin_client, usdt, monkeypatch, django_capture_on_commit_callbacks
    ):
        monkeypatch.setattr("spoor.modules.tracing.views.run_trace.delay", lambda run_id: None)

        with django_capture_on_commit_callbacks(execute=True):
            admin_client.post("/traces/", self.form_data(usdt, address="0x" + "AB" * 32))

        run = TraceRun.objects.get()
        assert run.seed_tx_hash == "0x" + "ab" * 32
        assert not run.seeds.exists()

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


@pytest.mark.django_db
class TestTraceGraph:
    def test_combines_transfers_per_address_pair(self, usdt):
        run, _ = trace(usdt, [("a", "b", 100, 1), ("a", "b", 50, 2), ("b", "c", 30, 3)])

        graph = build_graph(run)

        flows = {(e["source"][2], e["target"][2]): e for e in graph["edges"]}
        assert flows[("a", "b")]["count"] == 2
        assert flows[("a", "b")]["amount"] == str(usdt.to_units(150))
        assert flows[("a", "b")]["width"] > flows[("b", "c")]["width"]

    def test_nodes_carry_kind_hop_and_links(self, usdt):
        run, _ = trace(usdt, [("a", "b", 100, 1)])

        nodes = {n["id"][2]: n for n in build_graph(run)["nodes"]}

        assert nodes["a"]["kind"] == "seed"
        assert nodes["b"]["hop"] == 1
        assert nodes["b"]["outcome"] == "No qualifying transfers"
        assert nodes["b"]["transfers_url"].startswith("/transfers/?")

    def test_notes_url_only_for_traces_in_a_case(self, usdt, admin_user):
        case = Case.create_case(admin_user, name="Case", case_type=CaseType.OTHER)
        in_case, _ = trace(usdt, [("a", "b", 1, 1)], case=case)
        loose, _ = trace(usdt, [("c", "d", 1, 1)], seeds=("c",))

        assert build_graph(in_case)["notes_url"] == f"/api/v1/cases/{case.pk}/notes/"
        assert build_graph(loose)["notes_url"] is None

    def test_edge_width_is_log_scaled_within_bounds(self):
        assert edge_width(0, 0) == 1
        assert edge_width(10**24, 10**24) == MAX_EDGE_WIDTH
        assert 1 < edge_width(10**12, 10**24) < MAX_EDGE_WIDTH

    def test_api_returns_the_graph_in_the_envelope(self, admin_client, usdt):
        run, _ = trace(usdt, [("a", "b", 100, 1)])

        body = admin_client.get(f"/api/v1/traces/{run.pk}/graph/").json()

        assert body["status"] is True
        assert len(body["data"]["nodes"]) == 2
        assert body["data"]["finished"] is True

    def test_api_requires_login(self, client, usdt):
        run = make_run(usdt)

        response = client.get(f"/api/v1/traces/{run.pk}/graph/")

        assert response.status_code == 403
        assert response.json()["status"] is False


@pytest.mark.django_db
class TestManualExpansion:
    def test_expanding_a_hop_limited_node_follows_it(self, usdt):
        edges = [("a", "b", 100, 1), ("b", "c", 100, 2), ("c", "d", 100, 3)]
        run, _ = trace(usdt, edges, max_hops=1)
        stopped = node(run, "b")
        assert stopped.stop_reason == StopReason.MAX_HOPS

        TraceEngine(run, GraphAdapter(edges)).execute(from_node=stopped)

        run.refresh_from_db()
        assert node(run, "b").expanded
        assert node_hops(run) == {"a": 0, "b": 1, "c": 2}
        assert node(run, "c").stop_reason == StopReason.MAX_HOPS  # normal rules resume
        assert run.status == TraceStatus.COMPLETED

    def test_expanding_a_labeled_endpoint_overrides_the_stop_once(self, usdt):
        dataset = LabelDataset.objects.create(key="test", name="Test")
        for name in ("b", "c"):
            Label.objects.create(
                dataset=dataset,
                address=Address.resolve(usdt.chain, addr(name)),
                entity=f"Exchange {name}",
                category=LabelCategory.EXCHANGE,
                confidence=LabelConfidence.HIGH,
                source_url="https://example.test",
            )
        edges = [("a", "b", 100, 1), ("b", "c", 100, 2), ("c", "d", 100, 3)]
        run, _ = trace(usdt, edges)

        TraceEngine(run, GraphAdapter(edges)).execute(from_node=node(run, "b"))

        assert node(run, "c").stop_reason == StopReason.LABELED_ENDPOINT
        assert "d" not in node_hops(run)

    def expand_url(self, run, name):
        return f"/api/v1/traces/{run.pk}/nodes/{node(run, name).pk}/expand/"

    def test_api_queues_the_expansion(
        self, admin_client, usdt, monkeypatch, django_capture_on_commit_callbacks
    ):
        queued = []
        monkeypatch.setattr("spoor.modules.tracing.api.expand_node.delay", queued.append)
        run, _ = trace(usdt, [("a", "b", 1, 1), ("b", "c", 1, 2)], max_hops=1)

        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.post(self.expand_url(run, "b"))

        run.refresh_from_db()
        assert response.status_code == 202
        assert queued == [str(node(run, "b").pk)]
        assert run.status == TraceStatus.PENDING

    def test_expanding_inside_a_case_records_it(self, admin_client, admin_user, usdt, monkeypatch):
        monkeypatch.setattr("spoor.modules.tracing.api.expand_node.delay", lambda node_id: None)
        case = Case.create_case(admin_user, name="Case", case_type=CaseType.OTHER)
        run, _ = trace(usdt, [("a", "b", 1, 1), ("b", "c", 1, 2)], max_hops=1, case=case)

        admin_client.post(self.expand_url(run, "b"))

        expanded = case.events.get(event_type=CaseEventType.TRACE_EXPANDED)
        assert expanded.details["address"] == addr("b")

    def test_api_refuses_while_running_or_already_expanded(self, admin_client, usdt):
        run, _ = trace(usdt, [("a", "b", 1, 1)])

        expanded = admin_client.post(self.expand_url(run, "a"))
        run.mark_running()
        running = admin_client.post(self.expand_url(run, "b"))

        assert expanded.status_code == 409
        assert expanded.json()["error_code"] == "already_expanded"
        assert running.status_code == 409
        assert running.json()["error_code"] == "trace_running"

    def test_api_requires_csrf_for_session_users(self, usdt, django_user_model):
        user = django_user_model.objects.create_user("analyst", password="pw-for-tests")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        run, _ = trace(usdt, [("a", "b", 1, 1)], max_hops=0)

        response = csrf_client.post(self.expand_url(run, "a"))

        assert response.status_code == 403


@pytest.mark.django_db
class TestCollectionWalletHeuristic:
    """Collection: many senders into hub "9", then most of it swept onward to "8"."""

    def inflows(self, senders, minute=10, amount=100):
        return [(name, "9", amount, minute + i) for i, name in enumerate(senders)]

    def signals(self, usdt, edges):
        run, _ = trace(usdt, edges, seeds=("9",), direction=TraceDirection.FORWARD, max_hops=1)
        return list(node(run, "9").signals.all())

    def test_fires_on_many_senders_then_a_sweep(self, usdt):
        edges = self.inflows("abcde") + [("9", "8", 450, 60)]

        [signal] = self.signals(usdt, edges)

        assert signal.heuristic == "collection_wallet"
        assert signal.confidence == "low"
        assert "5 distinct senders" in signal.explanation
        assert "90% of it onward in 1 transfer" in signal.explanation
        assert signal.transfers.count() == 6

    def test_many_more_senders_raise_confidence(self, usdt):
        senders = [f"a{i}" for i in range(10)] + [f"b{i}" for i in range(5)]  # 15 distinct
        edges = self.inflows(senders) + [("9", "8", 1500, 60)]

        [signal] = self.signals(usdt, edges)

        assert signal.confidence == "medium"

    @pytest.mark.parametrize(
        "edges",
        [
            pytest.param([*("abcd"), ("9", "8", 400, 60)], id="too-few-senders"),
            pytest.param([*("abcde"), ("9", "8", 300, 60)], id="most-of-it-stays"),
            pytest.param([*("abcde"), ("9", "8", 500, 60 * 30)], id="sweep-too-late"),
            pytest.param([*("abcde"), ("9", "8", 500, 5)], id="sweep-before-inflows"),
        ],
    )
    def test_does_not_fire_without_the_full_pattern(self, usdt, edges):
        senders = [e for e in edges if isinstance(e, str)]
        sweeps = [e for e in edges if not isinstance(e, str)]

        assert self.signals(usdt, self.inflows(senders) + sweeps) == []

    def test_reevaluation_clears_a_signal_that_no_longer_holds(self, usdt, monkeypatch):
        run, _ = trace(
            usdt, self.inflows("abcde") + [("9", "8", 450, 60)], seeds=("9",), max_hops=1
        )
        assert node(run, "9").signals.exists()

        monkeypatch.setattr(CollectionWallet, "MIN_SENDERS", 6)
        evaluate_run(run)

        assert not node(run, "9").signals.exists()

    def test_signals_reach_the_graph(self, usdt):
        run, _ = trace(
            usdt, self.inflows("abcde") + [("9", "8", 450, 60)], seeds=("9",), max_hops=1
        )

        hub = next(n for n in build_graph(run)["nodes"] if n["id"] == addr("9"))

        assert hub["signals"][0]["name"] == "Collection wallet pattern"
