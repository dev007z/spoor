"""Reference data: the supported chains and the USDT contracts the adapters start with."""

from django.db import migrations

CHAINS = [
    {
        "key": "tron",
        "name": "TRON",
        "family": "tron",
        "evm_chain_id": None,
        "explorer_tx_url": "https://tronscan.org/#/transaction/{tx_hash}",
        "explorer_address_url": "https://tronscan.org/#/address/{address}",
    },
    {
        "key": "bsc",
        "name": "BNB Smart Chain",
        "family": "evm",
        "evm_chain_id": 56,
        "explorer_tx_url": "https://bscscan.com/tx/{tx_hash}",
        "explorer_address_url": "https://bscscan.com/address/{address}",
    },
    {
        "key": "ethereum",
        "name": "Ethereum",
        "family": "evm",
        "evm_chain_id": 1,
        "explorer_tx_url": "https://etherscan.io/tx/{tx_hash}",
        "explorer_address_url": "https://etherscan.io/address/{address}",
    },
]

# Contracts stored in canonical form (see spoor/modules/chains/addresses.py).
TOKENS = [
    ("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "USDT", "Tether USD", 6),
    ("bsc", "0x55d398326f99059ff775485246999027b3197955", "USDT", "Binance-Peg BSC-USD", 18),
    ("ethereum", "0xdac17f958d2ee523a2206206994597c13d831ec7", "USDT", "Tether USD", 6),
]


def seed(apps, schema_editor):
    Chain = apps.get_model("chains", "Chain")
    Token = apps.get_model("chains", "Token")

    for chain_data in CHAINS:
        Chain.objects.update_or_create(key=chain_data["key"], defaults=chain_data)

    for chain_key, contract, symbol, name, decimals in TOKENS:
        Token.objects.update_or_create(
            chain=Chain.objects.get(key=chain_key),
            contract=contract,
            defaults={"symbol": symbol, "name": name, "decimals": decimals},
        )


class Migration(migrations.Migration):
    dependencies = [("chains", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
