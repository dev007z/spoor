from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView

from spoor.common.responses import error_response, success_response
from spoor.modules.cases.enums import CaseEventType
from spoor.modules.cases.models import CaseEvent
from spoor.modules.tracing.graph import build_graph
from spoor.modules.tracing.models import TraceNode, TraceRun
from spoor.modules.tracing.tasks import expand_node


class TraceGraphApi(APIView):
    """Graph data for one trace run, in the standard response envelope."""

    def get(self, request, pk):
        run = get_object_or_404(TraceRun.objects.select_related("token__chain"), pk=pk)
        return success_response(build_graph(run), message="Trace graph.")


class ExpandNodeApi(APIView):
    """Queue a manual expansion of one address that the trace stopped at."""

    def post(self, request, pk, node_pk):
        node = get_object_or_404(
            TraceNode.objects.select_related("run__case", "address"), pk=node_pk, run_id=pk
        )
        run = node.run
        if not run.is_finished:
            return error_response(
                "The trace is still running.", "trace_running", status.HTTP_409_CONFLICT
            )
        if node.expanded:
            return error_response(
                "This address has already been expanded.",
                "already_expanded",
                status.HTTP_409_CONFLICT,
            )

        run.mark_queued()
        if run.case:
            CaseEvent.record(
                run.case,
                request.user,
                CaseEventType.TRACE_EXPANDED,
                f"Expanded {node.address.address} by hand.",
                trace_run=str(run.pk),
                address=node.address.address,
            )
        transaction.on_commit(lambda: expand_node.delay(str(node.pk)))
        return success_response(
            {"node": str(node.pk)}, message="Expansion queued.", status=status.HTTP_202_ACCEPTED
        )
