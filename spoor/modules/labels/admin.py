from django.contrib import admin

from spoor.modules.labels.models import Label, LabelDataset


@admin.register(LabelDataset)
class LabelDatasetAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "visibility")


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ("entity", "category", "confidence", "address", "dataset")
    list_filter = ("dataset", "category", "confidence")
    search_fields = ("entity", "address__address")
    list_select_related = ("address", "dataset")
    raw_id_fields = ("address",)
