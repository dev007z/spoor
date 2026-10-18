from datetime import timedelta

from django import forms

from spoor.modules.chains.addresses import InvalidAddressError
from spoor.modules.chains.models import Token

MAX_WINDOW = timedelta(days=31)


class TokenChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, token):
        return f"{token.symbol} on {token.chain.name}"


class AddressTransfersForm(forms.Form):
    """An address, the token to follow, and a UTC time window. The token implies the chain."""

    token = TokenChoiceField(
        queryset=Token.objects.select_related("chain").order_by("chain__name"), empty_label=None
    )
    address = forms.CharField(max_length=100)
    start = forms.DateTimeField(
        label="From (UTC)", widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    end = forms.DateTimeField(
        label="To (UTC)", widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )

    def clean(self):
        cleaned = super().clean()
        token, address = cleaned.get("token"), cleaned.get("address")
        if token and address:
            try:
                cleaned["address"] = token.chain.normalize_address(address)
            except InvalidAddressError:
                self.add_error("address", f"Not a valid {token.chain.name} address.")

        start, end = cleaned.get("start"), cleaned.get("end")
        if start and end:
            if start >= end:
                self.add_error("end", "Must be after the start.")
            elif end - start > MAX_WINDOW:
                self.add_error("end", "The window can be at most 31 days.")
        return cleaned
