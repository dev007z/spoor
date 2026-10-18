"""Turn a trace run into graph data for the fund-flow view.

Nodes are addresses; edges are the transfers followed between a pair of addresses,
combined so the graph stays readable. Exact totals travel as strings so no
precision is lost on the way to the browser.
"""

import math
from urllib.parse import urlencode

from django.urls import reverse

from spoor.common.functions import to_units
from spoor.modules.tracing.enums import StopReason

MAX_EDGE_WIDTH = 8


def build_graph(run):
    chain, token = run.chain, run.token
    seed_ids = set(run.seeds.values_list("id", flat=True))
    window = {
        "token": token.pk,
        "start": f"{run.start:%Y-%m-%dT%H:%M}",
        "end": f"{run.end:%Y-%m-%dT%H:%M}",
    }
    transfers_url = reverse("chains:address_transfers")

    nodes = []
    for node in run.fetch_nodes():
        address = node.address.address
        nodes.append(
            {
                "id": address,
                "node_id": str(node.pk),
                "hop": node.hop,
                "kind": node_kind(node, seed_ids),
                "label": node.label.entity if node.label else None,
                "category": node.label.category if node.label else None,
                "outcome": node.get_stop_reason_display()
                or ("Expanded" if node.expanded else "Queued"),
                "fan_out_truncated": node.fan_out_truncated,
                "fetch_incomplete": node.fetch_incomplete,
                "expandable": run.is_finished and not node.expanded,
                "expand_url": reverse("tracing:expand_node", args=[run.pk, node.pk]),
                "explorer_url": chain.address_url(address),
                "transfers_url": f"{transfers_url}?{urlencode({**window, 'address': address})}",
            }
        )

    pairs = {}
    for edge in run.fetch_edges():
        transfer = edge.transfer
        key = (transfer.from_address.address, transfer.to_address.address)
        pair = pairs.setdefault(key, {"amount": 0, "count": 0})
        pair["amount"] += transfer.amount
        pair["count"] += 1

    largest = max((pair["amount"] for pair in pairs.values()), default=0)
    edges = [
        {
            "id": f"{source}->{target}",
            "source": source,
            "target": target,
            "amount": str(to_units(pair["amount"], token.decimals)),
            "symbol": token.symbol,
            "count": pair["count"],
            "width": edge_width(pair["amount"], largest),
        }
        for (source, target), pair in pairs.items()
    ]
    return {"nodes": nodes, "edges": edges, "finished": run.is_finished}


def node_kind(node, seed_ids):
    if node.address_id in seed_ids:
        return "seed"
    if node.stop_reason == StopReason.LABELED_ENDPOINT:
        return "endpoint"
    if node.label:
        return "labeled"
    return "address"


def edge_width(amount, largest):
    """1 to MAX_EDGE_WIDTH on a log scale, so small flows stay visible next to large ones."""
    if largest <= 0:
        return 1
    return round(1 + (MAX_EDGE_WIDTH - 1) * math.log1p(amount) / math.log1p(largest), 2)
