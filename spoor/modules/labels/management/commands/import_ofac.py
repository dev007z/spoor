import io

import httpx
from django.core.management.base import BaseCommand

from spoor.modules.labels.ofac import SDN_URL, import_publication, parse_sdn


class Command(BaseCommand):
    help = "Import digital currency addresses from the OFAC SDN list as sanctioned labels."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", help="A local SDN.XML instead of downloading the current one."
        )

    def handle(self, *args, **options):
        if options["file"]:
            source = options["file"]
        else:
            self.stdout.write(f"Downloading {SDN_URL}")
            response = httpx.get(SDN_URL, follow_redirects=True, timeout=300)
            response.raise_for_status()
            source = io.BytesIO(response.content)

        publication = parse_sdn(source)
        summary = import_publication(publication)

        self.stdout.write(
            f"OFAC SDN list published {publication.publish_date}: {summary.labels} labels "
            f"on supported chains; {summary.unsupported} in an unsupported address format skipped."
        )
        if summary.skipped_currencies:
            skipped = ", ".join(f"{c} {n}" for c, n in sorted(summary.skipped_currencies.items()))
            self.stdout.write(f"Not traced by Spoor, skipped: {skipped}")
