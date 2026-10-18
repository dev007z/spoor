"""Exposure of an address to labeled entities.

Direct exposure: the address itself carries a label. One-hop exposure: it sent
funds to, or received funds from, a labeled address in the stored transfers for
the window. Deeper exposure is what a trace answers; `trace_exposure` reports the
labeled addresses a trace reached and how far from the seed they were.
"""

from dataclasses import dataclass

from spoor.common.functions import to_units
from spoor.modules.chains.models import Address, Transfer
from spoor.modules.labels.enums import LabelCategory
from spoor.modules.labels.models import Label

# Most serious first: the order findings are listed and the verdict is chosen in.
RISK_ORDER = [
    LabelCategory.SANCTIONED,
    LabelCategory.SCAM,
    LabelCategory.MIXER,
    LabelCategory.BRIDGE,
    LabelCategory.EXCHANGE,
    LabelCategory.PROTOCOL,
    LabelCategory.OTHER,
]


def risk_rank(category):
    return RISK_ORDER.index(category)


@dataclass
class CounterpartyExposure:
    address: Address
    label: Label
    received_from: object  # Decimal token units the screened address received from it
    sent_to: object  # Decimal token units the screened address sent to it
    transfers: int


@dataclass
class ScreeningResult:
    address: str
    direct_labels: list
    counterparties: list
    counterparty_count: int
    transfer_count: int

    @property
    def verdict(self):
        if self.direct_labels:
            return "direct"
        if self.counterparties:
            return "indirect"
        return "none"


def screen_address(token, address_value, start, end):
    address = Address.objects.filter(chain=token.chain, address=address_value).first()
    if address is None:
        return ScreeningResult(address_value, [], [], 0, 0)

    direct = sorted(
        Label.objects.filter(address=address).select_related("dataset"),
        key=lambda label: risk_rank(label.category),
    )
    flows = {}
    transfers = list(Transfer.fetch_for_address(address, token, start, end))
    for transfer in transfers:
        incoming = transfer.to_address_id == address.id
        counterparty = transfer.from_address if incoming else transfer.to_address
        flow = flows.setdefault(
            counterparty.id, {"address": counterparty, "in": 0, "out": 0, "n": 0}
        )
        flow["in" if incoming else "out"] += transfer.amount
        flow["n"] += 1

    labels = Label.best_for_addresses(list(flows))
    exposures = [
        CounterpartyExposure(
            address=flow["address"],
            label=labels[address_id],
            received_from=to_units(flow["in"], token.decimals),
            sent_to=to_units(flow["out"], token.decimals),
            transfers=flow["n"],
        )
        for address_id, flow in flows.items()
        if address_id in labels
    ]
    exposures.sort(key=lambda e: (risk_rank(e.label.category), -(e.received_from + e.sent_to)))
    return ScreeningResult(address_value, direct, exposures, len(flows), len(transfers))


def trace_exposure(run):
    """Labeled addresses a trace reached, most serious first, with what reached them."""
    received = {}
    for edge in run.edges.select_related("transfer"):
        transfer = edge.transfer
        received[transfer.to_address_id] = received.get(transfer.to_address_id, 0) + transfer.amount

    rows = [
        {
            "node": node,
            "label": node.label,
            "received": to_units(received.get(node.address_id, 0), run.token.decimals),
        }
        for node in run.nodes.filter(label__isnull=False).select_related("address", "label")
    ]
    rows.sort(key=lambda row: (risk_rank(row["label"].category), row["node"].hop))
    return rows
