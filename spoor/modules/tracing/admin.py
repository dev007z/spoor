from django.contrib import admin

from spoor.modules.tracing.models import TraceEdge, TraceNode, TraceRun


@admin.register(TraceRun)
class TraceRunAdmin(admin.ModelAdmin):
    list_display = ("created_at", "token", "direction", "status", "max_hops", "addresses_expanded")
    list_filter = ("status", "direction")
    readonly_fields = ("status", "error", "started_at", "finished_at", "addresses_expanded")


@admin.register(TraceNode)
class TraceNodeAdmin(admin.ModelAdmin):
    list_display = ("address", "run", "hop", "expanded", "stop_reason", "label")
    list_filter = ("stop_reason", "expanded")
    list_select_related = ("address", "run", "label")
    raw_id_fields = ("run", "address", "label")


@admin.register(TraceEdge)
class TraceEdgeAdmin(admin.ModelAdmin):
    list_display = ("transfer", "run", "hop")
    raw_id_fields = ("run", "transfer")
