import json

import httpx
import pytest

from spoor.modules.chains.adapters.replay import ReplayTransport
from spoor.modules.chains.models import Chain
from spoor.modules.contracts.etherscan import EtherscanClient, EtherscanError, split_source_files
from spoor.modules.contracts.models import Contract
from spoor.modules.contracts.services import fetch_contract

BSC_USDT = "0x55d398326f99059ff775485246999027b3197955"
USDC_PROXY = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDC_IMPLEMENTATION = "0x43506849d7c04f9138d1a2050bbf3a0c054402dd"


def recorded_client():
    return EtherscanClient(
        api_key="test-key", transport=ReplayTransport("etherscan_sources"), min_interval=0
    )


class TestSourceShapes:
    def test_plain_solidity_is_one_file(self):
        assert split_source_files("pragma solidity 0.8.0;", "Token") == {
            "Token.sol": "pragma solidity 0.8.0;"
        }

    def test_json_map_of_files(self):
        source = json.dumps({"A.sol": {"content": "a"}, "B.sol": {"content": "b"}})
        assert split_source_files(source, "A") == {"A.sol": "a", "B.sol": "b"}

    def test_double_braced_standard_json_input(self):
        standard = {"language": "Solidity", "sources": {"src/T.sol": {"content": "t"}}}
        assert split_source_files("{" + json.dumps(standard) + "}", "T") == {"src/T.sol": "t"}

    def test_unverified_has_no_files(self):
        assert split_source_files("", "") == {}


@pytest.mark.django_db
class TestFetchContract:
    """Against real Etherscan V2 responses recorded on 2026-10-18 (key stripped)."""

    def test_single_file_contract(self):
        contract = fetch_contract(Chain.get_chain(key="bsc"), BSC_USDT, recorded_client())

        assert contract.name == "BEP20USDT"
        assert contract.is_verified and not contract.is_proxy
        assert list(contract.source_files) == ["BEP20USDT.sol"]
        assert "mint" in {f["name"] for f in contract.abi_functions()}

    def test_proxy_brings_its_implementation_one_level(self):
        proxy = fetch_contract(Chain.get_chain(key="ethereum"), USDC_PROXY, recorded_client())

        assert proxy.is_proxy
        assert proxy.implementation.lower() == USDC_IMPLEMENTATION
        implementation = Contract.objects.get(address__address=USDC_IMPLEMENTATION)
        assert implementation.name == "FiatTokenV2_2"
        assert len(implementation.source_files) > 10
        assert Contract.objects.count() == 2

    def test_key_never_reaches_the_evidence(self):
        contract = fetch_contract(Chain.get_chain(key="bsc"), BSC_USDT, recorded_client())

        assert "apikey" not in contract.raw_response.params
        assert "test-key" not in json.dumps(contract.raw_response.params)

    def test_missing_key_explains_the_setting(self, settings):
        settings.ETHERSCAN_API_KEY = ""
        with pytest.raises(EtherscanError, match="ETHERSCAN_API_KEY"):
            EtherscanClient()

    def test_etherscan_errors_are_not_cached(self):
        refusal = {"status": "0", "message": "NOTOK", "result": "Invalid API Key"}
        client = EtherscanClient(
            api_key="bad",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=refusal)),
            min_interval=0,
        )

        with pytest.raises(EtherscanError, match="Invalid API Key"):
            fetch_contract(Chain.get_chain(key="bsc"), BSC_USDT, client)


@pytest.mark.django_db
class TestContractPages:
    def test_detail_lists_state_changing_functions_first(self, admin_client, monkeypatch):
        monkeypatch.setattr(
            "spoor.modules.contracts.analysis.read_ownership", lambda *args, **kwargs: None
        )
        contract = fetch_contract(Chain.get_chain(key="bsc"), BSC_USDT, recorded_client())

        response = admin_client.get(f"/contracts/{contract.pk}/")

        kinds = [
            f.get("stateMutability") in ("view", "pure") for f in response.context["functions"]
        ]
        assert kinds == sorted(kinds)

    def test_lookup_shows_provider_errors(self, admin_client, settings):
        settings.ETHERSCAN_API_KEY = ""
        bsc = Chain.get_chain(key="bsc")

        response = admin_client.post("/contracts/", {"chain": bsc.pk, "address": BSC_USDT})

        assert "ETHERSCAN_API_KEY" in response.context["error"]
