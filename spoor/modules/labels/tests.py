import pytest
from django.db import IntegrityError

from spoor.modules.chains.models import Address, Chain
from spoor.modules.labels.enums import DatasetVisibility, LabelCategory, LabelConfidence
from spoor.modules.labels.models import Label, LabelDataset


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
