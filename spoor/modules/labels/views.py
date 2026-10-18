from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.views import View

from spoor.modules.labels.forms import LabelFilterForm
from spoor.modules.labels.models import Label, LabelDataset

PAGE_SIZE = 50


class LabelListView(View):
    template_name = "labels/label_list.html"

    def get(self, request):
        form = LabelFilterForm(request.GET or None)
        conditions = Q()
        if form.is_valid():
            data = form.cleaned_data
            if data["q"]:
                conditions &= Q(address__address__icontains=data["q"].strip()) | Q(
                    entity__icontains=data["q"].strip()
                )
            if data["dataset"]:
                conditions &= Q(dataset=data["dataset"])
            if data["category"]:
                conditions &= Q(category=data["category"])
            if data["chain"]:
                conditions &= Q(address__chain=data["chain"])

        page = Paginator(Label.fetch_labels(conditions), PAGE_SIZE).get_page(
            request.GET.get("page")
        )
        query = request.GET.copy()
        query.pop("page", None)
        context = {
            "form": form,
            "page": page,
            "query": query.urlencode(),
            "datasets": LabelDataset.objects.annotate(count=Count("labels")).order_by("name"),
        }
        return render(request, self.template_name, context)
