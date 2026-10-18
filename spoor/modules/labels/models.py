from django.db import models

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
