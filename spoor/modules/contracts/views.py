from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from spoor.modules.cases.enums import CaseEventType
from spoor.modules.cases.models import CaseEvent
from spoor.modules.chains.adapters.base import AdapterError
from spoor.modules.contracts.analysis import analyze_contract
from spoor.modules.contracts.forms import ContractLookupForm, TraceDeployerForm
from spoor.modules.contracts.liquidity import controllers
from spoor.modules.contracts.models import Contract
from spoor.modules.contracts.services import fetch_contract
from spoor.modules.tracing.models import TraceRun
from spoor.modules.tracing.tasks import run_trace


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
        return self.render(request, contract)

    def render(self, request, contract, trace_form=None):
        analysis = analyze_contract(contract)
        implementation = analysis.logic if analysis.logic != contract else None
        functions = sorted(
            analysis.logic.abi_functions(),
            key=lambda f: (f.get("stateMutability") in ("view", "pure"), f.get("name", "")),
        )
        if trace_form is None:
            now = timezone.now().replace(second=0, microsecond=0)
            trace_form = TraceDeployerForm(
                contract=contract,
                initial={"start": now - timedelta(days=1), "end": now, "max_hops": 3},
            )
        owner = analysis.ownership.owner if analysis.ownership else None
        context = {
            "contract": contract,
            "implementation": implementation,
            "analysis": analysis,
            "functions": functions,
            "controllers": controllers(contract, owner),
            "trace_form": trace_form,
            "explorer_url": contract.chain.address_url(contract.address.address),
        }
        return render(request, self.template_name, context)


class TraceDeployerView(View):
    """Start a trace seeded with the deployer and owner wallets of a contract."""

    def post(self, request, pk):
        contract = get_object_or_404(Contract.objects.select_related("address__chain"), pk=pk)
        form = TraceDeployerForm(request.POST, contract=contract)
        if not form.is_valid():
            return ContractDetailView().render(request, contract, trace_form=form)

        analysis = analyze_contract(contract)
        owner = analysis.ownership.owner if analysis.ownership else None
        seeds = list(
            dict.fromkeys([*controllers(contract, owner), *form.cleaned_data["extra_wallets"]])
        )
        if not seeds:
            form.add_error(
                "extra_wallets", "No deployer or owner is known for this contract; add a wallet."
            )
            return ContractDetailView().render(request, contract, trace_form=form)

        data = form.cleaned_data
        run = TraceRun.create_run(
            data["token"],
            seed_addresses=seeds,
            case=data["case"],
            created_by=request.user,
            direction=data["direction"],
            start=data["start"],
            end=data["end"],
            max_hops=data["max_hops"],
            fan_out=data["fan_out"],
            min_amount=data["min_amount_raw"],
        )
        if run.case:
            CaseEvent.record(
                run.case,
                request.user,
                CaseEventType.TRACE_STARTED,
                f"Started tracing the deployer of {contract.name or contract.address.address}.",
                trace_run=str(run.pk),
                contract=contract.address.address,
            )
        transaction.on_commit(lambda: run_trace.delay(str(run.pk)))
        return redirect("tracing:trace_detail", pk=run.pk)
