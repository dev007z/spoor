from django.contrib.auth.decorators import login_not_required
from django.urls import path

from spoor.modules.reports.api import IssueReportApi
from spoor.modules.reports.views import ReportHtmlView, ReportPdfView

app_name = "reports"

urlpatterns = [
    path("reports/<uuid:pk>/", ReportHtmlView.as_view(), name="report_html"),
    path("reports/<uuid:pk>/pdf/", ReportPdfView.as_view(), name="report_pdf"),
    path(
        "api/v1/traces/<uuid:pk>/reports/",
        login_not_required(IssueReportApi.as_view()),
        name="issue_report",
    ),
]
