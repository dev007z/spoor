from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from spoor.modules.cases.enums import CaseEventType
from spoor.modules.cases.models import CaseEvent
from spoor.modules.tracing.forms import StartTraceForm
from spoor.modules.tracing.models import TraceRun
from spoor.modules.tracing.summary import summarize_run
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
            seed_addresses=[data["address"]] if data["address"] else [],
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
        context = summarize_run(run)
        context["reports"] = (
            run.reports.select_related("created_by").defer("html", "pdf").order_by("-created_at")
        )
        return render(request, template or self.template_name, context)
