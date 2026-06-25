"""Template filters for rendering safe inline synopsis formatting."""

from django import template
from django.utils.safestring import mark_safe

from ..utils import format_inline_markup_html

register = template.Library()


@register.filter
def render_inline_markup(value):
    return mark_safe(
        f'<span class="ce-inline-markup-rendered">{format_inline_markup_html(value or "")}</span>'
    )
