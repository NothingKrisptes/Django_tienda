from django import template

register = template.Library()

@register.filter
def porcentaje(value):
    """Convierte 0.15 a 15"""
    try:
        return int(float(value) * 100)
    except (ValueError, TypeError):
        return 0
