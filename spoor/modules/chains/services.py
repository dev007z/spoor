"""Fetching from providers into the evidence store, for pages that do it on request."""

from spoor.modules.chains.adapters.base import AdapterError
from spoor.modules.chains.adapters.registry import get_adapter
from spoor.modules.chains.models import Transfer

# Request-time fetches are capped so a page stays responsive on rate-limited providers;
# deep work belongs in a background trace.
MAX_RECORDS_PER_FETCH = 200


def fetch_address_transfers(token, address, start, end):
    """Fetch and store an address's transfers. Returns a context dict for the page."""
    try:
        result = get_adapter(token.chain).get_token_transfers(
            address, token, start, end, MAX_RECORDS_PER_FETCH
        )
    except AdapterError as exc:
        return {"fetch_error": str(exc)}
    Transfer.store_records(token.chain, token, result.records)
    return {"fetched": len(result.records), "fetch_complete": result.complete}
