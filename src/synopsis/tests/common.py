"""Shared imports for the synopsis test suite.

The test modules intentionally import this namespace wholesale so the split from
the former monolithic tests.py stays mechanical and keeps private view helper
coverage intact.
"""

import csv
from datetime import date, datetime, timedelta
import importlib
import io
import json
import re
from urllib.parse import urlparse
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
import jwt
import rispy
from django.contrib.auth.models import Group, User, AnonymousUser
from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings, RequestFactory, SimpleTestCase
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.core.management.base import CommandError
from django.urls import reverse

import shutil
import tempfile
import textwrap
from django.utils import timezone
from django.core.management import call_command

from ..models import (
    AdvisoryBoardInvitation,
    AdvisoryBoardMember,
    AdvisoryBoardCustomField,
    AdvisoryBoardCustomFieldValueHistory,
    Funder,
    IUCNCategory,
    Project,
    ProjectChangeLog,
    ProtocolFeedback,
    Protocol,
    ProtocolRevision,
    ActionList,
    ActionListRevision,
    ActionListFeedback,
    CollaborativeSession,
    UserRole,
    LibraryReference,
    LibraryReferenceFolderHistory,
    LibraryImportBatch,
    ReferenceSourceBatch,
    ReferenceSourceBatchNoteHistory,
    Reference,
    ReferenceSummary,
    ReferenceSummaryComment,
    ReferenceActionSummary,
    SynopsisChapter,
    SynopsisSubheading,
    SynopsisIntervention,
    SynopsisInterventionKeyMessage,
    SynopsisAssignment,
    SynopsisExportLog,
    SynopsisFeedback,
)
from ..forms import (
    ActionListReminderScheduleForm,
    ActionListSendForm,
    AdvisoryBulkInviteForm,
    AdvisoryBoardMemberForm,
    AdvisoryInviteForm,
    AdvisoryMemberCustomDataForm,
    FunderForm,
    FunderContactFormSet,
    ProtocolSendForm,
    ProtocolReminderScheduleForm,
    ProjectDeleteForm,
    ProjectSettingsForm,
    ReminderScheduleForm,
    IUCN_ACTION_CHOICES,
    IUCN_HABITAT_CHOICES,
    IUCN_THREAT_CHOICES,
    ReferenceSummaryDraftForm,
    ReferenceSummaryUpdateForm,
    SynopsisBackgroundForm,
    SynopsisKeyMessageForm,
)
from ..email_backends import AttachmentSummaryConsoleEmailBackend
from ..utils import (
    BRAND,
    GLOBAL_GROUPS,
    InlineMarkupSegment,
    default_action_list_review_message,
    default_advisory_invitation_message,
    default_protocol_review_message,
    default_synopsis_review_message,
    email_subject,
    ensure_global_groups,
    format_inline_markup_html,
    reference_summary_effective_citation,
    reference_hash,
    reply_to_list,
    split_inline_markup,
    split_inline_italic_markup,
)
from ..views import (
    _advisory_board_context,
    _apply_revision_to_action_list,
    _apply_revision_to_protocol,
    _build_advisory_invitation_email,
    _build_onlyoffice_config,
    _download_onlyoffice_file,
    _parse_onlyoffice_callback,
    _create_protocol_feedback,
    _format_deadline,
    _format_value,
    _funder_contact_label,
    _log_project_change,
    _normalise_import_record,
    _user_can_confirm_phase,
    _user_is_manager,
    _user_can_edit_project,
    protocol_delete_revision,
    action_list_delete_revision,
    _parse_plaintext_references,
    _parse_endnote_xml,
    project_synopsis_structure,
    _intervention_reference_numbering,
    _format_reference_number_ranges,
    _generate_synopsis_docx,
    _link_library_references_to_project,
    _reference_export_citation,
    _reference_summary_paragraph,
    _structured_summary_paragraph,
    _project_reference_summary_ids,
)

__all__ = [name for name in globals() if not name.startswith("__")]
