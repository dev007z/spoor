"""Everything shown about a trace run, computed once for the trace page and the report."""

from spoor.common.functions import to_units
from spoor.modules.screening.exposure import trace_exposure
from spoor.modules.tracing.enums import StopReason


def summarize_run(run):
    nodes = list(run.fetch_nodes())
    edges = list(run.fetch_edges())
    chain, token = run.chain, run.token

    flows = {}
    for edge in edges:
        transfer = edge.transfer
        for address_id, key in ((transfer.from_address_id, "out"), (transfer.to_address_id, "in")):
            flows.setdefault(address_id, {"in": 0, "out": 0})[key] += transfer.amount

    node_rows = [
        {
            "node": node,
            "url": chain.address_url(node.address.address),
            "received": to_units(flows.get(node.address_id, {}).get("in", 0), token.decimals),
            "sent": to_units(flows.get(node.address_id, {}).get("out", 0), token.decimals),
        }
        for node in nodes
    ]
    edge_rows = [
        {"edge": edge, "transfer": edge.transfer, "tx_url": chain.tx_url(edge.transfer.tx_hash)}
        for edge in edges
    ]
    return {
        "run": run,
        "seeds": list(run.seeds.all()),
        "seed_tx_url": chain.tx_url(run.seed_tx_hash) if run.seed_tx_hash else None,
        "min_amount_units": to_units(run.min_amount, token.decimals),
        "node_rows": node_rows,
        "edge_rows": edge_rows,
        "exposure": trace_exposure(run),
        "stats": {
            "addresses": len(nodes),
            "transfers": len(edges),
            "endpoints": sum(n.stop_reason == StopReason.LABELED_ENDPOINT for n in nodes),
        },
    }
