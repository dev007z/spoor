from django.contrib import admin

from spoor.modules.chains.models import Address, Chain, RawResponse, Token, Transfer


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
class RawResponseAdmin(admin.ModelAdmin):
    list_display = ("source", "endpoint", "status_code", "retrieved_at")
    list_filter = ("source", "status_code")
    search_fields = ("endpoint", "fingerprint")
    readonly_fields = [field.name for field in RawResponse._meta.fields]


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ("tx_hash", "log_index", "chain", "token", "from_address", "to_address")
    list_filter = ("chain", "token")
    search_fields = ("tx_hash",)
    list_select_related = ("chain", "token", "from_address", "to_address")
    raw_id_fields = ("from_address", "to_address", "raw_response")
