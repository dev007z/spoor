from django.db import models

from spoor.common.mixins import ModelMixin
from spoor.modules.chains.models import Address, RawResponse


class Contract(ModelMixin):
    """A token contract's verified source and ABI, as published on Etherscan."""

    address = models.OneToOneField(Address, on_delete=models.PROTECT, related_name="contract")
    name = models.CharField(max_length=200, blank=True)
    is_verified = models.BooleanField(default=False)
    compiler_version = models.CharField(max_length=100, blank=True)
    source_files = models.JSONField(default=dict, help_text="{file name: source code}")
    abi = models.JSONField(default=list)
    is_proxy = models.BooleanField(default=False)
    implementation = models.CharField(max_length=64, blank=True)
    deployer = models.CharField(max_length=64, blank=True)
    creation_tx = models.CharField(max_length=66, blank=True)
    deployer_note = models.CharField(
        max_length=300, blank=True, help_text="Why the deployer is unknown, when it is."
    )
    raw_response = models.ForeignKey(
        RawResponse, on_delete=models.PROTECT, related_name="contracts"
    )

    def __str__(self):
        return self.name or self.address.address

    @property
    def chain(self):
        return self.address.chain

    @property
    def source(self):
        """All source files joined, for checks that scan the whole contract."""
        return "\n".join(self.source_files.values())

    def abi_functions(self):
        return [item for item in self.abi if item.get("type") == "function"]
