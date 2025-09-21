from django.contrib import admin

from .models import ReferenceSourceBatch


@admin.register(ReferenceSourceBatch)
class ReferenceSourceBatchAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "project",
        "source_type",
        "search_date",
        "record_count",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("source_type", "project")
    search_fields = ("label", "project__title", "original_filename")


