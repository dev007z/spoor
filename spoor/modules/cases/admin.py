from django.contrib import admin

from spoor.modules.cases.models import Case, CaseEvent


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ("name", "case_type", "created_by", "created_at")
    list_filter = ("case_type",)
    search_fields = ("name",)


@admin.register(CaseEvent)
class CaseEventAdmin(admin.ModelAdmin):
    """The audit trail can be read in the admin but never edited there."""

    list_display = ("created_at", "case", "actor", "event_type", "summary")
    list_filter = ("event_type",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
