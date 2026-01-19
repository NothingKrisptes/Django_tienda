from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import Group
from .models import ViniloMusical, OrdenVenta, DetalleOrden, CuponDescuento, ConfiguracionFiscal
from .services.gestorFinanciero import GestorFinanciero

# --- HELPERS DE ROLES ---
def esFinanzas(user): return user.groups.filter(name='Finanzas').exists() or user.is_superuser
def esBodeguero(user): return user.groups.filter(name='Bodega').exists() or user.is_superuser
def esVendedor(user): return user.groups.filter(name='Vendedor').exists() or user.is_superuser

# --- VISTAS PÚBLICAS (CLIENTE) ---

def vistaInicio(request):
    # Productos destacados o nuevos
    discosRecientes = ViniloMusical.objects.filter(stockDisponible__gt=0).order_by('-id')[:4]
    return render(request, 'tienda/inicio.html', {'discos': discosRecientes})

def vistaCatalogo(request):
    discos = ViniloMusical.objects.filter(stockDisponible__gt=0)
    return render(request, 'tienda/catalogo.html', {'discos': discos})
def agregarAlCarrito(request, producto_id):
    carrito = request.session.get('carrito', {})
    carrito[str(producto_id)] = carrito.get(str(producto_id), 0) + 1
    request.session['carrito'] = carrito
    messages.success(request, "Disco añadido al carrito")
    return redirect('catalogo')

def verCarrito(request):
    carrito = request.session.get('carrito', {})
    cuponCodigo = request.GET.get('cupon')
    cuponObj = None
    
    if cuponCodigo:
        try:
            cuponObj = CuponDescuento.objects.get(codigoCupon=cuponCodigo, activo=True)
        except CuponDescuento.DoesNotExist:
            messages.error(request, "Cupón inválido")

    datosCompra = GestorFinanciero.calcularTotalesCarrito(carrito, cuponObj)
    
    # Contexto para el template
    contexto = {
        'items': datosCompra['items'],
        'subtotal': datosCompra['subtotal'],
        'impuesto': datosCompra['impuesto'],
        'total': datosCompra['total'],
        'descuento': datosCompra['descuento'],
        'cupon': cuponCodigo
    }
    return render(request, 'tienda/carrito.html', contexto)

@login_required
def procesarCompra(request):
    if request.method == 'POST':
        carrito = request.session.get('carrito', {})
        if not carrito: return redirect('inicio')
        
        # Recuperar cupón de la sesión o post si existiera lógica
        datosCompra = GestorFinanciero.calcularTotalesCarrito(carrito)
        
        # 1. Crear Orden
        nuevaOrden = OrdenVenta.objects.create(
            cliente=request.user,
            subtotalSinImpuestos=datosCompra['subtotal'],
            valorDescuento=datosCompra['descuento'],
            valorImpuestos=datosCompra['impuesto'],
            totalFinal=datosCompra['total'],
            estadoOrden='PAGADO' # Simulación directa
        )
        
        # 2. Crear Detalles y Restar Stock
        for item in datosCompra['items']:
            producto = item['producto']
            cantidad = item['cantidad']
            
            DetalleOrden.objects.create(
                orden=nuevaOrden,
                producto=producto,
                cantidad=cantidad,
                precioUnitarioHistorico=producto.precioUnitario
            )
            
            # Actualizar Inventario
            producto.stockDisponible -= cantidad
            producto.save()
            
        # 3. Limpiar Carrito
        request.session['carrito'] = {}
        messages.success(request, f"Compra realizada con éxito. Orden #{nuevaOrden.id}")
        return redirect('perfil')
        
    return redirect('carrito')

@login_required
def vistaPerfil(request):
    ordenes = OrdenVenta.objects.filter(cliente=request.user).order_by('-fechaCompra')
    return render(request, 'tienda/perfil.html', {'ordenes': ordenes})

# --- VISTAS ADMINISTRATIVAS (ROLES) ---

@user_passes_test(esFinanzas)
def dashboardFinanzas(request):
    if request.method == "POST":
        nuevoIva = request.POST.get('nuevo_iva')
        config = ConfiguracionFiscal.objects.first() or ConfiguracionFiscal()
        config.valorIva = float(nuevoIva)
        config.save()
        messages.success(request, "IVA Actualizado")
    
    ingresosTotales = sum(o.totalFinal for o in OrdenVenta.objects.filter(estadoOrden='PAGADO'))
    configFiscal = ConfiguracionFiscal.obtenerIvaActual()
    
    return render(request, 'tienda/dashboard_finanzas.html', {
        'ingresos': ingresosTotales,
        'iva_actual': configFiscal
    })

@user_passes_test(esBodeguero)
def reporteInventario(request):
    inventario = ViniloMusical.objects.all()
    return render(request, 'tienda/reporte_inventario.html', {'inventario': inventario})
