"""How much of a token, and of its DEX liquidity, its deployer and owner control.

Reads, at the latest block: the deployer's and owner's share of total supply; for
each configured DEX pair of the token, the share of liquidity tokens burned (sent to
the zero or dead address) and the share the deployer or owner still hold. Liquidity
held by anyone else, a locker contract included, is reported as "held by others":
lockers are not identified here, so a locked position cannot be told from a loose one.
"""

import decimal
from dataclasses import dataclass, field

from django.conf import settings

from spoor.common.functions import AMOUNT_CONTEXT
from spoor.modules.chains.adapters.base import AdapterError
from spoor.modules.chains.adapters.registry import get_adapter
from spoor.modules.contracts.checks import Finding, Severity
from spoor.modules.contracts.onchain import (
    DEAD_ADDRESS,
    ZERO_ADDRESS,
    balance_of,
    get_pair,
    total_supply,
)

LARGE_HOLDING = 20  # percent of supply
NOTABLE_HOLDING = 5
CONTROLLED_LIQUIDITY = 50  # percent of LP tokens
BURNED_LIQUIDITY = 95


@dataclass
class Holding:
    role: str
    address: str
    share: decimal.Decimal  # percent


@dataclass
class Pool:
    quote: str
    pair: str
    burned: decimal.Decimal  # percent of LP tokens
    held: list  # Holding per controlling wallet

    @property
    def others(self):
        return max(decimal.Decimal(0), 100 - self.burned - sum(h.share for h in self.held))


@dataclass
class Liquidity:
    dex: str
    holdings: list = field(default_factory=list)
    pools: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    error: str = ""


def percent(part, whole):
    if not whole:
        return decimal.Decimal(0)
    share = AMOUNT_CONTEXT.divide(decimal.Decimal(part) * 100, decimal.Decimal(whole))
    return share.quantize(decimal.Decimal("0.01"))


def controllers(contract, owner):
    """{address: role} for the deployer and a live owner, merged when they are one wallet."""
    wallets = {}
    for role, address in (("Deployer", contract.deployer), ("Owner", owner)):
        if address and address != ZERO_ADDRESS:
            wallets[address] = f"{wallets[address]} and owner" if address in wallets else role
    return wallets


def analyze_liquidity(contract, owner=None, adapter=None):
    dex = settings.SPOOR_DEXES.get(contract.chain.key)
    if dex is None:
        return None
    token = contract.address.address
    wallets = controllers(contract, owner)
    liquidity = Liquidity(dex=dex["name"])
    try:
        adapter = adapter or get_adapter(contract.chain)
        supply = total_supply(adapter, token)
        liquidity.holdings = [
            Holding(role, address, percent(balance_of(adapter, token, address), supply))
            for address, role in wallets.items()
        ]
        for quote, quote_token in dex["quote_tokens"].items():
            if quote_token == token:
                continue
            pair = get_pair(adapter, dex["factory"], token, quote_token)
            if pair is None:
                continue
            lp_supply = total_supply(adapter, pair)
            burned = balance_of(adapter, pair, DEAD_ADDRESS) + balance_of(
                adapter, pair, ZERO_ADDRESS
            )
            held = [
                Holding(role, address, percent(balance_of(adapter, pair, address), lp_supply))
                for address, role in wallets.items()
            ]
            liquidity.pools.append(Pool(quote, pair, percent(burned, lp_supply), held))
    except AdapterError as exc:
        liquidity.error = str(exc)
        return liquidity

    liquidity.findings = liquidity_findings(liquidity)
    return liquidity


def liquidity_findings(liquidity):
    findings = []
    for holding in liquidity.holdings:
        if holding.share >= NOTABLE_HOLDING:
            findings.append(
                Finding(
                    "concentrated_supply",
                    f"{holding.role} holds {holding.share}% of supply",
                    Severity.HIGH if holding.share >= LARGE_HOLDING else Severity.MEDIUM,
                    f"{holding.address} can sell {holding.share}% of all tokens into the market "
                    "at once.",
                )
            )
    for pool in liquidity.pools:
        controlled = [h for h in pool.held if h.share >= CONTROLLED_LIQUIDITY]
        for holding in controlled:
            findings.append(
                Finding(
                    "pullable_liquidity",
                    f"{holding.role} can pull the {pool.quote} liquidity",
                    Severity.HIGH,
                    f"{holding.address} holds {holding.share}% of the {liquidity.dex} "
                    f"{pool.quote} pool's liquidity tokens and can withdraw it, leaving holders "
                    "unable to sell (a rug pull).",
                )
            )
        if pool.burned >= BURNED_LIQUIDITY:
            findings.append(
                Finding(
                    "burned_liquidity",
                    f"{pool.quote} liquidity is burned",
                    Severity.INFO,
                    f"{pool.burned}% of the {liquidity.dex} {pool.quote} pool's liquidity tokens "
                    "were sent to an unspendable address, so that liquidity cannot be pulled.",
                )
            )
    if not liquidity.pools:
        findings.append(
            Finding(
                "no_pool",
                f"No {liquidity.dex} pool found",
                Severity.LOW,
                "No pair with the main quote tokens exists, so the token may not be tradable "
                "where buyers expect, or trades elsewhere.",
            )
        )
    return findings
