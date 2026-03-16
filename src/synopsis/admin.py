from django.contrib import admin

from .models import (
    CollaborativeSession,
    IUCNCategory,
    LibraryImportBatch,
    LibraryReference,
    SynopsisInterventionKeyMessage,
    ReferenceSourceBatch,
    Reference,
)


@admin.register(ReferenceSourceBatch)
class ReferenceSourceBatchAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "project",
        "source_type",
        "display_date_range",
        "record_count",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("source_type", "project")
    search_fields = ("label", "project__title", "original_filename")

    @admin.display(description="Date range")
    def display_date_range(self, obj):
        start = obj.search_date_start
        end = obj.search_date_end
        if start and end:
            return f"{start} – {end}"
        if start:
            return f"From {start}"
        if end:
            return f"Until {end}"
        return "—"


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


@admin.register(LibraryImportBatch)
class LibraryImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "source_type",
        "display_date_range",
        "record_count",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("source_type",)
    search_fields = ("label", "original_filename")

    @admin.display(description="Date range")
    def display_date_range(self, obj):
        start = obj.search_date_start
        end = obj.search_date_end
        if start and end:
            return f"{start} – {end}"
        if start:
            return f"From {start}"
        if end:
            return f"Until {end}"
        return "—"


@admin.register(LibraryReference)
class LibraryReferenceAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "publication_year",
        "journal",
        "doi",
        "import_batch",
    )
    list_filter = ("import_batch",)
    search_fields = ("title", "doi", "authors", "journal")


@admin.register(IUCNCategory)
class IUCNCategoryAdmin(admin.ModelAdmin):
    list_display = ("kind", "code", "name", "is_active", "position")
    list_filter = ("kind", "is_active")
    search_fields = ("code", "name")
    ordering = ("kind", "position", "name")


@admin.register(SynopsisInterventionKeyMessage)
class SynopsisInterventionKeyMessageAdmin(admin.ModelAdmin):
    list_display = (
        "intervention",
        "response_group",
        "outcome_label",
        "study_count",
        "position",
    )
    list_filter = ("response_group",)
    search_fields = ("intervention__title", "outcome_label", "statement")
    filter_horizontal = ("supporting_summaries",)


@admin.register(CollaborativeSession)
class CollaborativeSessionAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "document_type",
        "started_by",
        "started_at",
        "is_active",
        "ended_at",
    )
    list_filter = ("document_type", "is_active")
    search_fields = ("project__title", "started_by__username", "token")
    filter_horizontal = ("invitations",)
    readonly_fields = (
        "token",
        "started_at",
        "last_activity_at",
        "ended_at",
        "last_participant_name",
        "last_callback_payload",
        "initial_protocol_revision",
        "initial_action_list_revision",
        "result_protocol_revision",
        "result_action_list_revision",
        "change_summary",
    )
