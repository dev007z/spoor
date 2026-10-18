"""Live reads of a contract's state through the chain's read-only RPC client."""

from dataclasses import dataclass

from spoor.modules.chains.adapters.base import AdapterError
from spoor.modules.chains.adapters.registry import get_adapter

OWNER_SELECTOR = "0x8da5cb5b"  # owner()
ZERO_ADDRESS = "0x" + "0" * 40


@dataclass
class Ownership:
    owner: str | None  # None when the read failed
    renounced: bool
    raw_response: object | None
    error: str = ""


def has_owner_function(contract):
    return any(f.get("name") == "owner" and not f.get("inputs") for f in contract.abi_functions())


def read_ownership(contract, abi_contract=None, adapter=None):
    """The current owner() at `contract`, or None when its ABI has no owner().

    For a proxy, pass the implementation as `abi_contract`: the function comes from the
    implementation's ABI, but the state lives at the proxy's address.
    """
    if not has_owner_function(abi_contract or contract):
        return None
    try:
        adapter = adapter or get_adapter(contract.chain)
        result, raw = adapter.read_contract(contract.address.address, OWNER_SELECTOR)
    except AdapterError as exc:
        return Ownership(owner=None, renounced=False, raw_response=None, error=str(exc))
    owner = "0x" + result[-40:].lower()
    return Ownership(owner=owner, renounced=owner == ZERO_ADDRESS, raw_response=raw)
