"""Breadth-first fund tracing.

From the seed addresses, each hop fetches the token transfers of every frontier
address, keeps those that move funds in the trace direction within the address's
time bound and above the minimum amount, follows the largest `fan_out` of them,
and adds the counterparties as the next frontier. An address is expanded once per
run, so cycles terminate. Every stop and truncation is recorded on its node.

An analyst can also expand one stopped address by hand: its stop is overridden for
that address only, and the trace continues from it under the run's normal rules.
"""

import logging

from spoor.modules.chains.adapters.base import AdapterError
from spoor.modules.chains.adapters.registry import get_adapter
from spoor.modules.chains.models import Transfer
from spoor.modules.labels.enums import TERMINAL_CATEGORIES
from spoor.modules.labels.models import Label
from spoor.modules.tracing.enums import StopReason, TraceDirection
from spoor.modules.tracing.models import TraceEdge, TraceNode

logger = logging.getLogger(__name__)


class TraceEngine:
    def __init__(self, run, adapter=None):
        self.run = run
        self.adapter = adapter
        self.forward = run.direction == TraceDirection.FORWARD
        self.nodes = {}  # address_id -> TraceNode

    def execute(self, from_node=None):
        """Run the whole trace, or continue it from one node an analyst chose to expand."""
        self.run.mark_running()
        try:
            if self.adapter is None:
                self.adapter = get_adapter(self.run.chain)
            if from_node is None:
                self.trace()
            else:
                self.continue_from(from_node)
        except AdapterError as exc:
            self.run.mark_finished(error=str(exc))
        except Exception:
            logger.exception("Trace %s crashed", self.run.pk)
            self.run.mark_finished(error="Unexpected error while tracing; see the worker logs.")
            raise
        else:
            self.run.mark_finished()

    def trace(self):
        seed_anchor = self.run.start if self.forward else self.run.end
        self.walk([self.add_node(seed, hop=0, anchor=seed_anchor) for seed in self.run.seeds.all()])

    def continue_from(self, node):
        self.nodes = {n.address_id: n for n in self.run.nodes.select_related("address", "label")}
        self.walk(self.expand(self.nodes[node.address_id], forced=True))

    def walk(self, frontier):
        while frontier:
            frontier = [child for node in frontier for child in self.expand(node)]

    def expand(self, node, forced=False):
        """Follow one address. Returns the newly discovered nodes."""
        if not forced:
            if node.label and node.label.category in TERMINAL_CATEGORIES:
                return self.stop(node, StopReason.LABELED_ENDPOINT)
            if node.hop >= self.run.max_hops:
                return self.stop(node, StopReason.MAX_HOPS)

        start, end = self.window(node)
        selected = []
        if start <= end:
            result = self.adapter.get_token_transfers(
                node.address.address,
                self.run.token,
                start,
                end,
                self.run.max_records_per_address,
            )
            Transfer.store_records(self.run.chain, self.run.token, result.records)
            node.fetch_incomplete = not result.complete
            candidates = self.candidates(node, start, end)
            selected = candidates[: self.run.fan_out]
            node.fan_out_truncated = len(candidates) > self.run.fan_out

        node.expanded = True
        node.stop_reason = "" if selected else StopReason.NO_TRANSFERS
        node.save()
        self.run.record_progress()

        discovered = []
        for transfer in selected:
            TraceEdge.objects.get_or_create(
                run=self.run, transfer=transfer, defaults={"hop": node.hop}
            )
            counterparty = transfer.to_address if self.forward else transfer.from_address
            child = self.nodes.get(counterparty.id)
            if child is None:
                child = self.add_node(counterparty, hop=node.hop + 1, anchor=transfer.timestamp)
                discovered.append(child)
            elif not child.expanded and self.tightens(child, transfer.timestamp):
                child.anchor_at = transfer.timestamp
                child.save(update_fields=["anchor_at", "updated_at"])
        return discovered

    def window(self, node):
        if self.forward:
            return max(self.run.start, node.anchor_at), self.run.end
        return self.run.start, min(self.run.end, node.anchor_at)

    def candidates(self, node, start, end):
        """Transfers moving funds in the trace direction, largest first, ties by time."""
        transfers = Transfer.fetch_for_address(node.address, self.run.token, start, end).filter(
            amount__gte=self.run.min_amount
        )
        if self.forward:
            transfers = transfers.filter(from_address=node.address)
        else:
            transfers = transfers.filter(to_address=node.address)
        # The fan-out cap needs one extra row to know whether it truncated.
        return list(
            transfers.order_by("-amount", "timestamp", "tx_hash", "log_index")[
                : self.run.fan_out + 1
            ]
        )

    def tightens(self, node, moment):
        """True when this path reaches the node earlier (forward) or later (backward)."""
        return moment < node.anchor_at if self.forward else moment > node.anchor_at

    def add_node(self, address, hop, anchor):
        label = Label.best_for_addresses([address.id]).get(address.id)
        node = TraceNode.objects.create(
            run=self.run, address=address, hop=hop, anchor_at=anchor, label=label
        )
        self.nodes[address.id] = node
        return node

    @staticmethod
    def stop(node, reason):
        node.stop_reason = reason
        node.save(update_fields=["stop_reason", "updated_at"])
        return []
