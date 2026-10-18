from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from django.views import View

from spoor.modules.chains.forms import AddressTransfersForm
from spoor.modules.chains.services import fetch_address_transfers
from spoor.modules.screening.exposure import screen_address


class ScreeningView(View):
    """Screen an address: GET uses stored transfers, POST fetches the window first."""

    template_name = "screening/screening.html"
    body_template_name = "screening/_screening_body.html"

    def get(self, request):
        form = AddressTransfersForm(request.GET or None)
        context = {"form": form}
        if form.is_valid():
            context.update(self.screen(form.cleaned_data))
        return render(request, self.template_name, context)

    def post(self, request):
        form = AddressTransfersForm(request.POST)
        context = {"form": form}
        if form.is_valid():
            data = form.cleaned_data
            context.update(
                fetch_address_transfers(data["token"], data["address"], data["start"], data["end"])
            )
            context.update(self.screen(data))

        if not request.headers.get("HX-Request"):
            return render(request, self.template_name, context)
        response = render(request, self.body_template_name, context)
        if form.is_valid():
            query = urlencode({k: request.POST[k] for k in ("token", "address", "start", "end")})
            response["HX-Push-Url"] = f"{reverse('screening:screen')}?{query}"
        return response

    @staticmethod
    def screen(data):
        token = data["token"]
        result = screen_address(token, data["address"], data["start"], data["end"])
        trace_query = urlencode(
            {
                "token": token.pk,
                "address": data["address"],
                "start": f"{data['start']:%Y-%m-%dT%H:%M}",
                "end": f"{data['end']:%Y-%m-%dT%H:%M}",
            }
        )
        return {
            "result": result,
            "token": token,
            "chain": token.chain,
            "trace_url": f"{reverse('tracing:trace_list')}?{trace_query}",
        }
