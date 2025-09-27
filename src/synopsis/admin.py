from django.contrib import admin

from .models import ReferenceSourceBatch, Reference


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


@admin.register(Reference)
class ReferenceAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "project",
        "batch",
        "publication_year",
        "screening_status",
        "screened_by",
    )
    list_filter = ("screening_status", "project", "batch")
    search_fields = ("title", "doi", "authors", "journal")
