from django.urls import path

from spoor.modules.tracing.views import TraceDetailView, TraceListView

app_name = "tracing"

urlpatterns = [
    path("traces/", TraceListView.as_view(), name="trace_list"),
    path("traces/<uuid:pk>/", TraceDetailView.as_view(), name="trace_detail"),
]
