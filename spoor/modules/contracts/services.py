from spoor.modules.chains.models import Address
from spoor.modules.contracts.etherscan import EtherscanClient, EtherscanError
from spoor.modules.contracts.models import Contract


def fetch_contract(chain, address_value, client=None, follow_proxy=True):
    """Fetch a contract's verified source into the store.

    A proxy brings its implementation, one level only: the implementation is the logic
    that matters, and following further could chain or loop.
    """
    client = client or EtherscanClient()
    address = Address.resolve(chain, address_value)
    source, raw = client.get_source(chain, address.address)
    fields = {**source, **deployer_fields(client, chain, address.address), "raw_response": raw}
    contract, _ = Contract.objects.update_or_create(address=address, defaults=fields)
    if follow_proxy and contract.is_proxy and contract.implementation:
        fetch_contract(chain, contract.implementation, client, follow_proxy=False)
    return contract


def deployer_fields(client, chain, address):
    """Who deployed the contract, best effort: Etherscan's free plan lacks some chains."""
    try:
        deployer, creation_tx = client.get_creation(chain, address)
    except EtherscanError as exc:
        return {"deployer": "", "creation_tx": "", "deployer_note": str(exc)[:300]}
    return {"deployer": deployer, "creation_tx": creation_tx, "deployer_note": ""}
