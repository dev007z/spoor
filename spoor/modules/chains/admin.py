from django.contrib import admin

from spoor.modules.chains.models import Address, Chain, RawResponse, Token, Transfer


class EvidenceAdmin(admin.ModelAdmin):
    """Evidence is written only by adapters; the admin may inspect it, never alter it."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Chain)
class ChainAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "family", "evm_chain_id")


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ("symbol", "chain", "contract", "decimals")
    list_filter = ("chain",)
    search_fields = ("symbol", "contract")


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("address", "chain", "created_at")
    list_filter = ("chain",)
    search_fields = ("address",)


@admin.register(RawResponse)
class RawResponseAdmin(EvidenceAdmin):
    list_display = ("source", "endpoint", "status_code", "retrieved_at")
    list_filter = ("source", "status_code")
    search_fields = ("endpoint", "fingerprint")


@admin.register(Transfer)
class TransferAdmin(EvidenceAdmin):
    list_display = ("timestamp", "chain", "amount_display", "from_address", "to_address", "tx_hash")
    list_filter = ("chain", "token")
    search_fields = ("tx_hash", "from_address__address", "to_address__address")
    list_select_related = ("chain", "token", "from_address", "to_address")
    ordering = ("-timestamp",)

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, transfer):
        return f"{transfer.amount_units:,} {transfer.token.symbol}"
