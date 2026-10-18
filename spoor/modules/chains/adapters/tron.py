"""TRC-20 transfers from TronGrid.

TronGrid's account listing (/v1/accounts/{address}/transactions/trc20) filters by
address, token, and time, but has no block number or event index. So the listing
is used only to discover transaction ids; each transfer's evidence comes from
/v1/transactions/{id}/events, which carries block_number and event_index. The two
are cross-checked per transaction, and a disagreement fails loudly.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

from django.utils import timezone

from spoor.modules.chains.adapters.base import (
    ChainAdapter,
    FetchResult,
    ProviderDataError,
    ProviderError,
    TransferRecord,
)
from spoor.modules.chains.adapters.http import ProviderClient

BASE_URL = "https://api.trongrid.io"
PAGE_SIZE = 200  # TronGrid's maximum
# Confirmed TRON blocks are final within about a minute; a window that ended
# earlier than this can no longer change, so its listing is safe to cache.
FINALITY_MARGIN = timedelta(minutes=5)


class TronGridAdapter(ChainAdapter):
    source = "trongrid"

    def __init__(self, chain, transport=None, api_key="", base_url=BASE_URL, min_interval=None):
        super().__init__(chain)
        self.base_url = base_url.rstrip("/")
        if min_interval is None:
            min_interval = 0.1 if api_key else 1.0  # keyless requests are heavily rate limited
        self.client = ProviderClient(
            self.source,
            headers={"TRON-PRO-API-KEY": api_key} if api_key else {},
            min_interval=min_interval,
            transport=transport,
        )

    def get_token_transfers(self, address, token, start, end, max_records):
        address = self.chain.normalize_address(address)
        listed, complete = self.list_transfer_transactions(address, token, start, end, max_records)

        records = []
        for tx_hash, expected_count in listed.items():
            found = [
                r
                for r in self.transfers_in_transaction(tx_hash, token)
                if address in (r.from_address, r.to_address)
            ]
            if len(found) != expected_count:
                raise ProviderDataError(
                    f"TronGrid lists {expected_count} {token.symbol} transfers for {address} in "
                    f"{tx_hash}, but the transaction's events contain {len(found)}"
                )
            records.extend(found)

        return FetchResult(records=records, complete=complete)

    def list_transfer_transactions(self, address, token, start, end, max_records):
        """Transaction ids with the number of listed transfers in each, oldest first."""
        url = f"{self.base_url}/v1/accounts/{address}/transactions/trc20"
        params = {
            "contract_address": token.contract,
            "min_timestamp": to_millis(start),
            "max_timestamp": to_millis(end),
            "limit": PAGE_SIZE,
            "order_by": "block_timestamp,asc",
            "only_confirmed": "true",
        }
        cacheable = end <= timezone.now() - FINALITY_MARGIN

        counts = Counter()
        listed = 0
        while True:
            page, _ = self.client.get_json(url, params, cacheable=cacheable, check=check_success)

            for item in page["data"]:
                if item.get("type") != "Transfer":
                    continue
                if listed >= max_records:
                    return dict(counts), False
                counts[self.chain.normalize_tx_hash(item["transaction_id"])] += 1
                listed += 1

            cursor = page.get("meta", {}).get("fingerprint")
            if not cursor or not page["data"]:
                return dict(counts), True
            params = {**params, "fingerprint": cursor}

    def get_transaction_transfers(self, tx_hash, token):
        return self.transfers_in_transaction(self.chain.normalize_tx_hash(tx_hash), token)

    def transfers_in_transaction(self, tx_hash, token):
        url = f"{self.base_url}/v1/transactions/{tx_hash}/events"
        # Events of a confirmed transaction never change, so they are always cacheable.
        page, raw = self.client.get_json(
            url, {"only_confirmed": "true"}, cacheable=True, check=check_success
        )

        records = []
        for event in page["data"]:
            if event.get("event_name") != "Transfer":
                continue
            if self.chain.normalize_address(event["contract_address"]) != token.contract:
                continue

            result = event["result"]
            records.append(
                TransferRecord(
                    tx_hash=tx_hash,
                    log_index=event["event_index"],
                    block_number=event["block_number"],
                    timestamp=from_millis(event["block_timestamp"]),
                    from_address=self.chain.normalize_address(result["from"]),
                    to_address=self.chain.normalize_address(result["to"]),
                    amount=int(result["value"]),
                    raw_response=raw,
                )
            )
        return records


def check_success(page):
    if not page.get("success"):
        raise ProviderError(f"TronGrid reported failure: {str(page)[:300]}")


def to_millis(moment):
    return int(moment.timestamp() * 1000)


def from_millis(millis):
    return datetime.fromtimestamp(millis / 1000, tz=UTC)
