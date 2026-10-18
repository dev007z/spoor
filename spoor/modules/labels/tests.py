import json
from pathlib import Path

import pytest
from django.db import IntegrityError

from spoor.modules.chains.models import Address, Chain
from spoor.modules.labels.datasets import DatasetFileError, load_dataset_file
from spoor.modules.labels.enums import DatasetVisibility, LabelCategory, LabelConfidence
from spoor.modules.labels.models import Label, LabelDataset
from spoor.modules.labels.ofac import import_publication, parse_sdn


@pytest.mark.django_db
class TestLabels:
    @pytest.fixture
    def address(self):
        return Address.resolve(Chain.get_chain(key="ethereum"), "0x" + "3" * 40)

    def make_label(self, dataset, address, entity="Example Exchange"):
        return Label.objects.create(
            dataset=dataset,
            address=address,
            entity=entity,
            category=LabelCategory.EXCHANGE,
            confidence=LabelConfidence.HIGH,
            source_url="https://example.test/disclosure",
        )

    def test_datasets_are_public_by_default(self):
        dataset = LabelDataset.objects.create(key="public-reports", name="Public reports")
        assert dataset.visibility == DatasetVisibility.PUBLIC

    def test_one_label_per_address_within_a_dataset(self, address):
        dataset = LabelDataset.objects.create(key="ofac-sdn", name="OFAC SDN")
        self.make_label(dataset, address)

        with pytest.raises(IntegrityError):
            self.make_label(dataset, address, entity="Duplicate")

    def test_datasets_can_label_the_same_address_independently(self, address):
        """Two sources agreeing (or disagreeing) about one address are both kept."""
        first = LabelDataset.objects.create(key="first", name="First")
        second = LabelDataset.objects.create(key="second", name="Second")

        self.make_label(first, address)
        self.make_label(second, address)

        assert address.labels.count() == 2

    def test_best_label_prefers_higher_confidence(self, address):
        weak = LabelDataset.objects.create(key="weak", name="Weak")
        strong = LabelDataset.objects.create(key="strong", name="Strong")
        Label.objects.create(
            dataset=weak,
            address=address,
            entity="Guess",
            category=LabelCategory.OTHER,
            confidence=LabelConfidence.LOW,
            source_url="https://example.test/a",
        )
        Label.objects.create(
            dataset=strong,
            address=address,
            entity="Known Exchange",
            category=LabelCategory.EXCHANGE,
            confidence=LabelConfidence.HIGH,
            source_url="https://example.test/b",
        )

        best = Label.best_for_addresses([address.id])

        assert best[address.id].entity == "Known Exchange"


EXCERPT = Path(__file__).resolve().parent / "fixtures" / "ofac_sdn_excerpt.xml"


@pytest.fixture(scope="module")
def publication():
    return parse_sdn(EXCERPT)


class TestSdnParsing:
    """Against a real excerpt of SDN.XML (published 10/15/2026), cut to 7 entries."""

    def keyed(self, publication):
        return {(a.chain_key, a.address) for a in publication.addresses}

    def test_reads_the_publish_date(self, publication):
        assert publication.publish_date == "10/15/2026"

    def test_trx_addresses_are_tron_only(self, publication):
        keys = self.keyed(publication)
        assert ("tron", "TNiq9AXBp9EjUqhDhrwrfvAA8U3GUQZH81") in keys
        assert not any(
            a.address == "TNiq9AXBp9EjUqhDhrwrfvAA8U3GUQZH81" and a.chain_key != "tron"
            for a in publication.addresses
        )

    def test_evm_addresses_are_labeled_on_every_evm_chain(self, publication):
        keys = self.keyed(publication)
        address = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
        assert {("ethereum", address), ("bsc", address)} <= keys

    def test_usdt_is_routed_by_address_format(self, publication):
        keys = self.keyed(publication)
        assert ("tron", "TA3941uFAvmVibSkQ6fMJXxmaSNovX86mz") in keys
        assert ("bsc", "0x2f389ce8bd8ff92de3402ffce4691d17fc4f6535") in keys
        assert not any(
            a.address == "1KUUJPkyDhamZXgpsyXqNGc3x1QPXtdhgz" for a in publication.addresses
        )

    def test_untraced_currencies_are_counted_not_imported(self, publication):
        assert publication.skipped_currencies["ARB"] == 1
        assert publication.skipped_currencies["USDT"] == 5  # Omni addresses
        assert publication.skipped_currencies["XBT"] > 0

    def test_each_address_cites_its_sdn_entry(self, publication):
        tron = next(a for a in publication.addresses if a.address.startswith("TNiq9"))
        assert tron.source_url == "https://sanctionssearch.ofac.treas.gov/Details.aspx?id=4632"
        assert tron.entity == "BANK MARKAZI JOMHOURI ISLAMI IRAN"


@pytest.mark.django_db
class TestOfacImport:
    def test_imports_every_supported_address_once(self):
        summary = import_publication(parse_sdn(EXCERPT))

        # 65 TRON addresses + 18 unique EVM addresses on 2 EVM chains.
        assert summary.labels == 101
        dataset = LabelDataset.objects.get(key="ofac-sdn")
        assert dataset.labels.count() == 101
        assert set(dataset.labels.values_list("category", flat=True)) == {LabelCategory.SANCTIONED}
        assert "10/15/2026" in dataset.description

    def test_reimport_is_idempotent_and_delisting_removes_labels(self):
        publication = parse_sdn(EXCERPT)
        import_publication(publication)
        import_publication(publication)
        assert Label.objects.count() == 101

        publication.addresses = [a for a in publication.addresses if "4632" not in a.source_url]
        import_publication(publication)

        assert Label.objects.count() == 95
        assert not Label.objects.filter(source_url__endswith="id=4632").exists()


@pytest.mark.django_db
class TestDatasetFiles:
    def write(self, tmp_path, labels, **overrides):
        path = tmp_path / "dataset.json"
        path.write_text(
            json.dumps({"key": "test-set", "name": "Test set", "labels": labels, **overrides})
        )
        return path

    def entry(self, **overrides):
        return {
            "chain": "bsc",
            "address": "0x" + "AB" * 20,
            "entity": "Example Exchange",
            "category": "exchange",
            "confidence": "high",
            "source_url": "https://example.test/disclosure",
            **overrides,
        }

    def test_valid_file_loads_with_canonical_addresses(self, tmp_path):
        dataset, count = load_dataset_file(self.write(tmp_path, [self.entry()]))

        assert count == 1
        assert dataset.labels.get().address.address == "0x" + "ab" * 20

    @pytest.mark.parametrize(
        ("override", "message"),
        [
            ({"category": "whale"}, "unknown category"),
            ({"confidence": "certain"}, "unknown confidence"),
            ({"chain": "solana"}, "unknown chain"),
            ({"source_url": "http://example.test"}, "https link"),
            ({"source_url": ""}, "missing source_url"),
            ({"address": "0x1234"}, "Not an EVM address"),
        ],
    )
    def test_a_bad_entry_rejects_the_whole_file(self, tmp_path, override, message):
        path = self.write(tmp_path, [self.entry(address="0x" + "cd" * 20), self.entry(**override)])

        with pytest.raises(DatasetFileError, match=message):
            load_dataset_file(path)
        assert not LabelDataset.objects.exists()

    def test_removed_entries_are_unlabeled_on_reload(self, tmp_path):
        load_dataset_file(
            self.write(tmp_path, [self.entry(), self.entry(address="0x" + "cd" * 20)])
        )

        load_dataset_file(self.write(tmp_path, [self.entry()]))

        assert Label.objects.count() == 1


@pytest.mark.django_db
class TestLabelsPage:
    def test_search_matches_address_or_entity(self, admin_client):
        import_publication(parse_sdn(EXCERPT))

        by_entity = admin_client.get("/labels/", {"q": "markazi"})
        by_address = admin_client.get("/labels/", {"q": "TA3941uF"})

        assert by_entity.context["page"].paginator.count == 6
        assert by_address.context["page"].paginator.count == 1
