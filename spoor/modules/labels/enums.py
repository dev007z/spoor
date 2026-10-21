from django.db import models


class LabelCategory(models.TextChoices):
    EXCHANGE = "exchange", "Exchange"
    BRIDGE = "bridge", "Bridge"
    MIXER = "mixer", "Mixer"
    SANCTIONED = "sanctioned", "Sanctioned"
    SCAM = "scam", "Scam"
    PROTOCOL = "protocol", "Protocol"
    OTHER = "other", "Other"


# Funds reaching these entities leave the traceable on-chain path, so a trace stops there.
TERMINAL_CATEGORIES = frozenset({LabelCategory.EXCHANGE, LabelCategory.BRIDGE, LabelCategory.MIXER})


class LabelConfidence(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class DatasetVisibility(models.TextChoices):
    """Public datasets ship with Spoor. Private ones exist only in a deployment's own database."""

    PUBLIC = "public", "Public"
    PRIVATE = "private", "Private"
