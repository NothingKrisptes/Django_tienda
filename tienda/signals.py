# tienda/signals.py
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from .models import ViniloMusical, CuponDescuento, ConfiguracionFiscal

@receiver(post_migrate)
def inicializar_roles(sender, **kwargs):
    if sender.name == 'tienda':
        roles = ['Administrador', 'Finanzas', 'Bodega', 'Vendedor', 'Cliente']
        for rol in roles:
            Group.objects.get_or_create(name=rol)
            print(f"Verificando existencia del rol: {rol}")
