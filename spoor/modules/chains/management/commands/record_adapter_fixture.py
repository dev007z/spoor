"""Record a real adapter run as a test fixture.

    uv run python manage.py record_adapter_fixture tron <address> \
        --start 2026-10-17T10:00:00Z --end 2026-10-17T11:00:00Z --name tron_usdt_small

Uses the adapter options from settings (including API keys from .env). Keys never
reach the recording; review the file before committing it anyway.
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from spoor.modules.chains.adapters.registry import get_adapter, get_adapter_config
from spoor.modules.chains.adapters.replay import RECORDINGS_DIR, RecordingTransport
from spoor.modules.chains.models import Chain, Token


class Command(BaseCommand):
    help = "Run an adapter against the live provider and save the exchanges as a recording."

    def add_arguments(self, parser):
        parser.add_argument("chain", help="Chain key, e.g. tron or bsc.")
        parser.add_argument("address")
        parser.add_argument("--start", required=True, type=datetime.fromisoformat)
        parser.add_argument("--end", required=True, type=datetime.fromisoformat)
        parser.add_argument("--name", required=True, help="Recording file name, without .json.")
        parser.add_argument("--token", default="USDT", help="Token symbol on that chain.")
        parser.add_argument("--max-records", type=int, default=500)

    def handle(self, *args, **options):
        chain = Chain.get_chain(key=options["chain"])
        if chain is None:
            raise CommandError(f"Unknown chain {options['chain']!r}")
        token = Token.objects.filter(chain=chain, symbol=options["token"]).first()
        if token is None:
            raise CommandError(f"No {options['token']} token on {chain.key}")

        adapter_class, _ = get_adapter_config(chain)
        transport = RecordingTransport(
            RECORDINGS_DIR / f"{options['name']}.json",
            redact_path=adapter_class.redacts_url_path,
        )
        adapter = get_adapter(chain, transport=transport)
        adapter.client.use_cache = False
        result = adapter.get_token_transfers(
            options["address"], token, options["start"], options["end"], options["max_records"]
        )
        transport.save()

        self.stdout.write(
            f"Recorded {len(transport.exchanges)} exchanges, {len(result.records)} transfers "
            f"(complete={result.complete}) to {transport.path}"
        )
