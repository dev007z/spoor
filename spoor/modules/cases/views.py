from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from spoor.modules.cases.forms import CaseForm
from spoor.modules.cases.models import AddressNote, Case


class CaseListView(View):
    """All cases, and the form that opens a new one."""

    template_name = "cases/case_list.html"

    def get(self, request):
        return self.render(request, CaseForm())

    def post(self, request):
        form = CaseForm(request.POST)
        if not form.is_valid():
            return self.render(request, form)
        case = Case.create_case(request.user, **form.cleaned_data)
        return redirect("cases:case_detail", pk=case.pk)

    def render(self, request, form):
        return render(request, self.template_name, {"form": form, "cases": Case.fetch_cases()})


class CaseDetailView(View):
    template_name = "cases/case_detail.html"

    def get(self, request, pk):
        case = get_object_or_404(Case.objects.select_related("created_by"), pk=pk)
        context = {
            "case": case,
            "runs": case.trace_runs.select_related("token__chain")
            .prefetch_related("seeds")
            .order_by("-created_at"),
            "events": case.fetch_events()[:100],
            "notes": [
                {"note": note, "url": note.address.chain.address_url(note.address.address)}
                for note in AddressNote.fetch_notes(case)
            ],
        }
        return render(request, self.template_name, context)
