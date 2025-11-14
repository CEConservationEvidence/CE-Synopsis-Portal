from django import template

register = template.Library()


@register.simple_tag
def get_outline_section_meta(page, section_id):
    if not section_id or not hasattr(page, "get_outline_section_meta"):
        return None
    return page.get_outline_section_meta(section_id)
