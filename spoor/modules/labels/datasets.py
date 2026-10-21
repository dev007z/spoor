"""Contributed label datasets: reviewed JSON files under labels/data/.

A file holds one dataset:

    {
      "key": "example-exchanges",
      "name": "Example exchanges",
      "description": "Where these labels come from.",
      "labels": [
        {"chain": "tron", "address": "T...", "entity": "Example Exchange",
         "category": "exchange", "confidence": "high",
         "source_url": "https://example.com/proof-of-reserves"}
      ]
    }

Every entry is validated before anything is written, so a bad file changes nothing.
"""

import json
from pathlib import Path

from spoor.modules.chains.addresses import InvalidAddressError
from spoor.modules.chains.models import Chain
from spoor.modules.labels.enums import LabelCategory, LabelConfidence
from spoor.modules.labels.models import LabelDataset

DATA_DIR = Path(__file__).resolve().parent / "data"
LABEL_FIELDS = ("chain", "address", "entity", "category", "confidence", "source_url")


class DatasetFileError(ValueError):
    pass


def load_dataset_file(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise DatasetFileError(f"{path.name}: not valid JSON ({exc})") from exc

    for field in ("key", "name", "labels"):
        if field not in data:
            raise DatasetFileError(f"{path.name}: missing '{field}'")

    chains = {chain.key: chain for chain in Chain.objects.all()}
    entries = [validate_entry(path.name, i, raw, chains) for i, raw in enumerate(data["labels"])]
    return LabelDataset.sync(
        data["key"], data["name"], entries, description=data.get("description", "")
    )


def validate_entry(filename, index, raw, chains):
    where = f"{filename}: label {index}"
    missing = [f for f in LABEL_FIELDS if not raw.get(f)]
    if missing:
        raise DatasetFileError(f"{where}: missing {', '.join(missing)}")
    chain = chains.get(raw["chain"])
    if chain is None:
        raise DatasetFileError(f"{where}: unknown chain {raw['chain']!r}")
    if raw["category"] not in LabelCategory.values:
        raise DatasetFileError(f"{where}: unknown category {raw['category']!r}")
    if raw["confidence"] not in LabelConfidence.values:
        raise DatasetFileError(f"{where}: unknown confidence {raw['confidence']!r}")
    if not raw["source_url"].startswith("https://"):
        raise DatasetFileError(f"{where}: source_url must be an https link to the public source")
    try:
        address = chain.normalize_address(raw["address"])
    except InvalidAddressError as exc:
        raise DatasetFileError(f"{where}: {exc}") from exc
    return {**{f: raw[f] for f in LABEL_FIELDS}, "chain": chain, "address": address}
