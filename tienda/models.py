from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

# --- MODELO PARA FINANZAS ---
class ConfiguracionFiscal(models.Model):
    valorIva = models.DecimalField(max_digits=4, decimal_places=2, default=0.15, help_text="Ejemplo: 0.15 para 15%")
    fechaActualizacion = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.pk and ConfiguracionFiscal.objects.exists():
            self.pk = ConfiguracionFiscal.objects.first().pk
        super(ConfiguracionFiscal, self).save(*args, **kwargs)

    @classmethod
    def obtenerIvaActual(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj.valorIva
        
    def __str__(self): return f"IVA: {self.valorIva}"

# --- LOGS DE AUDITORÍA ---
class LogAuditoria(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    accion = models.CharField(max_length=255)
    fecha = models.DateTimeField(auto_now_add=True)
    
    def __str__(self): return f"{self.usuario} - {self.accion}"

# --- INVENTARIO ---
class ViniloMusical(models.Model):
    tituloDisco = models.CharField(max_length=200)
    artistaPrincipal = models.CharField(max_length=200)
    precioUnitario = models.DecimalField(max_digits=10, decimal_places=2)
    stockDisponible = models.IntegerField(default=0)
    
    # Campo nuevo para ofertas individuales
    porcentajeDescuento = models.IntegerField(default=0, verbose_name="Descuento (%)", help_text="0 para precio normal")
    
    # Baja Lógica
    activo = models.BooleanField(default=True, verbose_name="¿Activo en Tienda?")
    
    # Imágenes (Híbrido)
    imagenPortada = models.ImageField(upload_to='portadas/', blank=True, null=True)
    imagenUrl = models.URLField(max_length=500, blank=True, null=True, verbose_name="URL de Imagen (Opcional)")
    
    # Categoría simple (sin relación)
    categoria = models.CharField(max_length=100, verbose_name="Género Musical")
    
    # Reglas de negocio
    esNuevo = models.BooleanField(default=True)
    aceptaDevolucion = models.BooleanField(default=True)
    
    def obtenerPrecioFinal(self):
        """Calcula el precio real si tiene descuento individual"""
        if self.porcentajeDescuento > 0:
            montoDesc = self.precioUnitario * (self.porcentajeDescuento / 100)
            return self.precioUnitario - montoDesc
        return self.precioUnitario
    
    def __str__(self): return self.tituloDisco

class CuponDescuento(models.Model):
    codigoCupon = models.CharField(max_length=20, unique=True)
    porcentajeDescuento = models.DecimalField(max_digits=4, decimal_places=2, help_text="0.10 para 10%")
    activo = models.BooleanField(default=True)
    usuarios_usados = models.ManyToManyField(User, blank=True, related_name='cupones_usados')
    limite_uso = models.IntegerField(default=1, help_text="Veces que un usuario puede usarlo")
    
    def __str__(self): return self.codigoCupon

# --- VENTAS ---
class OrdenVenta(models.Model):
    ESTADOS = [('PENDIENTE', 'Pendiente'), ('PAGADO', 'Pagado'), ('DEVUELTO', 'Devuelto')]
    
    cliente = models.ForeignKey(User, on_delete=models.CASCADE)
    fechaCompra = models.DateTimeField(auto_now_add=True)
    estadoOrden = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')
    
    subtotalSinImpuestos = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valorImpuestos = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valorDescuento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    totalFinal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    def puedeDevolver(self):
        limite = self.fechaCompra + timedelta(days=7)
        return timezone.now() <= limite

class DetalleOrden(models.Model):
    orden = models.ForeignKey(OrdenVenta, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey(ViniloMusical, on_delete=models.PROTECT)
    cantidad = models.IntegerField(default=1)
    precioUnitarioHistorico = models.DecimalField(max_digits=10, decimal_places=2)
