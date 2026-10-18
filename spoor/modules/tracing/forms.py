from decimal import Decimal

from django import forms

from spoor.common.functions import to_raw
from spoor.modules.cases.models import Case
from spoor.modules.chains.addresses import is_tx_hash
from spoor.modules.chains.forms import AddressTransfersForm
from spoor.modules.tracing.enums import TraceDirection


class StartTraceForm(AddressTransfersForm):
    """The address-and-window form plus the trace parameters."""

    case = forms.ModelChoiceField(
        queryset=Case.objects.order_by("-created_at"), required=False, empty_label="No case"
    )
    direction = forms.ChoiceField(choices=TraceDirection.choices, initial=TraceDirection.FORWARD)
    max_hops = forms.IntegerField(min_value=1, max_value=10, initial=3)
    fan_out = forms.IntegerField(
        min_value=1, max_value=20, initial=5, help_text="Largest transfers followed per address."
    )
    min_amount = forms.DecimalField(
        min_value=Decimal(0), initial=Decimal(0), label="Min amount (token units)"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].label = "Seed address or transaction hash"

    def clean_target(self, cleaned, token, value):
        """A transaction hash seeds the trace from that transaction's transfers."""
        cleaned["seed_tx_hash"] = ""
        if is_tx_hash(value):
            cleaned["seed_tx_hash"] = token.chain.normalize_tx_hash(value)
            cleaned["address"] = None
        else:
            super().clean_target(cleaned, token, value)

    def clean(self):
        cleaned = super().clean()
        token, min_amount = cleaned.get("token"), cleaned.get("min_amount")
        if token and min_amount is not None:
            try:
                cleaned["min_amount_raw"] = to_raw(min_amount, token.decimals)
            except ValueError:
                self.add_error("min_amount", f"{token.symbol} has {token.decimals} decimals.")
        return cleaned
