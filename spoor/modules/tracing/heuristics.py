"""Heuristics: transaction patterns that suggest what an address might be.

A heuristic looks at an expanded trace address's stored transfers and may return a
Signal: a confidence level, a plain explanation an analyst can repeat, and the
transfers it rests on. Signals are never attribution; they are reasons to look
closer. Heuristics are registered in settings.SPOOR_HEURISTICS, so a deployment can
add its own without changing this module.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils.module_loading import import_string

from spoor.common.functions import to_units
from spoor.modules.chains.models import Transfer
from spoor.modules.labels.enums import LabelConfidence
from spoor.modules.tracing.models import NodeSignal


@dataclass(frozen=True)
class Signal:
    confidence: str
    explanation: str
    transfers: list


class Heuristic:
    key = ""
    name = ""

    def evaluate(self, node, transfers, token):
        """Return a Signal, or None when the pattern is absent."""
        raise NotImplementedError


class CollectionWallet(Heuristic):
    """Many senders in, most of it out again in a few transfers soon after.

    Fires when an address receives transfers from at least MIN_SENDERS distinct
    senders within WINDOW, then forwards at least FORWARD_PERCENT of that total in at
    most MAX_OUTFLOWS transfers within WINDOW of the last of those inflows.

    Typical of exchange deposit addresses and scam collection wallets. Known false
    positives: merchants settling sales, payroll or payout services, and exchange hot
    wallets, which all gather many payments and sweep them onward.
    """

    key = "collection_wallet"
    name = "Collection wallet pattern"
    MIN_SENDERS = 5
    STRONG_SENDERS = 15
    WINDOW = timedelta(hours=24)
    FORWARD_PERCENT = 80
    MAX_OUTFLOWS = 3

    def evaluate(self, node, transfers, token):
        inbound = sorted(
            (t for t in transfers if t.to_address_id == node.address_id), key=lambda t: t.timestamp
        )
        outbound = [t for t in transfers if t.from_address_id == node.address_id]

        for first in inbound:
            batch = [
                t
                for t in inbound
                if first.timestamp <= t.timestamp <= first.timestamp + self.WINDOW
            ]
            senders = {t.from_address_id for t in batch}
            if len(senders) < self.MIN_SENDERS:
                continue

            received = sum(t.amount for t in batch)
            last_in = batch[-1].timestamp
            onward = sorted(
                (t for t in outbound if last_in < t.timestamp <= last_in + self.WINDOW),
                key=lambda t: t.amount,
                reverse=True,
            )[: self.MAX_OUTFLOWS]
            forwarded = sum(t.amount for t in onward)
            if received and forwarded * 100 >= received * self.FORWARD_PERCENT:
                return Signal(
                    confidence=(
                        LabelConfidence.MEDIUM
                        if len(senders) >= self.STRONG_SENDERS
                        else LabelConfidence.LOW
                    ),
                    explanation=(
                        f"Received {len(batch)} transfers from {len(senders)} distinct senders "
                        f"within 24 hours ({to_units(received, token.decimals):f} {token.symbol}), "
                        f"then sent {forwarded * 100 // received}% of it onward in "
                        f"{len(onward)} transfer(s) within the next 24 hours. Typical of deposit "
                        "and collection wallets; also seen with merchants, payroll services and "
                        "exchange hot wallets."
                    ),
                    transfers=batch + onward,
                )
        return None


def registered_heuristics():
    return [import_string(path)() for path in settings.SPOOR_HEURISTICS]


def evaluate_run(run):
    """Re-evaluate every expanded address of a run and store the signals found."""
    heuristics = registered_heuristics()
    for node in run.nodes.filter(expanded=True).select_related("address"):
        transfers = list(Transfer.fetch_for_address(node.address, run.token, run.start, run.end))
        for heuristic in heuristics:
            signal = heuristic.evaluate(node, transfers, run.token)
            if signal is None:
                NodeSignal.objects.filter(node=node, heuristic=heuristic.key).delete()
                continue
            stored, _ = NodeSignal.objects.update_or_create(
                node=node,
                heuristic=heuristic.key,
                defaults={
                    "name": heuristic.name,
                    "confidence": signal.confidence,
                    "explanation": signal.explanation,
                },
            )
            stored.transfers.set(signal.transfers)
