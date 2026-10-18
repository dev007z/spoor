from datetime import UTC, datetime

import pytest

from spoor.modules.chains.adapters.base import FetchResult
from spoor.modules.chains.models import Address, RawResponse, Token, Transfer
from spoor.modules.labels.enums import LabelCategory, LabelConfidence
from spoor.modules.labels.models import Label, LabelDataset
from spoor.modules.screening.exposure import screen_address, trace_exposure
from spoor.modules.tracing.engine import TraceEngine
from spoor.modules.tracing.models import TraceRun

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 2, tzinfo=UTC)


def evm(name):
    return "0x" + name * 40


@pytest.fixture
def usdt():
    return Token.objects.get(chain__key="bsc", symbol="USDT")


@pytest.fixture
def world(usdt):
    """Subject s dealt with a sanctioned address, an exchange, and an unlabeled one."""
    chain = usdt.chain
    raw = RawResponse.record(
        source="test", endpoint="https://x.test", params={}, status_code=200, body="{}"
    )
    dataset = LabelDataset.objects.create(key="test", name="Test")

    def label(name, category, entity):
        Label.objects.create(
            dataset=dataset,
            address=Address.resolve(chain, evm(name)),
            entity=entity,
            category=category,
            confidence=LabelConfidence.HIGH,
            source_url="https://example.test",
        )

    label("e", LabelCategory.EXCHANGE, "Example Exchange")
    label("b", LabelCategory.SANCTIONED, "Sanctioned Group")

    def transfer(index, sender, receiver, amount):
        Transfer.objects.create(
            chain=chain,
            token=usdt,
            tx_hash="0x" + format(index, "064x"),
            log_index=0,
            block_number=index,
            timestamp=START.replace(hour=index),
            from_address=Address.resolve(chain, evm(sender)),
            to_address=Address.resolve(chain, evm(receiver)),
            amount=amount,
            raw_response=raw,
        )

    transfer(1, "b", "a", 5 * 10**18)  # a received 5 USDT from the sanctioned address
    transfer(2, "a", "e", 3 * 10**18)
    transfer(3, "a", "c", 1 * 10**18)
    return {"label": label}


@pytest.mark.django_db
class TestScreenAddress:
    def test_labeled_counterparties_most_serious_first(self, usdt, world):
        result = screen_address(usdt, evm("a"), START, END)

        assert result.verdict == "indirect"
        assert [e.label.entity for e in result.counterparties] == [
            "Sanctioned Group",
            "Example Exchange",
        ]
        sanctioned = result.counterparties[0]
        assert str(sanctioned.received_from) == "5.000000000000000000"
        assert result.counterparty_count == 3
        assert result.transfer_count == 3

    def test_a_labeled_address_is_a_direct_match(self, usdt, world):
        world["label"]("a", LabelCategory.SCAM, "Reported scam wallet")

        result = screen_address(usdt, evm("a"), START, END)

        assert result.verdict == "direct"
        assert result.direct_labels[0].entity == "Reported scam wallet"

    def test_window_bounds_what_counts(self, usdt, world):
        result = screen_address(usdt, evm("a"), START.replace(hour=2), END)

        assert [e.label.entity for e in result.counterparties] == ["Example Exchange"]

    def test_unknown_address_has_no_exposure(self, usdt):
        result = screen_address(usdt, evm("f"), START, END)

        assert result.verdict == "none"
        assert result.transfer_count == 0


@pytest.mark.django_db
class TestScreeningPage:
    def test_get_screens_stored_transfers(self, admin_client, usdt, world):
        response = admin_client.get(
            "/screening/",
            {
                "token": usdt.pk,
                "address": evm("a"),
                "start": "2026-01-01T00:00",
                "end": "2026-01-02T00:00",
            },
        )

        assert response.context["result"].verdict == "indirect"
        assert response.context["trace_url"].startswith("/traces/?")

    def test_post_fetches_then_screens(self, admin_client, usdt, world, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            "spoor.modules.screening.views.fetch_address_transfers",
            lambda *args: fetched.append(args) or {"fetched": 0, "fetch_complete": True},
        )

        response = admin_client.post(
            "/screening/",
            {
                "token": usdt.pk,
                "address": evm("a"),
                "start": "2026-01-01T00:00",
                "end": "2026-01-02T00:00",
            },
            HTTP_HX_REQUEST="true",
        )

        assert len(fetched) == 1
        assert response.templates[0].name == "screening/_screening_body.html"
        assert response["HX-Push-Url"].startswith("/screening/?")


@pytest.mark.django_db
class TestTraceExposure:
    def test_lists_labeled_addresses_reached_with_amounts(self, usdt, world):
        class StoredOnly:
            def get_token_transfers(self, *args):
                return FetchResult(records=[], complete=True)

        run = TraceRun.objects.create(token=usdt, start=START, end=END)
        run.seeds.set([Address.resolve(usdt.chain, evm("a"))])
        TraceEngine(run, StoredOnly()).execute()

        rows = trace_exposure(run)

        assert [(r["label"].entity, r["node"].hop) for r in rows] == [("Example Exchange", 1)]
        assert str(rows[0]["received"]) == "3.000000000000000000"
