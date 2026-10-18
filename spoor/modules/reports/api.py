from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import status
from rest_framework.views import APIView

from spoor.common.responses import error_response, success_response
from spoor.modules.reports.builder import InvalidGraphImageError, decode_graph_image, issue_report
from spoor.modules.reports.serializers import IssueReportSerializer
from spoor.modules.tracing.models import TraceRun


class IssueReportApi(APIView):
    """Freeze the current state of a finished trace into a report."""

    def post(self, request, pk):
        run = get_object_or_404(TraceRun.objects.select_related("token__chain", "case"), pk=pk)
        if not run.is_finished:
            return error_response(
                "Wait for the trace to finish before issuing a report.",
                "trace_running",
                status.HTTP_409_CONFLICT,
            )
        body = IssueReportSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            graph_image = decode_graph_image(body.validated_data.get("graph_image"))
        except InvalidGraphImageError as exc:
            return error_response(str(exc), "invalid_graph_image", status.HTTP_400_BAD_REQUEST)

        report = issue_report(run, request.user, graph_image)
        return success_response(
            {
                "report_url": reverse("reports:report_html", args=[report.pk]),
                "pdf_url": reverse("reports:report_pdf", args=[report.pk])
                if report.has_pdf
                else None,
                "pdf_error": report.pdf_error or None,
                "manifest_sha256": report.manifest_sha256,
            },
            message="Report issued.",
            status=status.HTTP_201_CREATED,
        )
