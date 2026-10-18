from django.urls import path

from spoor.modules.cases.views import CaseDetailView, CaseListView

app_name = "cases"

urlpatterns = [
    path("cases/", CaseListView.as_view(), name="case_list"),
    path("cases/<uuid:pk>/", CaseDetailView.as_view(), name="case_detail"),
]
