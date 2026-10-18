from django.db import models, transaction

from spoor.common.mixins import ModelMixin
from spoor.modules.chains.models import Address
from spoor.modules.labels.enums import DatasetVisibility, LabelCategory, LabelConfidence


class LabelDataset(ModelMixin):
    """A named, separately sourced collection of labels, such as the OFAC SDN list."""

    key = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    visibility = models.CharField(
        max_length=10, choices=DatasetVisibility.choices, default=DatasetVisibility.PUBLIC
    )

    def __str__(self):
        return self.name

    @classmethod
    def sync(cls, key, name, entries, description="", visibility=DatasetVisibility.PUBLIC):
        """Make the dataset hold exactly `entries`, adding, updating and removing labels.

        Each entry is a dict with chain (a Chain), address (canonical), entity, category,
        confidence and source_url. Re-running with the same entries changes nothing.
        """
        with transaction.atomic():
            dataset, _ = cls.objects.update_or_create(
                key=key,
                defaults={"name": name, "description": description, "visibility": visibility},
            )
            wanted = {}
            for entry in entries:
                address = Address.resolve(entry["chain"], entry["address"])
                wanted[address.id] = entry
            dataset.labels.exclude(address_id__in=wanted).delete()
            for address_id, entry in wanted.items():
                Label.objects.update_or_create(
                    dataset=dataset,
                    address_id=address_id,
                    defaults={
                        field: entry[field]
                        for field in ("entity", "category", "confidence", "source_url")
                    },
                )
        return dataset, len(wanted)


class Label(ModelMixin):
    """A sourced claim that an address belongs to an entity. Entities only, never individuals."""

    dataset = models.ForeignKey(LabelDataset, on_delete=models.CASCADE, related_name="labels")
    address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name="labels")
    entity = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=LabelCategory.choices)
    confidence = models.CharField(max_length=10, choices=LabelConfidence.choices)
    source_url = models.URLField(max_length=500)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset", "address"], name="unique_label_per_dataset"),
        ]

    def __str__(self):
        return f"{self.entity} ({self.category})"

    @classmethod
    def fetch_labels(cls, conditions):
        return (
            cls.objects.filter(conditions)
            .select_related("dataset", "address__chain")
            .order_by("dataset__name", "entity", "address__address")
        )

    @classmethod
    def best_for_addresses(cls, address_ids):
        """{address_id: label} keeping the highest-confidence label when datasets overlap."""
        rank = {LabelConfidence.HIGH: 0, LabelConfidence.MEDIUM: 1, LabelConfidence.LOW: 2}
        best = {}
        for label in cls.objects.filter(address_id__in=address_ids).select_related("dataset"):
            current = best.get(label.address_id)
            if current is None or rank[label.confidence] < rank[current.confidence]:
                best[label.address_id] = label
        return best
