"""Live reads of a contract's state through the chain's read-only RPC client."""

from dataclasses import dataclass

from spoor.modules.chains.adapters.base import AdapterError
from spoor.modules.chains.adapters.registry import get_adapter

OWNER_SELECTOR = "0x8da5cb5b"  # owner()
TOTAL_SUPPLY_SELECTOR = "0x18160ddd"  # totalSupply()
BALANCE_OF_SELECTOR = "0x70a08231"  # balanceOf(address)
GET_PAIR_SELECTOR = "0xe6a43905"  # getPair(address,address) on Uniswap V2 style factories
ZERO_ADDRESS = "0x" + "0" * 40
DEAD_ADDRESS = "0x000000000000000000000000000000000000dead"


def word(address):
    return address[2:].lower().rjust(64, "0")


def total_supply(adapter, token):
    result, _ = adapter.read_contract(token, TOTAL_SUPPLY_SELECTOR)
    return int(result, 16)


def balance_of(adapter, token, holder):
    result, _ = adapter.read_contract(token, BALANCE_OF_SELECTOR + word(holder))
    return int(result, 16)


def get_pair(adapter, factory, token_a, token_b):
    """The pair contract for two tokens, or None when the factory has none."""
    result, _ = adapter.read_contract(factory, GET_PAIR_SELECTOR + word(token_a) + word(token_b))
    pair = "0x" + result[-40:].lower()
    return None if pair == ZERO_ADDRESS else pair


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
