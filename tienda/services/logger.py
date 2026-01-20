from tienda.models import LogAuditoria

def registrarLog(usuario, accion):
    """Guarda un evento en la base de datos de auditoría"""
    try:
        LogAuditoria.objects.create(
            usuario=usuario if usuario.is_authenticated else None,
            accion=accion
        )
    except Exception as e:
        print(f"Error guardando log: {e}")
