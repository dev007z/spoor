from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View

from spoor.modules.reports.models import ReportExport


class ReportHtmlView(View):
    """The report exactly as issued."""

    def get(self, request, pk):
        report = get_object_or_404(ReportExport, pk=pk)
        return HttpResponse(report.html, content_type="text/html; charset=utf-8")


class ReportPdfView(View):
    def get(self, request, pk):
        report = get_object_or_404(ReportExport, pk=pk)
        if not report.has_pdf:
            raise Http404("This report was issued without a PDF.")
        response = HttpResponse(bytes(report.pdf), content_type="application/pdf")
        filename = f"spoor-report-{report.created_at:%Y%m%d-%H%M%S}.pdf"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
