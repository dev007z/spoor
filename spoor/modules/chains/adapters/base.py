"""The contract every chain adapter satisfies.

Providers authenticate and paginate differently, so each adapter owns its own
request logic. What they share is the return shape: a FetchResult of
TransferRecords, each pointing at the RawResponse it was parsed from.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from spoor.modules.chains.models import RawResponse


class AdapterError(Exception):
    pass


class ProviderError(AdapterError):
    """The provider failed, refused, or returned something unusable."""


class ProviderDataError(AdapterError):
    """The provider's responses contradict each other, so none can be trusted as evidence."""


@dataclass(frozen=True)
class TransferRecord:
    tx_hash: str
    log_index: int
    block_number: int
    timestamp: datetime
    from_address: str
    to_address: str
    amount: int
    raw_response: RawResponse


@dataclass(frozen=True)
class FetchResult:
    records: list[TransferRecord]
    complete: bool  # False when max_records cut the window short


class ChainAdapter(ABC):
    # True when the provider URL carries a credential in its path, as many RPC URLs do.
    redacts_url_path = False

    def __init__(self, chain):
        self.chain = chain

    @abstractmethod
    def get_token_transfers(self, address, token, start, end, max_records):
        """Token transfers into or out of `address` with start <= timestamp <= end.

        Addresses in the records are canonical (see chains.addresses). `start` and
        `end` are timezone-aware datetimes.
        """

    @abstractmethod
    def get_transaction_transfers(self, tx_hash, token):
        """Every transfer of `token` emitted by one transaction, in log order."""
