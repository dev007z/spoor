from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from spoor.common.functions import to_units
from spoor.modules.cases.enums import CaseEventType
from spoor.modules.cases.models import CaseEvent
from spoor.modules.tracing.enums import StopReason
from spoor.modules.tracing.forms import StartTraceForm
from spoor.modules.tracing.models import TraceRun
from spoor.modules.tracing.tasks import run_trace


class TraceListView(View):
    """Recent traces, and the form that starts a new one."""

    template_name = "tracing/trace_list.html"

    def get(self, request):
        return self.render(request, StartTraceForm(initial={"case": request.GET.get("case")}))

    def post(self, request):
        form = StartTraceForm(request.POST)
        if not form.is_valid():
            return self.render(request, form)

        data = form.cleaned_data
        run = TraceRun.create_run(
            data["token"],
            case=data["case"],
            created_by=request.user,
            seed_address=data["address"],
            seed_tx_hash=data["seed_tx_hash"],
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
                f"Started a {run.direction} {run.token.symbol} trace on {run.chain.name}.",
                trace_run=str(run.pk),
            )
        transaction.on_commit(lambda: run_trace.delay(str(run.pk)))
        return redirect("tracing:trace_detail", pk=run.pk)

    def render(self, request, form):
        context = {"form": form, "runs": TraceRun.fetch_runs()[:50]}
        return render(request, self.template_name, context)


class TraceDetailView(View):
    """One trace. While it runs, htmx polls the body partial until the run finishes."""

    template_name = "tracing/trace_detail.html"
    body_template_name = "tracing/_trace_body.html"

    def get(self, request, pk):
        run = get_object_or_404(TraceRun.objects.select_related("token__chain", "case"), pk=pk)
        template = self.body_template_name if request.headers.get("HX-Request") else None
        return render(request, template or self.template_name, trace_context(run))


def trace_context(run):
    nodes = list(run.fetch_nodes())
    edges = list(run.fetch_edges())
    chain, token = run.chain, run.token

    flows = {}
    for edge in edges:
        transfer = edge.transfer
        for address_id, key in ((transfer.from_address_id, "out"), (transfer.to_address_id, "in")):
            flows.setdefault(address_id, {"in": 0, "out": 0})[key] += transfer.amount

    node_rows = [
        {
            "node": node,
            "url": chain.address_url(node.address.address),
            "received": to_units(flows.get(node.address_id, {}).get("in", 0), token.decimals),
            "sent": to_units(flows.get(node.address_id, {}).get("out", 0), token.decimals),
        }
        for node in nodes
    ]
    edge_rows = [
        {"edge": edge, "transfer": edge.transfer, "tx_url": chain.tx_url(edge.transfer.tx_hash)}
        for edge in edges
    ]
    return {
        "run": run,
        "seeds": list(run.seeds.all()),
        "seed_tx_url": chain.tx_url(run.seed_tx_hash) if run.seed_tx_hash else None,
        "min_amount_units": to_units(run.min_amount, token.decimals),
        "node_rows": node_rows,
        "edge_rows": edge_rows,
        "stats": {
            "addresses": len(nodes),
            "transfers": len(edges),
            "endpoints": sum(n.stop_reason == StopReason.LABELED_ENDPOINT for n in nodes),
        },
    }
