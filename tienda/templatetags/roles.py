from django import template

register = template.Library()

@register.filter(name='tiene_rol')
def tiene_rol(user, nombre_grupo):
    if user.is_superuser:
        return True
    return user.groups.filter(name=nombre_grupo).exists()
