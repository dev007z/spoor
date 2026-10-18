from django import forms

from spoor.modules.chains.addresses import InvalidAddressError
from spoor.modules.chains.enums import ChainFamily
from spoor.modules.chains.models import Chain, Token
from spoor.modules.tracing.forms import StartTraceForm


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


class TraceDeployerForm(StartTraceForm):
    """Trace from the contract's deployer and owner wallets, plus any the analyst adds."""

    address = None
    extra_wallets = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
        label="Other wallets",
        help_text="One per line, e.g. a deployer found on an explorer.",
    )

    def __init__(self, *args, contract, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract
        self.fields["token"].queryset = Token.objects.filter(chain=contract.chain)

    def clean_extra_wallets(self):
        wallets = []
        for line in self.cleaned_data["extra_wallets"].split():
            try:
                wallets.append(self.contract.chain.normalize_address(line))
            except InvalidAddressError as exc:
                raise forms.ValidationError(
                    f"Not a valid {self.contract.chain.name} address: {line}"
                ) from exc
        return wallets
