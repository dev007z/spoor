"""Labels from the OFAC Specially Designated Nationals (SDN) list.

OFAC publishes digital currency addresses as `id` entries of type
"Digital Currency Address - <currency>". Each address becomes a SANCTIONED label
citing its SDN entry. The currency decides the chain:

- TRX: TRON.
- ETH, BSC, BNB: every supported EVM chain, since one EVM key controls the same
  address on all of them.
- USDT, USDC: routed by address format (T... is TRON, 0x... is EVM). Other formats
  (for example Omni addresses on Bitcoin) are skipped.
- Anything else: skipped, as Spoor does not trace that chain.
"""

from dataclasses import dataclass, field

import defusedxml.ElementTree as ET

from spoor.modules.chains.addresses import InvalidAddressError
from spoor.modules.chains.models import Chain
from spoor.modules.labels.enums import LabelCategory, LabelConfidence
from spoor.modules.labels.models import LabelDataset

SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/publicationpreview/exports/sdn.xml"
ENTRY_URL = "https://sanctionssearch.ofac.treas.gov/Details.aspx?id={uid}"
DATASET_KEY = "ofac-sdn"
ADDRESS_ID_PREFIX = "Digital Currency Address - "

EVM_CHAINS = ("ethereum", "bsc")
CURRENCY_CHAINS = {"TRX": ("tron",), "ETH": EVM_CHAINS, "BSC": EVM_CHAINS, "BNB": EVM_CHAINS}
FORMAT_ROUTED = frozenset({"USDT", "USDC"})


@dataclass(frozen=True)
class SanctionedAddress:
    chain_key: str
    address: str
    entity: str
    source_url: str


@dataclass
class SdnPublication:
    publish_date: str = ""
    addresses: list[SanctionedAddress] = field(default_factory=list)
    skipped_currencies: dict[str, int] = field(default_factory=dict)


def chains_for(currency, address):
    if currency in CURRENCY_CHAINS:
        return CURRENCY_CHAINS[currency]
    if currency in FORMAT_ROUTED:
        if address.startswith("T"):
            return ("tron",)
        if address.startswith("0x"):
            return EVM_CHAINS
    return ()


def parse_sdn(source):
    """Parse SDN.XML from a path or file object, streaming so the full list stays cheap."""
    publication = SdnPublication()
    for _, element in ET.iterparse(source, events=("end",)):
        tag = local_name(element.tag)
        if tag == "Publish_Date":
            publication.publish_date = element.text or ""
        elif tag == "sdnEntry":
            read_entry(element, publication)
            element.clear()
    return publication


def read_entry(entry, publication):
    uid = child_text(entry, "uid")
    name = " ".join(filter(None, [child_text(entry, "firstName"), child_text(entry, "lastName")]))
    for id_element in entry.iter():
        if local_name(id_element.tag) != "id":
            continue
        id_type = child_text(id_element, "idType")
        if not id_type.startswith(ADDRESS_ID_PREFIX):
            continue
        currency = id_type.removeprefix(ADDRESS_ID_PREFIX).strip()
        address = child_text(id_element, "idNumber").strip()
        chains = chains_for(currency, address)
        if not chains:
            publication.skipped_currencies[currency] = (
                publication.skipped_currencies.get(currency, 0) + 1
            )
        for chain_key in chains:
            publication.addresses.append(
                SanctionedAddress(
                    chain_key=chain_key,
                    address=address,
                    entity=name[:200],
                    source_url=ENTRY_URL.format(uid=uid),
                )
            )


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(element, name):
    for child in element:
        if local_name(child.tag) == name:
            return child.text or ""
    return ""


@dataclass(frozen=True)
class ImportSummary:
    labels: int
    unsupported: int
    skipped_currencies: dict[str, int]


def import_publication(publication):
    """Sync the OFAC dataset to the publication. Delisted addresses lose their label."""
    chains = {chain.key: chain for chain in Chain.objects.all()}
    entries, unsupported = [], 0
    for item in publication.addresses:
        chain = chains.get(item.chain_key)
        if chain is None:
            continue
        try:
            address = chain.normalize_address(item.address)
        except InvalidAddressError:
            unsupported += 1
            continue
        entries.append(
            {
                "chain": chain,
                "address": address,
                "entity": item.entity,
                "category": LabelCategory.SANCTIONED,
                "confidence": LabelConfidence.HIGH,
                "source_url": item.source_url,
            }
        )
    _, count = LabelDataset.sync(
        DATASET_KEY,
        "OFAC SDN list",
        entries,
        description=(
            "Digital currency addresses on the US Treasury OFAC Specially Designated Nationals "
            f"list, published {publication.publish_date}. Source: {SDN_URL}"
        ),
    )
    return ImportSummary(count, unsupported, publication.skipped_currencies)
