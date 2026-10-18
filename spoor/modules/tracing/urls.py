from django.contrib.auth.decorators import login_not_required
from django.urls import path

from spoor.modules.tracing.api import TraceGraphApi
from spoor.modules.tracing.views import TraceDetailView, TraceListView

app_name = "tracing"

urlpatterns = [
    path("traces/", TraceListView.as_view(), name="trace_list"),
    path("traces/<uuid:pk>/", TraceDetailView.as_view(), name="trace_detail"),
    # API views answer unauthenticated calls with a 403 envelope from DRF, not a login redirect.
    path(
        "api/v1/traces/<uuid:pk>/graph/",
        login_not_required(TraceGraphApi.as_view()),
        name="trace_graph",
    ),
]
