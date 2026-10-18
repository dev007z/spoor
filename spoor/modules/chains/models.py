import hashlib
import json

from django.db import models
from django.utils import timezone

from spoor.common.functions import to_units
from spoor.common.mixins import ModelMixin
from spoor.modules.chains.addresses import normalize_address, normalize_tx_hash
from spoor.modules.chains.enums import ChainFamily

# Query parameters that carry credentials. They are stripped before a request is
# fingerprinted or stored, so no key ever reaches the database or a report.
SENSITIVE_PARAMS = frozenset({"apikey", "api_key", "key", "token", "access_token"})


class Chain(ModelMixin):
    key = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    family = models.CharField(max_length=10, choices=ChainFamily.choices)
    evm_chain_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    explorer_tx_url = models.CharField(max_length=200, help_text="Template with {tx_hash}.")
    explorer_address_url = models.CharField(max_length=200, help_text="Template with {address}.")

    def __str__(self):
        return self.name

    @classmethod
    def get_chain(cls, **kwargs):
        return cls.objects.filter(**kwargs).first()

    def normalize_address(self, value):
        return normalize_address(self.family, value)

    def normalize_tx_hash(self, value):
        return normalize_tx_hash(self.family, value)

    def tx_url(self, tx_hash):
        return self.explorer_tx_url.format(tx_hash=tx_hash)

    def address_url(self, address):
        return self.explorer_address_url.format(address=address)


class Token(ModelMixin):
    chain = models.ForeignKey(Chain, on_delete=models.PROTECT, related_name="tokens")
    contract = models.CharField(max_length=64)
    symbol = models.CharField(max_length=32)
    name = models.CharField(max_length=100)
    decimals = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["chain", "contract"], name="unique_token_per_chain"),
        ]

    def __str__(self):
        return f"{self.symbol} ({self.chain.key})"

    @classmethod
    def get_token(cls, chain, contract):
        return cls.objects.filter(chain=chain, contract=chain.normalize_address(contract)).first()

    def to_units(self, raw_amount):
        return to_units(raw_amount, self.decimals)


class Address(ModelMixin):
    chain = models.ForeignKey(Chain, on_delete=models.PROTECT, related_name="addresses")
    address = models.CharField(max_length=64)

    class Meta:
        verbose_name_plural = "addresses"
        constraints = [
            models.UniqueConstraint(fields=["chain", "address"], name="unique_address_per_chain"),
        ]

    def __str__(self):
        return self.address

    @classmethod
    def resolve(cls, chain, value):
        """The Address row for any accepted spelling of an address, created if new."""
        address, _ = cls.objects.get_or_create(chain=chain, address=chain.normalize_address(value))
        return address


class RawResponse(ModelMixin):
    """An API response exactly as received: the evidence every parsed record points back to."""

    source = models.CharField(
        max_length=64, db_index=True, help_text="Name of the adapter that made the request."
    )
    endpoint = models.CharField(max_length=500, help_text="URL without the query string.")
    params = models.JSONField(default=dict, help_text="Request parameters, credentials removed.")
    fingerprint = models.CharField(max_length=64, db_index=True)
    status_code = models.PositiveSmallIntegerField()
    body = models.TextField(help_text="Response body text, byte for byte as received.")
    body_sha256 = models.CharField(max_length=64)
    retrieved_at = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"{self.source} {self.endpoint} @ {self.retrieved_at:%Y-%m-%d %H:%M:%S}"

    @staticmethod
    def sanitize_params(params):
        return {k: v for k, v in params.items() if k.lower() not in SENSITIVE_PARAMS}

    @classmethod
    def compute_fingerprint(cls, source, endpoint, params):
        canonical = json.dumps(
            [source, endpoint, cls.sanitize_params(params)], sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def record(cls, *, source, endpoint, params, status_code, body, retrieved_at=None):
        return cls.objects.create(
            source=source,
            endpoint=endpoint,
            params=cls.sanitize_params(params),
            fingerprint=cls.compute_fingerprint(source, endpoint, params),
            status_code=status_code,
            body=body,
            body_sha256=hashlib.sha256(body.encode()).hexdigest(),
            retrieved_at=retrieved_at or timezone.now(),
        )

    @classmethod
    def get_latest(cls, *, source, endpoint, params):
        """The most recent stored response to this exact request, or None."""
        fingerprint = cls.compute_fingerprint(source, endpoint, params)
        return cls.objects.filter(fingerprint=fingerprint).order_by("-retrieved_at").first()


class Transfer(ModelMixin):
    """One token transfer event. A transaction can emit several, told apart by log_index."""

    chain = models.ForeignKey(Chain, on_delete=models.PROTECT, related_name="transfers")
    token = models.ForeignKey(Token, on_delete=models.PROTECT, related_name="transfers")
    tx_hash = models.CharField(max_length=66)
    log_index = models.PositiveIntegerField()
    block_number = models.PositiveBigIntegerField()
    timestamp = models.DateTimeField()
    from_address = models.ForeignKey(
        Address, on_delete=models.PROTECT, related_name="outgoing_transfers"
    )
    to_address = models.ForeignKey(
        Address, on_delete=models.PROTECT, related_name="incoming_transfers"
    )
    amount = models.DecimalField(
        max_digits=78, decimal_places=0, help_text="Raw integer amount; see token decimals."
    )
    raw_response = models.ForeignKey(
        RawResponse, on_delete=models.PROTECT, related_name="transfers"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["chain", "tx_hash", "log_index"], name="unique_transfer_event"
            ),
        ]
        indexes = [
            models.Index(fields=["from_address", "timestamp"]),
            models.Index(fields=["to_address", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.tx_hash}:{self.log_index}"

    @property
    def amount_units(self):
        return self.token.to_units(self.amount)
