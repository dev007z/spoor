"""ERC-20 / BEP-20 transfers from any EVM JSON-RPC endpoint via eth_getLogs.

Transfer(address indexed from, address indexed to, uint256 value) logs are read
with the traced address in topic 1 (outgoing) and topic 2 (incoming). Logs carry
logIndex and blockNumber natively. The time window is mapped to a block range by
searching block timestamps, and only blocks the node reports as finalized are
ever answered from cache.
"""

from datetime import UTC, datetime

from spoor.modules.chains.adapters.base import (
    AdapterError,
    ChainAdapter,
    FetchResult,
    ProviderError,
    TransferRecord,
)
from spoor.modules.chains.adapters.http import ProviderClient

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEFAULT_MAX_BLOCK_RANGE = 1000
BLOCK_TIME_SAMPLE = 1000  # blocks back from the head used to estimate the block time

# Phrases RPC providers use when an eth_getLogs range or result set is too big.
RANGE_ERROR_HINTS = ("range", "limit", "too many", "too large", "exceed", "query returned more")


class RpcError(ProviderError):
    pass


class RangeTooLargeError(RpcError):
    pass


def check_rpc(data):
    error = data.get("error") if isinstance(data, dict) else None
    if error:
        message = str(error.get("message", error))
        if any(hint in message.lower() for hint in RANGE_ERROR_HINTS):
            raise RangeTooLargeError(message)
        raise RpcError(message)
    if not isinstance(data, dict) or "result" not in data:
        raise RpcError(f"Malformed JSON-RPC response: {str(data)[:300]}")


class JsonRpcAdapter(ChainAdapter):
    source_prefix = "rpc"
    # Hosted RPC URLs usually carry the API key in the path.
    redacts_url_path = True

    def __init__(
        self,
        chain,
        transport=None,
        rpc_url="",
        max_block_range=DEFAULT_MAX_BLOCK_RANGE,
        min_interval=0.2,
    ):
        super().__init__(chain)
        if not rpc_url:
            raise AdapterError(
                f"No JSON-RPC URL configured for {chain.name}. "
                f"Set {chain.key.upper()}_RPC_URL in .env."
            )
        self.rpc_url = rpc_url
        self.max_block_range = max_block_range
        self.client = ProviderClient(
            f"{self.source_prefix}:{chain.key}",
            min_interval=min_interval,
            redact_path=True,
            transport=transport,
        )
        self.head = None
        self.finalized = None
        self.block_times = {}  # per-adapter memo; the block search revisits the same blocks

    def call(self, method, params, cacheable):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        data, raw = self.client.post_json(
            self.rpc_url, payload, cacheable=cacheable, check=check_rpc
        )
        return data["result"], raw

    def get_token_transfers(self, address, token, start, end, max_records):
        address = self.chain.normalize_address(address)
        # One view of the chain per fetch, so both window searches agree.
        self.head = int(self.call("eth_blockNumber", [], cacheable=False)[0], 16)
        self.finalized = self.finalized_block_number()

        from_block = self.first_block_at_or_after(start)
        to_block = self.first_block_at_or_after(end, inclusive=False) - 1
        if from_block > to_block:
            return FetchResult(records=[], complete=True)

        topic = "0x" + address[2:].rjust(64, "0")
        logs = {}
        complete = True
        for topics in ([TRANSFER_TOPIC, topic], [TRANSFER_TOPIC, None, topic]):
            for log, raw in self.get_logs(token.contract, topics, from_block, to_block):
                key = (log["transactionHash"].lower(), int(log["logIndex"], 16))
                if key in logs:
                    continue  # a self-transfer matches both directions
                if len(logs) >= max_records:
                    complete = False
                    break
                logs[key] = (log, raw)

        records = [self.to_record(log, raw) for log, raw in logs.values()]
        records.sort(key=lambda r: (r.block_number, r.log_index))
        return FetchResult(records=records, complete=complete)

    def get_transaction_transfers(self, tx_hash, token):
        """The token's Transfer logs from one transaction.

        Reads the transaction's block with eth_getLogs rather than the receipt: some
        nodes refuse receipts, and it keeps every EVM transfer's evidence in one shape.
        """
        tx_hash = self.chain.normalize_tx_hash(tx_hash)
        self.finalized = self.finalized_block_number()
        transaction, _ = self.call("eth_getTransactionByHash", [tx_hash], cacheable=False)
        if transaction is None or transaction.get("blockNumber") is None:
            raise RpcError(f"Transaction {tx_hash} not found in a block on {self.chain.name}")
        block = int(transaction["blockNumber"], 16)
        return [
            self.to_record(log, raw)
            for log, raw in self.get_logs(token.contract, [TRANSFER_TOPIC], block, block)
            if log["transactionHash"].lower() == tx_hash
        ]

    def get_logs(self, contract, topics, from_block, to_block):
        """Yield (log, raw_response), shrinking the block range when the node refuses it."""
        size = self.max_block_range
        cursor = from_block
        while cursor <= to_block:
            chunk_end = min(cursor + size - 1, to_block)
            params = [
                {
                    "address": contract,
                    "fromBlock": hex(cursor),
                    "toBlock": hex(chunk_end),
                    "topics": topics,
                }
            ]
            try:
                logs, raw = self.call("eth_getLogs", params, cacheable=chunk_end <= self.finalized)
            except RangeTooLargeError:
                if size == 1:
                    raise
                size = max(1, size // 2)
                continue

            for log in logs:
                if log.get("removed") or len(log.get("topics", [])) != 3:
                    continue  # reorged-out logs; 4-topic Transfer is ERC-721, not a token amount
                yield log, raw
            cursor = chunk_end + 1

    def to_record(self, log, raw):
        block_number = int(log["blockNumber"], 16)
        timestamp = log.get("blockTimestamp")
        seconds = int(timestamp, 16) if timestamp else self.block_timestamp(block_number)
        return TransferRecord(
            tx_hash=self.chain.normalize_tx_hash(log["transactionHash"]),
            log_index=int(log["logIndex"], 16),
            block_number=block_number,
            timestamp=datetime.fromtimestamp(seconds, tz=UTC),
            from_address=self.chain.normalize_address("0x" + log["topics"][1][-40:]),
            to_address=self.chain.normalize_address("0x" + log["topics"][2][-40:]),
            amount=int(log["data"], 16),
            raw_response=raw,
        )

    def finalized_block_number(self):
        block, _ = self.call("eth_getBlockByNumber", ["finalized", False], cacheable=False)
        return int(block["number"], 16)

    def block_timestamp(self, number):
        if number not in self.block_times:
            block, _ = self.call(
                "eth_getBlockByNumber", [hex(number), False], cacheable=number <= self.finalized
            )
            if block is None:
                raise RpcError(f"Block {number} not found")
            self.block_times[number] = int(block["timestamp"], 16)
        return self.block_times[number]

    def first_block_at_or_after(self, moment, inclusive=True):
        """The first block with timestamp >= moment (> moment when not inclusive).

        Starts from an estimate based on recent block times, widens until the moment
        is bracketed, then interpolates (bisecting whenever a guess fails to halve the
        interval). It only touches blocks near the window, which matters on nodes that
        refuse old-block requests. Returns head + 1 when no block has reached the moment.
        """
        target = moment.timestamp()

        def reached(number):
            ts = self.block_timestamp(number)
            return ts >= target if inclusive else ts > target

        head = self.head
        if not reached(head):
            return head + 1

        sample = max(head - BLOCK_TIME_SAMPLE, 0)
        span = self.block_timestamp(head) - self.block_timestamp(sample)
        seconds_per_block = span / (head - sample) if head > sample and span > 0 else 1.0
        guess = head - int((self.block_timestamp(head) - target) / seconds_per_block)

        # Bracket the answer: not reached(lo), reached(hi).
        step = 64
        hi = min(max(guess + step, 0), head)
        while not reached(hi):
            step *= 4
            hi = min(hi + step, head)
        lo = max(min(guess - step, hi - 1), 0)
        while reached(lo):
            if lo == 0:
                return 0
            hi = lo
            step *= 4
            lo = max(lo - step, 0)

        lo_ts, hi_ts = self.block_timestamp(lo), self.block_timestamp(hi)
        bisect = False
        while hi - lo > 1:
            width = hi - lo
            if bisect or hi_ts == lo_ts:
                guess = lo + width // 2
            else:
                guess = lo + int((target - lo_ts) * width / (hi_ts - lo_ts))
            middle = min(max(guess, lo + 1), hi - 1)
            if reached(middle):
                hi, hi_ts = middle, self.block_timestamp(middle)
            else:
                lo, lo_ts = middle, self.block_timestamp(middle)
            bisect = (hi - lo) * 2 > width
        return hi
