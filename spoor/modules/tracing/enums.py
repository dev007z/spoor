from django.db import models


class TraceDirection(models.TextChoices):
    FORWARD = "forward", "Forward (where the funds went)"
    BACKWARD = "backward", "Backward (where the funds came from)"


class TraceStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class StopReason(models.TextChoices):
    """Why a node was not expanded further. Blank means it was expanded."""

    LABELED_ENDPOINT = "labeled_endpoint", "Labeled endpoint"
    MAX_HOPS = "max_hops", "Hop limit reached"
    NO_TRANSFERS = "no_transfers", "No qualifying transfers"
