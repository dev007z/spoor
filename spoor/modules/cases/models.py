from django.conf import settings
from django.db import models

from spoor.common.mixins import ModelMixin
from spoor.modules.cases.enums import CaseEventType, CaseType


class Case(ModelMixin):
    """An investigation: the traces, notes, and history gathered for one matter."""

    name = models.CharField(max_length=200)
    case_type = models.CharField(max_length=30, choices=CaseType.choices)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cases"
    )

    def __str__(self):
        return self.name

    @classmethod
    def create_case(cls, user, **fields):
        case = cls.objects.create(created_by=user, **fields)
        CaseEvent.record(case, user, CaseEventType.CREATED, f'Opened case "{case.name}".')
        return case

    @classmethod
    def fetch_cases(cls):
        return (
            cls.objects.select_related("created_by")
            .annotate(trace_count=models.Count("trace_runs", distinct=True))
            .order_by("-created_at")
        )

    def fetch_events(self):
        return self.events.select_related("actor").order_by("-created_at")


class CaseEvent(ModelMixin):
    """Append-only history of a case: who did what, and when."""

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="case_events"
    )
    event_type = models.CharField(max_length=30, choices=CaseEventType.choices)
    summary = models.CharField(max_length=500)
    details = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.get_event_type_display()}: {self.summary}"

    @classmethod
    def record(cls, case, actor, event_type, summary, **details):
        return cls.objects.create(
            case=case, actor=actor, event_type=event_type, summary=summary, details=details
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Case events are append-only.")
        super().save(*args, **kwargs)
