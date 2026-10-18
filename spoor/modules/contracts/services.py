from spoor.modules.chains.models import Address
from spoor.modules.contracts.etherscan import EtherscanClient
from spoor.modules.contracts.models import Contract


def fetch_contract(chain, address_value, client=None, follow_proxy=True):
    """Fetch a contract's verified source into the store.

    A proxy brings its implementation, one level only: the implementation is the logic
    that matters, and following further could chain or loop.
    """
    client = client or EtherscanClient()
    address = Address.resolve(chain, address_value)
    source, raw = client.get_source(chain, address.address)
    contract, _ = Contract.objects.update_or_create(
        address=address, defaults={**source, "raw_response": raw}
    )
    if follow_proxy and contract.is_proxy and contract.implementation:
        fetch_contract(chain, contract.implementation, client, follow_proxy=False)
    return contract
