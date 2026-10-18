"""Verified contract source and ABI from Etherscan API V2 (free on every chain).

Etherscan returns SourceCode in one of three shapes: plain Solidity (one file), a
JSON object of {file: {content}}, or standard JSON input wrapped in double braces
"{{...}}" with the files under "sources". All three become {file name: source}.
"""

import json

from django.conf import settings
from django.utils import timezone

from spoor.modules.chains.adapters.base import ProviderError
from spoor.modules.chains.adapters.http import ProviderClient

BASE_URL = "https://api.etherscan.io/v2/api"


class EtherscanError(ProviderError):
    pass


def check_etherscan(data):
    if data.get("status") != "1":
        raise EtherscanError(f"Etherscan: {data.get('message')} ({str(data.get('result'))[:200]})")


class EtherscanClient:
    source = "etherscan"

    def __init__(self, api_key=None, transport=None, min_interval=0.4):
        self.api_key = api_key if api_key is not None else settings.ETHERSCAN_API_KEY
        if not self.api_key:
            raise EtherscanError("Set ETHERSCAN_API_KEY in .env to analyze contracts.")
        self.client = ProviderClient(self.source, min_interval=min_interval, transport=transport)

    def get_source(self, chain, address):
        """(parsed source dict, RawResponse). Unverified answers are re-checked, not reused."""
        params = {
            "chainid": chain.evm_chain_id,
            "module": "contract",
            "action": "getsourcecode",
            "address": address,
            "apikey": self.api_key,
        }
        started = timezone.now()
        data, raw = self.client.get_json(BASE_URL, params, cacheable=True, check=check_etherscan)
        result = parse_source(data["result"][0])
        if not result["is_verified"] and raw.retrieved_at < started:
            # A cached "not verified" may be stale: the contract can be verified since.
            data, raw = self.client.get_json(
                BASE_URL, params, cacheable=False, check=check_etherscan
            )
            result = parse_source(data["result"][0])
        return result, raw


def parse_source(item):
    source_code = item.get("SourceCode", "")
    abi_text = item.get("ABI", "")
    is_verified = bool(source_code) and not abi_text.startswith("Contract source code not verified")
    return {
        "is_verified": is_verified,
        "name": item.get("ContractName", ""),
        "compiler_version": item.get("CompilerVersion", ""),
        "source_files": split_source_files(source_code, item.get("ContractName", "")),
        "abi": json.loads(abi_text) if is_verified else [],
        "is_proxy": item.get("Proxy") == "1",
        "implementation": item.get("Implementation", ""),
    }


def split_source_files(source_code, contract_name):
    if not source_code:
        return {}
    text = source_code.strip()
    if text.startswith("{{") and text.endswith("}}"):
        standard_input = json.loads(text[1:-1])
        return {name: entry["content"] for name, entry in standard_input["sources"].items()}
    if text.startswith("{"):
        try:
            files = json.loads(text)
        except json.JSONDecodeError:
            return {f"{contract_name or 'Contract'}.sol": source_code}
        return {name: entry["content"] for name, entry in files.items()}
    return {f"{contract_name or 'Contract'}.sol": source_code}
