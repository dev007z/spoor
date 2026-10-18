from django.db import models


class CaseType(models.TextChoices):
    INVESTMENT_SCHEME = "investment_scheme", "Investment scheme"
    ROMANCE = "romance", "Romance or pig-butchering"
    FAKE_PLATFORM = "fake_platform", "Fake exchange or wallet"
    RUG_PULL = "rug_pull", "Rug pull or honeypot token"
    RANSOMWARE = "ransomware", "Ransomware"
    HACK = "hack", "Hack or exploit"
    OTHER = "other", "Other"


class CaseEventType(models.TextChoices):
    CREATED = "created", "Case created"
    UPDATED = "updated", "Case updated"
    TRACE_STARTED = "trace_started", "Trace started"
    TRACE_EXPANDED = "trace_expanded", "Address expanded"
    NOTE_ADDED = "note_added", "Note added"
    REPORT_EXPORTED = "report_exported", "Report issued"
