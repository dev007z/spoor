# Spoor

Trace the money, and explain the contract that stole it.

Spoor is an open-source tool for on-chain investigations. Paste an address, a transaction hash, or a token contract and get a hop-by-hop fund-flow graph, a risk breakdown of any token contract involved, and an exportable report where every claim is tied to a transaction hash, block, timestamp, and data source.

> **Status:** early development. See [docs/sprint.md](docs/sprint.md) for the plan.

## Principles

- **Read-only.** Spoor never signs or sends transactions and never holds private keys.
- **Public data only.** Labels come from public sources, each with a citation.
- **Reproducible.** Every finding can be re-derived from the cited transactions. How tracing and heuristics work is documented in [docs/methodology.md](docs/methodology.md).

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

Open http://localhost:8000.

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
