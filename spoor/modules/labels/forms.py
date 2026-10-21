from django import forms

from spoor.modules.chains.models import Chain
from spoor.modules.labels.enums import LabelCategory
from spoor.modules.labels.models import LabelDataset


class LabelFilterForm(forms.Form):
    """Whitelisted filters for the labels list."""

    q = forms.CharField(required=False, label="Address or entity")
    dataset = forms.ModelChoiceField(
        queryset=LabelDataset.objects.order_by("name"), required=False, empty_label="All datasets"
    )
    category = forms.ChoiceField(
        choices=[("", "All categories"), *LabelCategory.choices], required=False
    )
    chain = forms.ModelChoiceField(
        queryset=Chain.objects.order_by("name"), required=False, empty_label="All chains"
    )
