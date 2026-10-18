from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from spoor.modules.chains.adapters.base import AdapterError
from spoor.modules.contracts.analysis import analyze_contract
from spoor.modules.contracts.forms import ContractLookupForm
from spoor.modules.contracts.models import Contract
from spoor.modules.contracts.services import fetch_contract


class ContractListView(View):
    """Look up a contract, and the contracts fetched so far."""

    template_name = "contracts/contract_list.html"

    def get(self, request):
        return self.render(request, ContractLookupForm())

    def post(self, request):
        form = ContractLookupForm(request.POST)
        if not form.is_valid():
            return self.render(request, form)
        try:
            contract = fetch_contract(form.cleaned_data["chain"], form.cleaned_data["address"])
        except AdapterError as exc:
            return self.render(request, form, error=str(exc))
        return redirect("contracts:contract_detail", pk=contract.pk)

    def render(self, request, form, error=None):
        contracts = Contract.objects.select_related("address__chain").order_by("-updated_at")[:50]
        context = {"form": form, "contracts": contracts, "error": error}
        return render(request, self.template_name, context)


class ContractDetailView(View):
    template_name = "contracts/contract_detail.html"

    def get(self, request, pk):
        contract = get_object_or_404(
            Contract.objects.select_related("address__chain", "raw_response"), pk=pk
        )
        analysis = analyze_contract(contract)
        implementation = analysis.logic if analysis.logic != contract else None
        functions = sorted(
            analysis.logic.abi_functions(),
            key=lambda f: (f.get("stateMutability") in ("view", "pure"), f.get("name", "")),
        )
        context = {
            "contract": contract,
            "implementation": implementation,
            "analysis": analysis,
            "functions": functions,
            "explorer_url": contract.chain.address_url(contract.address.address),
        }
        return render(request, self.template_name, context)
