"""Static checks on small contracts written for one pattern each, plus real recorded tokens."""

import json

import httpx
import pytest

from spoor.modules.chains.adapters.evm import ForbiddenMethodError, JsonRpcAdapter
from spoor.modules.chains.adapters.replay import ReplayTransport
from spoor.modules.chains.models import Address, Chain, RawResponse
from spoor.modules.contracts.analysis import analyze_contract
from spoor.modules.contracts.checks import Source, run_checks, strip_comments
from spoor.modules.contracts.etherscan import EtherscanClient
from spoor.modules.contracts.models import Contract
from spoor.modules.contracts.services import fetch_contract

OWNABLE = """
contract Token {
    address private _owner;
    modifier onlyOwner() { require(msg.sender == _owner); _; }
    function owner() public view returns (address) { return _owner; }
"""


def contract_with(body, name="Token", **fields):
    raw = RawResponse.record(
        source="test", endpoint="https://x.test", params={}, status_code=200, body="{}"
    )
    # A fresh address per contract: a contract is one-to-one with its address.
    address = Address.resolve(
        Chain.get_chain(key="bsc"), "0x" + format(Contract.objects.count() + 1, "040x")
    )
    defaults = {
        "name": name,
        "is_verified": True,
        "source_files": {f"{name}.sol": OWNABLE + body + "\n}"},
    }
    return Contract.objects.create(address=address, raw_response=raw, **{**defaults, **fields})


def checks(body, **fields):
    return {f.check: f for f in run_checks(contract_with(body, **fields))}


@pytest.mark.django_db
class TestChecks:
    def test_owner_only_mint(self):
        found = checks("function mint(address to, uint256 a) public onlyOwner { _mint(to, a); }")
        assert found["privileged_mint"].severity == "high"
        assert found["privileged_mint"].evidence[0].line == 6

    def test_internal_mint_is_not_a_power(self):
        assert "privileged_mint" not in checks("function _mint(address to, uint256 a) internal { }")

    def test_blacklist(self):
        found = checks(
            "mapping(address => bool) public isBlacklisted;\n"
            "function blacklist(address a) external onlyOwner { isBlacklisted[a] = true; }"
        )
        assert found["transfer_blocklist"].severity == "high"

    def test_unbounded_fee_setter_is_high(self):
        found = checks("function setSellFee(uint256 f) external onlyOwner { sellFee = f; }")
        assert found["modifiable_fees"].severity == "high"

    def test_bounded_fee_setter_is_medium(self):
        found = checks(
            "function setSellFee(uint256 f) external onlyOwner { require(f <= 10); sellFee = f; }"
        )
        assert found["modifiable_fees"].severity == "medium"

    def test_trading_switch_and_limits(self):
        found = checks(
            "function enableTrading() external onlyOwner { tradingOpen = true; }\n"
            "function setMaxTxAmount(uint256 m) external onlyOwner { maxTx = m; }"
        )
        assert found["trading_controls"].severity == "high"
        assert found["transfer_limits"].severity == "medium"

    def test_ownership_reclaim_trick(self):
        found = checks(
            "address private _previousOwner;\n"
            "function unlock() public {\n"
            "    require(_previousOwner == msg.sender); _owner = _previousOwner;\n}"
        )
        assert found["hidden_ownership"].severity == "high"

    def test_upgrade_needs_code_evidence_not_a_flag(self):
        assert "upgradeable" not in checks("function f() public {}", is_proxy=True)
        assert "upgradeable" in checks("function upgradeTo(address impl) external onlyOwner {}")

    def test_comments_never_trigger_findings(self):
        assert (
            checks("// function blacklist(address a) external onlyOwner {}\n/* mint onlyOwner */")
            == {}
        )

    def test_comment_stripping_keeps_line_numbers(self):
        code = "a\n/* one\n two */\nfunction mint() public onlyOwner {}"
        assert strip_comments(code).count("\n") == code.count("\n")
        assert Source({"T.sol": code}).find(r"function mint")[0].line == 4

    def test_unverified_contracts_have_no_findings(self):
        assert run_checks(contract_with("", is_verified=False)) == []


class FakeOwnerNode:
    """Answers owner() through the real JSON-RPC adapter, like a node would."""

    def __init__(self, owner):
        self.owner = owner

    def __call__(self, request):
        body = json.loads(request.content)
        assert body["method"] == "eth_call"
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": "0x" + self.owner[2:].rjust(64, "0")}
        )


def owner_adapter(owner):
    return JsonRpcAdapter(
        Chain.get_chain(key="ethereum"),
        transport=httpx.MockTransport(FakeOwnerNode(owner)),
        rpc_url="https://rpc.test/",
        min_interval=0,
    )


@pytest.mark.django_db
class TestRealTokens:
    """Real verified sources recorded from Etherscan on 2026-10-18."""

    def fetch(self, chain_key, address):
        client = EtherscanClient(
            api_key="k", transport=ReplayTransport("etherscan_sources"), min_interval=0
        )
        return fetch_contract(Chain.get_chain(key=chain_key), address, client)

    def test_bsc_usdt_owner_can_mint(self):
        contract = self.fetch("bsc", "0x55d398326f99059ff775485246999027b3197955")
        assert [f.check for f in run_checks(contract)] == ["privileged_mint"]

    def test_usdc_proxy_reports_its_implementations_powers_and_live_owner(self):
        proxy = self.fetch("ethereum", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
        owner = "0x" + "fc" * 20

        analysis = analyze_contract(proxy, adapter=owner_adapter(owner))

        found = {f.check for f in analysis.findings}
        assert {"privileged_mint", "transfer_blocklist", "trading_controls", "upgradeable"} <= found
        assert analysis.logic.name == "FiatTokenV2_2"
        assert analysis.ownership.owner == owner
        active = next(f for f in analysis.findings if f.check == "ownership")
        assert active.severity == "medium"

    def test_renounced_ownership_is_informational(self):
        contract = self.fetch("bsc", "0x55d398326f99059ff775485246999027b3197955")

        analysis = analyze_contract(contract, adapter=owner_adapter("0x" + "0" * 40))

        assert analysis.ownership.renounced
        assert next(f for f in analysis.findings if f.check == "ownership").severity == "info"


@pytest.mark.django_db
def test_rpc_client_refuses_anything_but_reads():
    """Spoor is read-only by construction: a write method never leaves the process."""
    calls = []
    adapter = JsonRpcAdapter(
        Chain.get_chain(key="bsc"),
        transport=httpx.MockTransport(calls.append),
        rpc_url="https://rpc.test/",
        min_interval=0,
    )

    for method in ("eth_sendRawTransaction", "eth_sendTransaction", "eth_sign", "personal_sign"):
        with pytest.raises(ForbiddenMethodError):
            adapter.call(method, [], cacheable=False)
    assert calls == []


class FakeTokenNode:
    """A node that answers totalSupply, balanceOf, getPair and owner like real contracts."""

    def __init__(self, supplies, balances, pairs, owner):
        self.supplies, self.balances, self.pairs, self.owner = supplies, balances, pairs, owner

    @staticmethod
    def word(value):
        return "0x" + format(value, "064x")

    def __call__(self, request):
        call = json.loads(request.content)["params"][0]
        to, data = call["to"].lower(), call["data"]
        selector, args = data[:10], data[10:]
        if selector == "0x18160ddd":
            result = self.word(self.supplies[to])
        elif selector == "0x70a08231":
            result = self.word(self.balances.get((to, "0x" + args[24:64]), 0))
        elif selector == "0xe6a43905":
            pair = self.pairs.get(("0x" + args[24:64], "0x" + args[88:128]), "0x" + "0" * 40)
            result = "0x" + pair[2:].rjust(64, "0")
        elif selector == "0x8da5cb5b":
            result = "0x" + self.owner[2:].rjust(64, "0")
        else:
            raise AssertionError(selector)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


@pytest.mark.django_db
class TestLiquidity:
    TOKEN = "0x" + "11" * 20
    PAIR = "0x" + "22" * 20
    DEPLOYER = "0x" + "33" * 20
    WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"

    def analyze(self, token_balances, lp_balances, owner=None):
        contract = contract_with(
            MINTABLE_BODY,
            deployer=self.DEPLOYER,
            abi=[{"type": "function", "name": "owner", "inputs": [], "stateMutability": "view"}],
        )
        contract.address.address = self.TOKEN
        contract.address.save()
        node = FakeTokenNode(
            supplies={self.TOKEN: 1000, self.PAIR: 100},
            balances={
                **{(self.TOKEN, holder): amount for holder, amount in token_balances.items()},
                **{(self.PAIR, holder): amount for holder, amount in lp_balances.items()},
            },
            pairs={(self.TOKEN, self.WBNB): self.PAIR},
            owner=owner or self.DEPLOYER,
        )
        adapter = JsonRpcAdapter(
            Chain.get_chain(key="bsc"),
            transport=httpx.MockTransport(node),
            rpc_url="https://rpc.test/",
            min_interval=0,
        )
        return analyze_contract(contract, adapter=adapter)

    def test_deployer_who_holds_supply_and_liquidity_is_a_rug_risk(self):
        analysis = self.analyze({self.DEPLOYER: 400}, {self.DEPLOYER: 90})

        found = {f.check: f for f in analysis.findings}
        assert found["concentrated_supply"].severity == "high"
        assert "40.00%" in found["concentrated_supply"].title
        assert found["pullable_liquidity"].severity == "high"
        assert analysis.liquidity.holdings[0].role == "Deployer and owner"

    def test_burned_liquidity_is_reported_and_not_pullable(self):
        dead = "0x000000000000000000000000000000000000dead"
        analysis = self.analyze({self.DEPLOYER: 10}, {dead: 99})

        found = {f.check for f in analysis.findings}
        assert "burned_liquidity" in found
        assert "pullable_liquidity" not in found
        assert analysis.liquidity.pools[0].burned == 99

    def test_liquidity_held_elsewhere_counts_as_others(self):
        analysis = self.analyze({}, {"0x" + "44" * 20: 100})

        assert analysis.liquidity.pools[0].others == 100


MINTABLE_BODY = "function mint(uint256 a) public onlyOwner {}"
