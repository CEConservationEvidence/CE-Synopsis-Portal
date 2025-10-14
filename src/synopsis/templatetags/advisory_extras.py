from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    if hasattr(mapping, "get"):
        return mapping.get(key)
    return None
