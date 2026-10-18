from django.shortcuts import get_object_or_404
from rest_framework.views import APIView

from spoor.common.responses import success_response
from spoor.modules.tracing.graph import build_graph
from spoor.modules.tracing.models import TraceRun


class TraceGraphApi(APIView):
    """Graph data for one trace run, in the standard response envelope."""

    def get(self, request, pk):
        run = get_object_or_404(TraceRun.objects.select_related("token__chain"), pk=pk)
        return success_response(build_graph(run), message="Trace graph.")
