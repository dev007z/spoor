from django.conf import settings
from django.db import models

from spoor.common.mixins import ModelMixin
from spoor.modules.tracing.models import TraceRun


class ReportExport(ModelMixin):
    """A frozen report: the exact HTML issued, the evidence it cites, and its PDF.

    The HTML and manifest are stored as issued, so the report reads the same later
    even if the trace is expanded. The PDF is rendered from that same HTML.
    """

    run = models.ForeignKey(TraceRun, on_delete=models.PROTECT, related_name="reports")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports"
    )
    html = models.TextField()
    manifest = models.JSONField()
    manifest_sha256 = models.CharField(max_length=64)
    pdf = models.BinaryField(null=True, blank=True, editable=False)
    pdf_sha256 = models.CharField(max_length=64, blank=True)
    pdf_error = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"Report for {self.run} at {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def has_pdf(self):
        return self.pdf is not None

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Reports are frozen once issued; export a new one instead.")
        super().save(*args, **kwargs)
