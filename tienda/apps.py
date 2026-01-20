from django.apps import AppConfig


class TiendaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tienda'

    def ready(self):
        # Conectamos la señal para crear grupos automáticamente tras las migraciones
        from . import signals