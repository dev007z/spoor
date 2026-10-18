# Spoor

Trace the money, and explain the contract that stole it.

Spoor is an open-source tool for on-chain investigations. Paste an address, a transaction hash, or a token contract and get a hop-by-hop fund-flow graph, a risk breakdown of any token contract involved, and an exportable report where every claim is tied to a transaction hash, block, timestamp, and data source.

> **Status:** 0.1.0, the first usable release. Expect rough edges.

## What it does

- **Trace funds** forward or backward from an address or a transaction, hop by hop, across TRON and BNB Smart Chain or Ethereum (USDT first). Traces run in the background and draw a live fund-flow graph; expand any address by hand.
- **Keep evidence.** Every transfer is parsed from a stored provider response, kept byte for byte with its SHA-256 and retrieval time, and linked from the transfer it produced.
- **Know the endpoints.** Labeled exchanges, bridges and mixers stop a trace; the US Treasury OFAC SDN list is imported as sanctioned labels, and contributors can add sourced datasets.
- **Screen addresses** for direct labels and labeled counterparties, and see exposure on every trace.
- **Spot patterns** with heuristic signals (starting with collection wallets), always shown as signals, never as attribution.
- **Analyze token contracts:** verified source from Etherscan, static checks for owner powers (minting, blocklists, fees, pausing, upgrades, ownership reclaim), live ownership, supply and DEX liquidity control, and one click to trace the deployer.
- **Work in cases** with an append-only history and analyst notes on addresses.
- **Issue reports:** frozen HTML and PDF with the graph, every transfer's hash, log index and block, the methodology, and a manifest hashing all cited evidence.

## Principles

- **Read-only.** Spoor never signs or sends transactions and never holds private keys.
- **Public data only.** Labels come from public sources, each with a citation.
- **Reproducible.** Every finding can be re-derived from the cited transactions.

## Quickstart (Docker)

Requires Docker with Compose.

```bash
cp .env.example .env
```

Fill in `SECRET_KEY` and `POSTGRES_PASSWORD` in `.env`, then:

```bash
docker compose up --build
```

In a second terminal, create your login:

```bash
docker compose exec web python manage.py createsuperuser
```

Load the OFAC sanctions list as labels (re-run it to pick up OFAC updates):

```bash
docker compose exec web python manage.py import_ofac
```

Open http://localhost:8000.

## Configuration

All settings come from `.env` (see `.env.example`).

| Setting | Needed for | Notes |
|---|---|---|
| `SECRET_KEY`, `POSTGRES_*` | Everything | Required. |
| `TRONGRID_API_KEY` | TRON | Optional; without it TronGrid is limited to about one request per second. |
| `BSC_RPC_URL`, `ETHEREUM_RPC_URL` | BNB Smart Chain, Ethereum | A JSON-RPC endpoint that serves `eth_getLogs`. Free public nodes only serve recent blocks; investigations need archive access. |
| `ETHERSCAN_API_KEY` | Contract analysis | Free key; verified source works on every chain. |
| `HTTPS` | Production | Set to `true` behind TLS for secure cookies, HSTS and redirects. |

## Limitations

- Free RPC nodes refuse older blocks, so deep or old traces need an archive-capable RPC provider.
- Etherscan's free plan does not return contract creators on some chains (BNB Smart Chain among them); add the deployer by hand when tracing it.
- Liquidity locked in locker contracts is reported as held by others; lockers are not identified yet.
- Honeypot (buy-then-sell) simulation is not included yet.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env               # set SECRET_KEY, POSTGRES_PASSWORD, and DEBUG=true
uv sync                            # create the virtualenv and install dependencies
uv run pre-commit install          # lint, format, and secret scanning on every commit
docker compose up -d db redis      # Postgres and Redis only
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Run the tests with `uv run pytest`.

## Disclaimer

Spoor's output is an investigative lead, not proof of who controls an address. Labels and heuristics can be wrong; verify findings independently before acting on them. How you use this tool is your responsibility. Spoor is provided as is, without warranty of any kind; see the [license](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), including the label policy.

## License

[Apache-2.0](LICENSE)
