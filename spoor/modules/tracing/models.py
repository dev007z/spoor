from django.db import models
from django.utils import timezone

from spoor.common.mixins import ModelMixin
from spoor.modules.chains.models import Address, Token, Transfer
from spoor.modules.labels.models import Label
from spoor.modules.tracing.enums import StopReason, TraceDirection, TraceStatus


class TraceRun(ModelMixin):
    """One breadth-first trace: its parameters, its progress, and the graph it produced."""

    token = models.ForeignKey(Token, on_delete=models.PROTECT, related_name="trace_runs")
    seeds = models.ManyToManyField(Address, related_name="seeded_trace_runs")
    seed_tx_hash = models.CharField(
        max_length=66, blank=True, help_text="Set when the trace starts from a transaction."
    )
    direction = models.CharField(
        max_length=10, choices=TraceDirection.choices, default=TraceDirection.FORWARD
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    max_hops = models.PositiveSmallIntegerField(default=3)
    min_amount = models.DecimalField(
        max_digits=78, decimal_places=0, default=0, help_text="Raw integer amount."
    )
    fan_out = models.PositiveSmallIntegerField(
        default=5, help_text="Largest qualifying transfers followed per address."
    )
    max_records_per_address = models.PositiveIntegerField(default=500)

    status = models.CharField(
        max_length=10, choices=TraceStatus.choices, default=TraceStatus.PENDING, db_index=True
    )
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    addresses_expanded = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.get_direction_display()} trace of {self.token} ({self.status})"

    @classmethod
    def create_run(cls, token, seed_address=None, seed_tx_hash="", **params):
        """A pending run seeded from an address, or from a transaction whose transfers the
        worker resolves into seeds when the run starts."""
        run = cls.objects.create(token=token, seed_tx_hash=seed_tx_hash, **params)
        if seed_address:
            run.seeds.set([Address.resolve(token.chain, seed_address)])
        return run

    @classmethod
    def fetch_runs(cls):
        return (
            cls.objects.select_related("token__chain")
            .prefetch_related("seeds")
            .annotate(node_count=models.Count("nodes", distinct=True))
            .annotate(edge_count=models.Count("edges", distinct=True))
            .order_by("-created_at")
        )

    @property
    def chain(self):
        return self.token.chain

    @property
    def is_finished(self):
        return self.status in (TraceStatus.COMPLETED, TraceStatus.FAILED)

    def fetch_nodes(self):
        return self.nodes.select_related("address", "label").order_by("hop", "created_at")

    def fetch_edges(self):
        return self.edges.select_related(
            "transfer__from_address", "transfer__to_address", "transfer__token"
        ).order_by("hop", "transfer__timestamp", "transfer__log_index")

    def mark_queued(self):
        self.status = TraceStatus.PENDING
        self.error = ""
        self.save(update_fields=["status", "error", "updated_at"])

    def mark_running(self):
        self.status = TraceStatus.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at", "updated_at"])

    def mark_finished(self, error=""):
        self.status = TraceStatus.FAILED if error else TraceStatus.COMPLETED
        self.error = error
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "error", "finished_at", "updated_at"])

    def record_progress(self):
        self.addresses_expanded += 1
        self.save(update_fields=["addresses_expanded", "updated_at"])


class TraceNode(ModelMixin):
    """An address reached by a trace, and why the trace did or did not continue from it."""

    run = models.ForeignKey(TraceRun, on_delete=models.CASCADE, related_name="nodes")
    address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name="trace_nodes")
    hop = models.PositiveSmallIntegerField()
    # Time bound for following funds through this address: forward traces only follow
    # outflows at or after the first inflow; backward traces only inflows at or before
    # the last outflow.
    anchor_at = models.DateTimeField()
    label = models.ForeignKey(
        Label, on_delete=models.SET_NULL, null=True, blank=True, related_name="trace_nodes"
    )
    expanded = models.BooleanField(default=False)
    stop_reason = models.CharField(max_length=20, choices=StopReason.choices, blank=True)
    fan_out_truncated = models.BooleanField(default=False)
    fetch_incomplete = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "address"], name="unique_node_per_run"),
        ]

    def __str__(self):
        return f"{self.address} (hop {self.hop})"


class TraceEdge(ModelMixin):
    """A transfer the trace followed. Every edge is one on-chain transfer event."""

    run = models.ForeignKey(TraceRun, on_delete=models.CASCADE, related_name="edges")
    transfer = models.ForeignKey(Transfer, on_delete=models.PROTECT, related_name="trace_edges")
    hop = models.PositiveSmallIntegerField(help_text="Hop of the node the edge leaves from.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "transfer"], name="unique_edge_per_run"),
        ]

    def __str__(self):
        return f"{self.transfer} (hop {self.hop})"
