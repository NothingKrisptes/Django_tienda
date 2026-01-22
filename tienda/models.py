from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

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
    precioUnitario = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Precio CON IVA incluido (Ley Ecuador)"
    )
    stockDisponible = models.IntegerField(default=0)
    # Campo nuevo para ofertas individuales
    porcentajeDescuento = models.IntegerField(
        default=0, 
        verbose_name="Descuento (%)", 
        help_text="0 para precio normal"
    )
    # Baja Lógica
    activo = models.BooleanField(default=True, verbose_name="¿Activo en Tienda?")
    # Imágenes (Híbrido)
    imagenPortada = models.ImageField(upload_to='portadas/', blank=True, null=True)
    imagenUrl = models.URLField(
        max_length=500, 
        blank=True, 
        null=True, 
        verbose_name="URL de Imagen (Opcional)"
    )
    # Categoría simple (sin relación)
    categoria = models.CharField(max_length=100, verbose_name="Género Musical")
    # Reglas de negocio
    esNuevo = models.BooleanField(default=True)
    aceptaDevolucion = models.BooleanField(default=True)
    descripcion = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="Descripción del Álbum",
        help_text="Historia del disco, canciones destacadas, etc."
    )
    listaCanciones = models.TextField(
        blank=True,
        null=True,
        verbose_name="Lista de Canciones",
        help_text="Una por línea o separadas por comas"
    )
    
    def obtenerPrecioFinal(self):
        """
        Calcula el precio final con descuento individual aplicado.
        IMPORTANTE: El precioUnitario YA incluye IVA (Ley Ecuador).
        """
        if self.porcentajeDescuento > 0:
            # Convertimos el factor de descuento a Decimal
            factor = Decimal(self.porcentajeDescuento) / Decimal(100)
            montoDesc = self.precioUnitario * factor
            return self.precioUnitario - montoDesc
        return self.precioUnitario
    
    def obtenerAhorro(self):
        """
        Calcula cuánto dinero ahorra el cliente con el descuento individual.
        Útil para mostrar "Ahorras: $X.XX"
        """
        if self.porcentajeDescuento > 0:
            return self.precioUnitario - self.obtenerPrecioFinal()
        return Decimal('0')
    
    def obtenerPrecioSinIva(self):
        """
        Calcula el precio base sin IVA (solo para reportes internos y facturas).
        El precio al público SIEMPRE incluye IVA.
        """
        iva = ConfiguracionFiscal.obtenerIvaActual()
        factor_iva = Decimal('1') + iva
        precio_final = self.obtenerPrecioFinal()
        return precio_final / factor_iva
    
    def obtenerMontoIva(self):
        """
        Calcula cuánto IVA está incluido en el precio final.
        Útil para desgloses en facturas.
        """
        precio_final = self.obtenerPrecioFinal()
        precio_sin_iva = self.obtenerPrecioSinIva()
        return precio_final - precio_sin_iva
    
    def __str__(self):
        return self.tituloDisco
    
    class Meta:
        verbose_name = "Vinilo Musical"
        verbose_name_plural = "Vinilos Musicales"
        ordering = ['-id']

# --- CUPONES DE DESCUENTO ---

class CuponDescuento(models.Model):
    codigoCupon = models.CharField(max_length=20, unique=True)
    porcentajeDescuento = models.DecimalField(max_digits=4, decimal_places=2, help_text="0.10 para 10%")
    activo = models.BooleanField(default=True)
    usuarios_usados = models.ManyToManyField(User, blank=True, related_name='cupones_usados')
    limite_uso = models.IntegerField(default=1, help_text="Veces que un usuario puede usarlo")
    es_banner = models.BooleanField(default=False, verbose_name="Mostrar en Banner")
    
    def __str__(self): return self.codigoCupon

# --- VENTAS ---
class OrdenVenta(models.Model):
    TIPO_ENTREGA_CHOICES = [
        ('DOMICILIO', 'Entrega a Domicilio'),
        ('RETIRO', 'Retiro en Tienda'),
    ]
    ESTADOS = [('PENDIENTE', 'Pendiente'), ('PAGADO', 'Pagado'), ('DEVUELTO', 'Devuelto')]
    ESTADOS_ENVIO = [
        ('REVISION', '⏳ En Revisión'),
        ('PREPARANDO', '📦 Preparando Paquete'),
        ('EN_CAMINO', '🚚 En Camino'),
        ('ENTREGADO', '✅ Entregado'),
    ]
    cliente = models.ForeignKey(User, on_delete=models.CASCADE)
    fechaCompra = models.DateTimeField(auto_now_add=True)
    estadoOrden = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')
    subtotalSinImpuestos = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valorImpuestos = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valorDescuento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    totalFinal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estadoEntrega = models.CharField(max_length=20, choices=ESTADOS_ENVIO, default='REVISION')
    metodoPago = models.CharField(max_length=50, default='Tarjeta Crédito')
    infoPago = models.CharField(max_length=20, default='**** 0000', verbose_name="Terminación Tarjeta")
    motivoDevolucion = models.TextField(blank=True, null=True)
    montoReembolsado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cuponAplicado = models.ForeignKey(CuponDescuento, on_delete=models.SET_NULL, null=True, blank=True)
    tipoEntrega = models.CharField(max_length=20,choices=TIPO_ENTREGA_CHOICES,default='RETIRO')
    direccionEntrega = models.TextField( null=True,blank=True,help_text="Dirección de entrega a domicilio")
    montoDescuento = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ['-fechaCompra']
    
    def puedeDevolver(self):
        limite = self.fechaCompra + timedelta(days=7)
        return timezone.now() <= limite
    
class Cupon(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    porcentajeDescuento = models.DecimalField(max_digits=5, decimal_places=2, help_text="Porcentaje de 0 a 100")
    enBanner = models.BooleanField(default=False, verbose_name="¿Mostrar en Banner?")
    activo = models.BooleanField(default=True)
    
    def __str__(self):
        return self.codigo

    class Meta:
        verbose_name = "Cupón"
        verbose_name_plural = "Cupones"

class DetalleOrden(models.Model):
    orden = models.ForeignKey(OrdenVenta, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey(ViniloMusical, on_delete=models.PROTECT)
    cantidad = models.IntegerField(default=1)
    precioUnitarioHistorico = models.DecimalField(max_digits=10, decimal_places=2)

# --- SISTEMA DE DEVOLUCIONES CON APROBACIÓN ---
class SolicitudDevolucion(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE', '⏳ Pendiente de Revisión Bodega'),
        ('APROBADA_BODEGA', '📦 Aprobada por Bodega - Pendiente Finanzas'),
        ('RECHAZADA_BODEGA', '❌ Rechazada por Bodega'),
        ('APROBADA_FINANZAS', '✅ Aprobada - Reembolso Procesado'),
        ('RECHAZADA_FINANZAS', '❌ Rechazada por Finanzas'),
    ]
    
    orden = models.ForeignKey(OrdenVenta, on_delete=models.CASCADE, related_name='solicitudes_devolucion')
    cliente = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mis_solicitudes')
    motivoCliente = models.TextField(verbose_name="Motivo del Cliente")
    fechaSolicitud = models.DateTimeField(auto_now_add=True)
    estadoSolicitud = models.CharField(max_length=30, choices=ESTADO_CHOICES, default='PENDIENTE')
    
    # Aprobación BODEGA (Paso 1)
    revisadoPorBodega = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='devoluciones_bodega')
    fechaRevisionBodega = models.DateTimeField(null=True, blank=True)
    observacionesBodega = models.TextField(blank=True, verbose_name="Observaciones Bodega")
    estadoFisico = models.CharField(max_length=100, blank=True, verbose_name="Estado Físico del Producto")
    
    # Aprobación FINANZAS (Paso 2)
    revisadoPorFinanzas = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='devoluciones_finanzas')
    fechaRevisionFinanzas = models.DateTimeField(null=True, blank=True)
    observacionesFinanzas = models.TextField(blank=True, verbose_name="Observaciones Finanzas")
    montoReembolsado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    class Meta:
        ordering = ['-fechaSolicitud']
        verbose_name = "Solicitud de Devolución"
        verbose_name_plural = "Solicitudes de Devolución"
    
    def __str__(self):
        return f"Solicitud #{self.id} - Orden #{self.orden.id} ({self.get_estadoSolicitud_display()})"