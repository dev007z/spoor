from django.contrib.auth.decorators import login_not_required
from django.urls import path

from spoor.modules.cases.api import AddressNotesApi
from spoor.modules.cases.views import CaseDetailView, CaseListView

app_name = "cases"

urlpatterns = [
    path("cases/", CaseListView.as_view(), name="case_list"),
    path("cases/<uuid:pk>/", CaseDetailView.as_view(), name="case_detail"),
    path(
        "api/v1/cases/<uuid:pk>/notes/",
        login_not_required(AddressNotesApi.as_view()),
        name="address_notes",
    ),
]
