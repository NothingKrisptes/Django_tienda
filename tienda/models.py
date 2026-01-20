from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

# --- MODELO SINGLETON PARA FINANZAS ---
class ConfiguracionFiscal(models.Model):
    """Solo permite un registro para controlar el IVA global"""
    valorIva = models.DecimalField(max_digits=4, decimal_places=2, default=0.15, help_text="Ejemplo: 0.15 para 15%")
    fechaActualizacion = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.pk and ConfiguracionFiscal.objects.exists():
            # Si ya existe, forzamos a usar el ID 1 (Singleton Pattern)
            self.pk = ConfiguracionFiscal.objects.first().pk
        super(ConfiguracionFiscal, self).save(*args, **kwargs)

    @classmethod
    def obtenerIvaActual(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj.valorIva

    def __str__(self):
        return f"IVA Actual: {self.valorIva * 100}%"

# --- INVENTARIO ---
class CategoriaMusical(models.Model):
    nombreCategoria = models.CharField(max_length=100)
    
    def __str__(self): return self.nombreCategoria

class ViniloMusical(models.Model):
    tituloDisco = models.CharField(max_length=200)
    artistaPrincipal = models.CharField(max_length=200)
    precioUnitario = models.DecimalField(max_digits=10, decimal_places=2)
    stockDisponible = models.IntegerField(default=0)
    imagenPortada = models.ImageField(upload_to='portadas/', blank=True, null=True)
    categoria = models.CharField(max_length=100, verbose_name="Género Musical")
    imagenUrl = models.URLField(max_length=500, blank=True, null=True, verbose_name="URL de Imagen (Opcional)")
    activo = models.BooleanField(default=True, verbose_name="¿Activo en Tienda?")
    
    # Lógica de devolución
    esNuevo = models.BooleanField(default=True)
    aceptaDevolucion = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.tituloDisco} - {self.artistaPrincipal}"
    
    def __str__(self): return self.tituloDisco

class CuponDescuento(models.Model):
    codigoCupon = models.CharField(max_length=20, unique=True)
    porcentajeDescuento = models.DecimalField(max_digits=4, decimal_places=2, help_text="0.10 para 10%")
    activo = models.BooleanField(default=True)
    
    def __str__(self): return self.codigoCupon

# --- VENTAS Y FACTURACIÓN ---
class OrdenVenta(models.Model):
    ESTADOS = [('PENDIENTE', 'Pendiente'), ('PAGADO', 'Pagado'), ('DEVUELTO', 'Devuelto')]
    
    cliente = models.ForeignKey(User, on_delete=models.CASCADE)
    fechaCompra = models.DateTimeField(auto_now_add=True)
    estadoOrden = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')
    
    subtotalSinImpuestos = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valorImpuestos = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valorDescuento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    totalFinal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    cuponAplicado = models.ForeignKey(CuponDescuento, null=True, blank=True, on_delete=models.SET_NULL)

    def puedeDevolver(self):
        """Regla: Devolución válida solo dentro de los 7 días"""
        limite = self.fechaCompra + timedelta(days=7)
        return timezone.now() <= limite

class DetalleOrden(models.Model):
    orden = models.ForeignKey(OrdenVenta, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey(ViniloMusical, on_delete=models.PROTECT)
    cantidad = models.IntegerField(default=1)
    precioUnitarioHistorico = models.DecimalField(max_digits=10, decimal_places=2)
    
    def subtotalLinea(self):
        return self.cantidad * self.precioUnitarioHistorico

class LogAuditoria(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    accion = models.CharField(max_length=255)
    fecha = models.DateTimeField(auto_now_add=True)
    
    def __str__(self): return f"{self.usuario} - {self.accion}"