from django import forms

from spoor.modules.chains.addresses import InvalidAddressError
from spoor.modules.chains.enums import ChainFamily
from spoor.modules.chains.models import Chain


class ContractLookupForm(forms.Form):
    chain = forms.ModelChoiceField(
        queryset=Chain.objects.filter(family=ChainFamily.EVM).order_by("name"), empty_label=None
    )
    address = forms.CharField(max_length=100, label="Contract address")

    def clean(self):
        cleaned = super().clean()
        chain, address = cleaned.get("chain"), cleaned.get("address")
        if chain and address:
            try:
                cleaned["address"] = chain.normalize_address(address)
            except InvalidAddressError:
                self.add_error("address", f"Not a valid {chain.name} address.")
        return cleaned
