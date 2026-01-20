# tienda/views.py (COMPLETO Y CON LOGS DE AUDITORÍA)

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import Group
from django.contrib.auth import login
from .models import ViniloMusical, OrdenVenta, DetalleOrden, CuponDescuento, ConfiguracionFiscal, LogAuditoria
from .services.gestorFinanciero import GestorFinanciero
from .services.logger import registrarLog # <--- IMPORTANTE: El servicio de logs
from .forms import ViniloForm, RegistroClienteForm, CreacionStaffForm, CuponForm

# --- HELPERS DE SEGURIDAD (ROLES) ---
def esFinanzas(user): return user.is_superuser or user.groups.filter(name='Finanzas').exists()
def esBodeguero(user): return user.is_superuser or user.groups.filter(name='Bodega').exists()
def esVendedor(user): return user.is_superuser or user.groups.filter(name='Vendedor').exists()

# --- VISTAS PÚBLICAS Y CLIENTES ---

def vistaInicio(request):
    discosRecientes = ViniloMusical.objects.filter(stockDisponible__gt=0, activo=True).order_by('-id')[:4]
    return render(request, 'tienda/inicio.html', {'discos': discosRecientes})

def vistaCatalogo(request):
    discos = ViniloMusical.objects.filter(stockDisponible__gt=0, activo=True)
    return render(request, 'tienda/catalogo.html', {'discos': discos})

def agregarAlCarrito(request, producto_id):
    carrito = request.session.get('carrito', {})
    carrito[str(producto_id)] = carrito.get(str(producto_id), 0) + 1
    request.session['carrito'] = carrito
    messages.success(request, "Disco añadido a tu colección")
    return redirect('catalogo')

def verCarrito(request):
    carrito = request.session.get('carrito', {})
    cuponCodigo = request.GET.get('cupon')
    cuponObj = None
    
    if cuponCodigo:
        try:
            cuponObj = CuponDescuento.objects.get(codigoCupon=cuponCodigo, activo=True)
            # Log de intento de cupón
            if request.user.is_authenticated:
                registrarLog(request.user, f"Aplicó cupón: {cuponCodigo}")
        except CuponDescuento.DoesNotExist:
            messages.error(request, "El cupón ingresado no existe o venció.")

    datosCompra = GestorFinanciero.calcularTotalesCarrito(carrito, cuponObj)
    
    contexto = {
        'items': datosCompra['items'],
        'subtotal': datosCompra['subtotal'],
        'impuesto': datosCompra['impuesto'],
        'total': datosCompra['total'],
        'descuento': datosCompra['descuento'],
        'cupon': cuponCodigo
    }
    return render(request, 'tienda/carrito.html', contexto)

# --- AUTENTICACIÓN Y REGISTRO ---

def vistaRegistro(request):
    """Registro público: asigna rol Cliente automáticamente y mantiene el carrito"""
    if request.user.is_authenticated:
        return redirect('inicio')

    if request.method == 'POST':
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            
            # Asignar grupo Cliente
            grupoCliente, _ = Group.objects.get_or_create(name='Cliente')
            usuario.groups.add(grupoCliente)
            
            # Login automático + Persistencia de sesión
            login(request, usuario)
            
            # [LOG] Registro de nuevo usuario
            registrarLog(usuario, "Nuevo usuario registrado en la plataforma")
            
            messages.success(request, f"¡Bienvenido {usuario.first_name}! Tu cuenta ha sido creada.")
            
            # Si hay carrito pendiente, ir directo a pagar
            if request.session.get('carrito'):
                return redirect('carrito')
            return redirect('inicio')
    else:
        form = RegistroClienteForm()
    
    return render(request, 'tienda/registro.html', {'form': form})

# --- PROCESOS DE NEGOCIO (REQUIEREN LOGIN) ---

@login_required
def procesarCompra(request):
    if request.method == 'POST':
        carrito = request.session.get('carrito', {})
        if not carrito: return redirect('inicio')
        
        datosCompra = GestorFinanciero.calcularTotalesCarrito(carrito)
        
        # Crear Orden
        nuevaOrden = OrdenVenta.objects.create(
            cliente=request.user,
            subtotalSinImpuestos=datosCompra['subtotal'],
            valorDescuento=datosCompra['descuento'],
            valorImpuestos=datosCompra['impuesto'],
            totalFinal=datosCompra['total'],
            estadoOrden='PAGADO'
        )
        
        # Detalles
        for item in datosCompra['items']:
            producto = item['producto']
            cantidad = item['cantidad']
            
            DetalleOrden.objects.create(
                orden=nuevaOrden,
                producto=producto,
                cantidad=cantidad,
                precioUnitarioHistorico=producto.precioUnitario
            )
            
            producto.stockDisponible -= cantidad
            producto.save()
            
        request.session['carrito'] = {} # Vaciar carrito
        
        # [LOG] Compra realizada
        registrarLog(request.user, f"Realizó compra Orden #{nuevaOrden.id} por ${nuevaOrden.totalFinal}")
        
        messages.success(request, f"Compra realizada con éxito. Orden #{nuevaOrden.id}")
        return redirect('perfil')
        
    return redirect('carrito')

@login_required
def vistaPerfil(request):
    # Si envía formulario para editar datos
    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('nombre')
        user.last_name = request.POST.get('apellido')
        user.email = request.POST.get('email')
        user.save()
        
        # [LOG] Actualización de perfil
        registrarLog(user, "Actualizó sus datos de perfil")
        
        messages.success(request, "Datos actualizados correctamente.")
        return redirect('perfil')

    ordenes = OrdenVenta.objects.filter(cliente=request.user).order_by('-fechaCompra')
    return render(request, 'tienda/perfil.html', {'ordenes': ordenes, 'user': request.user})

# --- ZONA STAFF (ADMIN, BODEGA, FINANZAS) ---

@user_passes_test(esFinanzas)
def dashboardFinanzas(request):
    # Inicializamos forms
    form_cupon = CuponForm()
    
    if request.method == "POST":
        # Opción A: Cambiar IVA
        if 'btn_iva' in request.POST:
            nuevoIva = request.POST.get('nuevo_iva')
            config = ConfiguracionFiscal.objects.first() or ConfiguracionFiscal()
            ivaAnterior = config.valorIva
            config.valorIva = float(nuevoIva)
            config.save()
            registrarLog(request.user, f"Cambió Tasa IVA de {ivaAnterior} a {nuevoIva}")
            messages.success(request, "Tasa de IVA actualizada")

        # Opción B: Crear Cupón
        elif 'btn_cupon' in request.POST:
            form_cupon = CuponForm(request.POST)
            if form_cupon.is_valid():
                cupon = form_cupon.save()
                registrarLog(request.user, f"Creó cupón: {cupon.codigoCupon} ({cupon.porcentajeDescuento})")
                messages.success(request, f"Cupón {cupon.codigoCupon} creado exitosamente")
                return redirect('finanzas')

    ingresosTotales = sum(o.totalFinal for o in OrdenVenta.objects.filter(estadoOrden='PAGADO'))
    configFiscal = ConfiguracionFiscal.obtenerIvaActual()
    # Listamos cupones existentes
    cupones = CuponDescuento.objects.all().order_by('-id')
    
    return render(request, 'tienda/dashboard_finanzas.html', {
        'ingresos': ingresosTotales,
        'iva_actual': configFiscal,
        'form_cupon': form_cupon,
        'cupones': cupones
    })

@user_passes_test(esBodeguero)
def reporteInventario(request):
    # [LOG] Acceso a reporte (Opcional, puede generar ruido si se usa mucho)
    # registrarLog(request.user, "Consultó reporte de inventario") 
    inventario = ViniloMusical.objects.all()
    return render(request, 'tienda/reporte_inventario.html', {'inventario': inventario})

@user_passes_test(esBodeguero)
def agregarProducto(request):
    """Permite subir productos desde el frontend"""
    if request.method == 'POST':
        form = ViniloForm(request.POST, request.FILES)
        if form.is_valid():
            producto = form.save()
            
            # [LOG] Gestión de Inventario
            registrarLog(request.user, f"Agregó nuevo producto: {producto.tituloDisco} ({producto.stockDisponible} u.)")
            
            messages.success(request, "Nuevo vinilo añadido al catálogo.")
            return redirect('catalogo')
    else:
        form = ViniloForm()
    return render(request, 'tienda/agregar_producto.html', {'form': form})

@user_passes_test(lambda u: u.is_superuser)
def vistaCrearStaff(request):
    """Solo SuperAdmin crea empleados y asigna roles"""
    if request.method == 'POST':
        form = CreacionStaffForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            grupo = form.cleaned_data['rolSeleccionado']
            usuario.groups.add(grupo)
            usuario.is_staff = True 
            usuario.save()
            
            # [LOG] Gestión de RRHH
            registrarLog(request.user, f"Creó empleado {usuario.username} con rol {grupo.name}")
            
            messages.success(request, f"Empleado {usuario.username} creado con rol {grupo.name}")
            return redirect('inicio') 
    else:
        form = CreacionStaffForm()
    return render(request, 'tienda/admin_crear_staff.html', {'form': form})

@user_passes_test(lambda u: u.is_superuser)
def vistaLogs(request):
    logs = LogAuditoria.objects.all().order_by('-fecha')[:50] 
    return render(request, 'tienda/admin_logs.html', {'logs': logs})

@user_passes_test(esBodeguero)
def editarProducto(request, producto_id):
    producto = get_object_or_404(ViniloMusical, pk=producto_id)
    if request.method == 'POST':
        form = ViniloForm(request.POST, request.FILES, instance=producto)
        if form.is_valid():
            form.save()
            registrarLog(request.user, f"Editó producto: {producto.tituloDisco}")
            messages.success(request, "Producto actualizado correctamente.")
            return redirect('inventario')
    else:
        form = ViniloForm(instance=producto)
    return render(request, 'tienda/agregar_producto.html', {'form': form}) # Reutilizamos el template

@user_passes_test(esBodeguero)
def eliminarProducto(request, producto_id):
    """Baja Lógica: No borra, solo oculta."""
    producto = get_object_or_404(ViniloMusical, pk=producto_id)
    
    # Cambiamos el estado a Inactivo
    producto.activo = False
    producto.save()
    
    registrarLog(request.user, f"Dio de baja el producto: {producto.tituloDisco}")
    messages.warning(request, "Producto dado de baja (Oculto en tienda).")
    return redirect('inventario')

@user_passes_test(esBodeguero)
def reactivarProducto(request, producto_id):
    """Restaura un producto dado de baja."""
    producto = get_object_or_404(ViniloMusical, pk=producto_id)
    
    producto.activo = True
    producto.save()
    
    registrarLog(request.user, f"Reactivó el producto: {producto.tituloDisco}")
    messages.success(request, "Producto reactivado y visible en tienda.")
    return redirect('inventario')

@login_required
def solicitarDevolucion(request, orden_id):
    orden = get_object_or_404(OrdenVenta, pk=orden_id, cliente=request.user)
    
    if not orden.puedeDevolver():
        messages.error(request, "El periodo de devolución ha expirado.")
        return redirect('perfil')

    if orden.estadoOrden == 'DEVUELTO':
        messages.warning(request, "Esta orden ya fue devuelta.")
        return redirect('perfil')

    # Lógica de devolución de stock
    for detalle in orden.detalles.all():
        if detalle.producto.aceptaDevolucion:
            detalle.producto.stockDisponible += detalle.cantidad
            detalle.producto.save()
    
    orden.estadoOrden = 'DEVUELTO'
    orden.save()
    
    registrarLog(request.user, f"Devolución procesada Orden #{orden.id}")
    messages.success(request, "Devolución aceptada. El stock ha sido restaurado.")
    return redirect('perfil')

@user_passes_test(esFinanzas)
def crearCupon(request):
    if request.method == 'POST':
        form = CuponForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Cupón creado exitosamente")
            return redirect('finanzas')
    return redirect('finanzas') # O renderizar un template si prefieres
