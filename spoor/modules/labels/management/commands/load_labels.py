from django.core.management.base import BaseCommand, CommandError

from spoor.modules.labels.datasets import DATA_DIR, DatasetFileError, load_dataset_file


class Command(BaseCommand):
    help = "Load label dataset files (default: every JSON file in labels/data/)."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="*")

    def handle(self, *args, **options):
        paths = options["paths"] or sorted(DATA_DIR.glob("*.json"))
        if not paths:
            self.stdout.write("No dataset files found.")
            return
        for path in paths:
            try:
                dataset, count = load_dataset_file(path)
            except DatasetFileError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(f"{dataset.key}: {count} labels")
