import json
from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView

from spoor.common.functions import to_units
from spoor.modules.chains.forms import AddressTransfersForm
from spoor.modules.chains.models import Address, RawResponse, Transfer
from spoor.modules.chains.services import fetch_address_transfers


class AddressTransfersView(View):
    """Look up an address's token transfers: GET shows stored ones, POST fetches from the chain."""

    template_name = "chains/address_transfers.html"
    body_template_name = "chains/_transfers_body.html"

    def get(self, request):
        form = AddressTransfersForm(request.GET or None)
        context = {"form": form}
        if form.is_valid():
            context.update(self.results_context(form.cleaned_data))
        return render(request, self.template_name, context)

    def post(self, request):
        form = AddressTransfersForm(request.POST)
        context = {"form": form}
        if form.is_valid():
            data = form.cleaned_data
            context.update(
                fetch_address_transfers(data["token"], data["address"], data["start"], data["end"])
            )
            context.update(self.results_context(form.cleaned_data))

        if not request.headers.get("HX-Request"):
            return render(request, self.template_name, context)

        response = render(request, self.body_template_name, context)
        if form.is_valid():
            query = urlencode({k: request.POST[k] for k in ("token", "address", "start", "end")})
            response["HX-Push-Url"] = f"{reverse('chains:address_transfers')}?{query}"
        return response

    def results_context(self, data):
        token, chain = data["token"], data["token"].chain
        address = Address.objects.filter(chain=chain, address=data["address"]).first()
        transfers = Transfer.fetch_for_address(address, token, data["start"], data["end"])

        rows, total_in, total_out, counterparties = [], 0, 0, set()
        for transfer in transfers if address else []:
            incoming = transfer.to_address_id == address.id
            counterparty = (transfer.from_address if incoming else transfer.to_address).address
            if incoming:
                total_in += transfer.amount
            else:
                total_out += transfer.amount
            counterparties.add(counterparty)
            rows.append(
                {
                    "transfer": transfer,
                    "incoming": incoming,
                    "counterparty": counterparty,
                    "counterparty_url": chain.address_url(counterparty),
                    "tx_url": chain.tx_url(transfer.tx_hash),
                }
            )

        return {
            "token": token,
            "rows": rows,
            "stats": {
                "count": len(rows),
                "total_in": to_units(total_in, token.decimals),
                "total_out": to_units(total_out, token.decimals),
                "counterparties": len(counterparties),
            },
        }


class EvidenceView(DetailView):
    """One stored provider response: what was asked, when, and exactly what came back."""

    model = RawResponse
    template_name = "chains/evidence.html"
    context_object_name = "evidence"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context["pretty_body"] = json.dumps(json.loads(self.object.body), indent=2)
        except json.JSONDecodeError:
            context["pretty_body"] = self.object.body
        return context
