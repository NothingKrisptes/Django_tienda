from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import Group
from django.contrib.auth import login
from .models import ViniloMusical, OrdenVenta, DetalleOrden, CuponDescuento, ConfiguracionFiscal, LogAuditoria
from .services.gestorFinanciero import GestorFinanciero
from .services.logger import registrarLog
from .forms import ViniloForm, RegistroClienteForm, CreacionStaffForm, CuponForm
from decimal import Decimal 
from django.utils import timezone

# --- HELPERS DE SEGURIDAD (ROLES) ---
def esFinanzas(user): return user.is_superuser or user.groups.filter(name='Finanzas').exists()
def esBodeguero(user): return user.is_superuser or user.groups.filter(name='Bodega').exists()

# --- VISTAS PÚBLICAS Y CLIENTES ---

def vistaInicio(request):
    """Muestra productos y banner de oferta"""
    # Solo productos activos y con stock
    discosRecientes = ViniloMusical.objects.filter(stockDisponible__gt=0, activo=True).order_by('-id')[:4]
    
    # Buscar el MEJOR cupón activo para mostrar en el banner
    cuponDestacado = CuponDescuento.objects.filter(activo=True).order_by('-porcentajeDescuento').first()
    
    return render(request, 'tienda/inicio.html', {
        'discos': discosRecientes, 
        'cupon_promo': cuponDestacado 
    })

def vistaCatalogo(request):
    """Tienda completa"""
    discos = ViniloMusical.objects.filter(stockDisponible__gt=0, activo=True)
    return render(request, 'tienda/catalogo.html', {'discos': discos})

def agregarAlCarrito(request, producto_id):
    """Añade producto a la sesión"""
    carrito = request.session.get('carrito', {})
    carrito[str(producto_id)] = carrito.get(str(producto_id), 0) + 1
    request.session['carrito'] = carrito
    messages.success(request, "Disco añadido a tu colección")
    return redirect('catalogo')

def actualizarCarrito(request, producto_id, accion):
    carrito = request.session.get('carrito', {})
    producto_id_str = str(producto_id)
    
    if producto_id_str in carrito:
        if accion == 'sumar':
            # Verificar stock antes de sumar
            producto = get_object_or_404(ViniloMusical, pk=producto_id)
            if carrito[producto_id_str] < producto.stockDisponible:
                carrito[producto_id_str] += 1
            else:
                messages.warning(request, "No hay más stock disponible.")
        elif accion == 'restar':
            if carrito[producto_id_str] > 1:
                carrito[producto_id_str] -= 1
            else:
                # Si llega a 0, lo borramos
                del carrito[producto_id_str]
        elif accion == 'eliminar':
            del carrito[producto_id_str]
            
    request.session['carrito'] = carrito
    return redirect('carrito')

def verCarrito(request):
    """Calcula totales y valida cupones"""
    carrito = request.session.get('carrito', {})
    cuponCodigo = request.GET.get('cupon')
    cuponObj = None
    
    # Lógica de Validación de Cupón
    if cuponCodigo:
        try:
            potential_cupon = CuponDescuento.objects.get(codigoCupon=cuponCodigo, activo=True)
            
            # 1. Validar si ya lo usó (Solo usuarios logueados)
            if request.user.is_authenticated:
                veces_usado = potential_cupon.usuarios_usados.filter(id=request.user.id).count()
                if veces_usado >= potential_cupon.limite_uso:
                    messages.error(request, f"Ya utilizaste el cupón '{cuponCodigo}' anteriormente.")
                    # Limpiamos cupón de sesión si existía
                    if 'cupon_aplicado' in request.session: del request.session['cupon_aplicado']
                else:
                    # Cupón válido
                    cuponObj = potential_cupon
                    request.session['cupon_aplicado'] = cuponCodigo # Guardar para el checkout
                    messages.success(request, f"Cupón '{cuponCodigo}' aplicado correctamente.")
            else:
                # Si no está logueado, permitimos ver el descuento pero pediremos login al pagar
                cuponObj = potential_cupon
                request.session['cupon_aplicado'] = cuponCodigo
                
        except CuponDescuento.DoesNotExist:
            messages.error(request, "El cupón ingresado no existe o venció.")
            if 'cupon_aplicado' in request.session: del request.session['cupon_aplicado']

    datosCompra = GestorFinanciero.calcularTotalesCarrito(carrito, cuponObj)
    
    return render(request, 'tienda/carrito.html', {
        'items': datosCompra['items'],
        'subtotal': datosCompra['subtotal'],
        'impuesto': datosCompra['impuesto'],
        'total': datosCompra['total'],
        'descuento': datosCompra['descuento'],
        'cupon': cuponCodigo if cuponObj else None, # Solo devolvemos el código si fue válido
        'iva_porcentaje': datosCompra['iva_porcentaje']
    })

# --- AUTENTICACIÓN Y REGISTRO ---

def vistaRegistro(request):
    if request.user.is_authenticated: return redirect('inicio')

    if request.method == 'POST':
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            grupoCliente, _ = Group.objects.get_or_create(name='Cliente')
            usuario.groups.add(grupoCliente)
            login(request, usuario)
            
            registrarLog(usuario, "Nuevo usuario registrado")
            
            # Regalo de bienvenida
            cupon = CuponDescuento.objects.filter(activo=True).first()
            codigo = cupon.codigoCupon if cupon else "SDK2026"
            messages.success(request, f"¡Bienvenido! Usa el código '{codigo}' para tu primera compra.")
            
            if request.session.get('carrito'): return redirect('carrito')
            return redirect('inicio')
    else:
        form = RegistroClienteForm()
    
    return render(request, 'tienda/registro.html', {'form': form})

# --- PROCESOS DE NEGOCIO (REQUIEREN LOGIN) ---

@login_required
def procesarCompra(request):
    if request.method == 'POST':
        # Simulamos datos de tarjeta del formulario
        numero_tarjeta = request.POST.get('card_number', '0000')[-4:] # Guardamos solo últimos 4
        
        carrito = request.session.get('carrito', {})
        # ... (lógica de recuperación de cupón igual que antes) ...
        cupon_code = request.session.get('cupon_aplicado')
        cuponObj = None
        if cupon_code:
             try: cuponObj = CuponDescuento.objects.get(codigoCupon=cupon_code)
             except: pass

        datosCompra = GestorFinanciero.calcularTotalesCarrito(carrito, cuponObj)
        
        # CREAMOS LA ORDEN CON LOS NUEVOS DATOS
        nuevaOrden = OrdenVenta.objects.create(
            cliente=request.user,
            subtotalSinImpuestos=datosCompra['subtotal'],
            valorDescuento=datosCompra['descuento'],
            valorImpuestos=datosCompra['impuesto'],
            totalFinal=datosCompra['total'],
            estadoOrden='PAGADO',
            estadoEntrega='REVISION', # Comienza en revisión por bodega
            cuponAplicado=cuponObj,
            infoPago=f"Visa terminada en {numero_tarjeta}"
        )
        
        # ... (Creación de DetalleOrden y Resta de Stock igual que antes) ...
        for item in datosCompra['items']:
             DetalleOrden.objects.create(
                 orden=nuevaOrden, producto=item['producto'],
                 cantidad=item['cantidad'], precioUnitarioHistorico=item['precio_aplicado']
             )
             # BAJA DE STOCK
             item['producto'].stockDisponible -= item['cantidad']
             item['producto'].save()

        # Limpieza
        if cuponObj:
            cuponObj.usuarios_usados.add(request.user)
            del request.session['cupon_aplicado']
        request.session['carrito'] = {}
        
        messages.success(request, f"¡Pago Aprobado! Tu orden #{nuevaOrden.id} se está preparando.")
        return redirect('perfil')

@login_required
def vistaPerfil(request):
    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('nombre')
        user.last_name = request.POST.get('apellido')
        user.email = request.POST.get('email')
        user.save()
        registrarLog(user, "Actualizó su perfil")
        messages.success(request, "Datos actualizados.")
        return redirect('perfil')

    ordenes = OrdenVenta.objects.filter(cliente=request.user).order_by('-fechaCompra')
    return render(request, 'tienda/perfil.html', {'ordenes': ordenes, 'user': request.user})

@login_required
def solicitarDevolucion(request, orden_id):
    """
    Lógica tipo Amazon:
    1. Cliente solicita.
    2. Validamos tiempo (7 días).
    3. Validamos si hay productos devolubles en la orden.
    """
    orden = get_object_or_404(OrdenVenta, pk=orden_id, cliente=request.user)
    
    # Validación 1: Tiempo
    dias_pasados = (timezone.now() - orden.fechaCompra).days
    if dias_pasados > 7:
        messages.error(request, f"El plazo de devolución expiró hace {dias_pasados - 7} días.")
        return redirect('perfil')

    if orden.estadoOrden == 'DEVUELTO':
        messages.warning(request, "Esta orden ya fue devuelta.")
        return redirect('perfil')

    # Validación 2: ¿Hay algo que devolver?
    productos_reembolsados = 0
    monto_reembolso = 0
    
    for detalle in orden.detalles.all():
        # AQUÍ ESTÁ LA CLAVE: Solo devolvemos si 'aceptaDevolucion' es True
        if detalle.producto.aceptaDevolucion:
            detalle.producto.stockDisponible += detalle.cantidad
            detalle.producto.save()
            productos_reembolsados += 1
            monto_reembolso += detalle.precioUnitarioHistorico * detalle.cantidad
    
    if productos_reembolsados == 0:
        messages.error(request, "Los productos de esta orden no aceptan devolución (Política de 'Venta Final').")
        return redirect('perfil')

    # Marcamos la orden
    orden.estadoOrden = 'DEVUELTO'
    orden.motivoDevolucion = "Solicitud cliente"
    orden.montoReembolsado = monto_reembolso # Guardamos cuánto se devolvió realmente
    orden.save()
    
    registrarLog(request.user, f"Devolución parcial/total Orden #{orden.id}")
    
    if productos_reembolsados < orden.detalles.count():
        messages.warning(request, f"Devolución procesada parcialmente. Se reembolsaron ${monto_reembolso} (Algunos items no admiten cambios).")
    else:
        messages.success(request, f"Devolución exitosa. Se han reembolsado ${monto_reembolso} a tu tarjeta.")
        
    return redirect('perfil')

# --- ZONA STAFF (ADMIN, BODEGA, FINANZAS) ---

@user_passes_test(esFinanzas)
def dashboardFinanzas(request):
    form_cupon = CuponForm()
    
    if request.method == "POST":
        if 'btn_iva' in request.POST:
            nuevoIva = request.POST.get('nuevo_iva')
            config = ConfiguracionFiscal.objects.first() or ConfiguracionFiscal()
            config.valorIva = float(nuevoIva)
            config.save()
            registrarLog(request.user, f"Actualizó IVA a {nuevoIva}")
            messages.success(request, "Configuración fiscal actualizada")
            
        elif 'btn_cupon' in request.POST:
            form_cupon = CuponForm(request.POST)
            if form_cupon.is_valid():
                c = form_cupon.save()
                registrarLog(request.user, f"Creó cupón {c.codigoCupon}")
                messages.success(request, "Cupón de descuento creado")
                return redirect('finanzas')

    ingresos = sum(o.totalFinal for o in OrdenVenta.objects.filter(estadoOrden='PAGADO'))
    config = ConfiguracionFiscal.obtenerIvaActual()
    cupones = CuponDescuento.objects.all().order_by('-id')
    
    return render(request, 'tienda/dashboard_finanzas.html', {
        'ingresos': ingresos, 
        'iva_actual': config, 
        'form_cupon': form_cupon, 
        'cupones': cupones
    })

@user_passes_test(esBodeguero)
def reporteInventario(request):
    inventario = ViniloMusical.objects.all()
    return render(request, 'tienda/reporte_inventario.html', {'inventario': inventario})

@user_passes_test(esBodeguero)
def agregarProducto(request):
    if request.method == 'POST':
        form = ViniloForm(request.POST, request.FILES)
        if form.is_valid():
            p = form.save()
            registrarLog(request.user, f"Agregó producto: {p.tituloDisco}")
            messages.success(request, "Producto añadido al catálogo.")
            return redirect('catalogo')
    else:
        form = ViniloForm()
    return render(request, 'tienda/agregar_producto.html', {'form': form})

@user_passes_test(esBodeguero)
def editarProducto(request, producto_id):
    producto = get_object_or_404(ViniloMusical, pk=producto_id)
    if request.method == 'POST':
        form = ViniloForm(request.POST, request.FILES, instance=producto)
        if form.is_valid():
            form.save()
            registrarLog(request.user, f"Editó producto: {producto.tituloDisco}")
            messages.success(request, "Cambios guardados.")
            return redirect('inventario')
    else:
        form = ViniloForm(instance=producto)
    return render(request, 'tienda/agregar_producto.html', {'form': form})

@user_passes_test(esBodeguero)
def eliminarProducto(request, producto_id):
    """Baja Lógica"""
    p = get_object_or_404(ViniloMusical, pk=producto_id)
    p.activo = False
    p.save()
    registrarLog(request.user, f"Dio de baja: {p.tituloDisco}")
    messages.warning(request, "Producto oculto de la tienda.")
    return redirect('inventario')

@user_passes_test(esBodeguero)
def reactivarProducto(request, producto_id):
    p = get_object_or_404(ViniloMusical, pk=producto_id)
    p.activo = True
    p.save()
    registrarLog(request.user, f"Reactivó: {p.tituloDisco}")
    messages.success(request, "Producto visible nuevamente.")
    return redirect('inventario')

@user_passes_test(lambda u: u.is_superuser)
def vistaCrearStaff(request):
    if request.method == 'POST':
        form = CreacionStaffForm(request.POST)
        if form.is_valid():
            u = form.save()
            g = form.cleaned_data['rolSeleccionado']
            u.groups.add(g)
            u.is_staff = True
            u.save()
            registrarLog(request.user, f"Creó empleado {u.username} ({g.name})")
            messages.success(request, f"Empleado creado con rol {g.name}")
            return redirect('inicio')
    else:
        form = CreacionStaffForm()
    return render(request, 'tienda/admin_crear_staff.html', {'form': form})

@user_passes_test(lambda u: u.is_superuser)
def vistaLogs(request):
    logs = LogAuditoria.objects.all().order_by('-fecha')[:100]
    return render(request, 'tienda/admin_logs.html', {'logs': logs})

# --- CHECKOUT Y PAGO ---
@login_required
def vistaPago(request):
    """Simula pasarela de pago"""
    carrito = request.session.get('carrito', {})
    if not carrito: return redirect('catalogo')
    
    # Recalculamos totales para mostrar en el resumen final
    cupon_code = request.session.get('cupon_aplicado')
    cuponObj = None
    if cupon_code:
        try:
            cuponObj = CuponDescuento.objects.get(codigoCupon=cupon_code, activo=True)
        except: pass
        
    datos = GestorFinanciero.calcularTotalesCarrito(carrito, cuponObj)
    
    return render(request, 'tienda/pago.html', {'total': datos['total']})

# --- LOGÍSTICA (BODEGA) ---

@user_passes_test(esBodeguero)
def gestionPedidosBodega(request):
    """Panel para que el bodeguero mueva los paquetes"""
    pedidos_pendientes = OrdenVenta.objects.filter(estadoOrden='PAGADO').exclude(estadoEntrega='ENTREGADO').order_by('fechaCompra')
    return render(request, 'tienda/admin_pedidos.html', {'pedidos': pedidos_pendientes})

@user_passes_test(esBodeguero)
def actualizarEstadoEnvio(request, orden_id):
    if request.method == 'POST':
        orden = get_object_or_404(OrdenVenta, pk=orden_id)
        nuevo_estado = request.POST.get('nuevo_estado')
        orden.estadoEntrega = nuevo_estado
        orden.save()
        
        # Log y Notificación
        icono = "🚚" if nuevo_estado == 'EN_CAMINO' else "📦"
        registrarLog(request.user, f"Cambió estado Orden #{orden.id} a {nuevo_estado}")
        messages.success(request, f"Orden actualizada correctamente.")
        
    return redirect('pedidos_bodega')

# --- FINANZAS MEJORADO ---

@user_passes_test(esFinanzas)
def destacarCupon(request, cupon_id):
    """Lógica de 'Radio Button': Solo uno activo a la vez"""
    CuponDescuento.objects.update(es_banner=False) # Apagar todos
    c = get_object_or_404(CuponDescuento, pk=cupon_id)
    c.es_banner = True # Prender el elegido
    c.save()
    messages.success(request, f"Cupón {c.codigoCupon} ahora es el principal.")
    return redirect('finanzas')

@user_passes_test(esFinanzas)
def dashboardFinanzas(request):
    # ... (Lógica de crear cupón y cambiar IVA igual que antes) ...

    # KPIs REALES
    ordenes_pagadas = OrdenVenta.objects.filter(estadoOrden='PAGADO')
    ingresos = sum(o.totalFinal for o in ordenes_pagadas)
    total_descuentos_dados = sum(o.valorDescuento for o in ordenes_pagadas)
    
    # Simulación de Egresos (ej: 40% de los ingresos son costos)
    egresos_estimados = ingresos * Decimal('0.4')
    utilidad_neta = ingresos - egresos_estimados

    cupones = CuponDescuento.objects.all().order_by('-id')
    
    # Importante: Buscamos el cupón activo para el banner
    # En vistaInicio usamos: CuponDescuento.objects.filter(es_banner=True, activo=True).first()

    return render(request, 'tienda/dashboard_finanzas.html', {
        'ingresos': ingresos,
        'descuentos_total': total_descuentos_dados,
        'egresos': egresos_estimados,
        'utilidad': utilidad_neta,
        'cupones': cupones,
        # ... forms ...
    })

# --- FACTURACIÓN Y DEVOLUCIONES ---

@login_required
def verFactura(request, orden_id):
    """Genera una factura imprimible simple"""
    orden = get_object_or_404(OrdenVenta, pk=orden_id)
    if orden.cliente != request.user and not request.user.is_staff:
        return redirect('inicio')
    return render(request, 'tienda/factura_simple.html', {'orden': orden})

@login_required
def solicitarDevolucion(request, orden_id):
    orden = get_object_or_404(OrdenVenta, pk=orden_id, cliente=request.user)
    
    # 1. Validación de Tiempo
    dias_pasados = (timezone.now() - orden.fechaCompra).days
    if dias_pasados > 7:
        registrarLog(request.user, f"Intento devolución Orden #{orden.id}: Rechazado por tiempo ({dias_pasados} días)")
        messages.error(request, f"El plazo expiró hace {dias_pasados - 7} días.")
        return redirect('perfil')

    if orden.estadoOrden == 'DEVUELTO':
        return redirect('perfil')

    # 2. Proceso de devolución
    productos_reembolsados = 0
    monto_reembolso = 0
    
    for detalle in orden.detalles.all():
        # Solo devolvemos si el producto tiene la casilla marcada
        if detalle.producto.aceptaDevolucion:
            detalle.producto.stockDisponible += detalle.cantidad
            detalle.producto.save()
            productos_reembolsados += 1
            monto_reembolso += detalle.precioUnitarioHistorico * detalle.cantidad
    
    # CASO A: NINGÚN PRODUCTO SE PUDO DEVOLVER
    if productos_reembolsados == 0:
        registrarLog(request.user, f"Intento devolución Orden #{orden.id}: Rechazado (Política 'Venta Final')")
        messages.error(request, "Este producto no acepta devoluciones (Venta Final).")
        return redirect('perfil')

    # CASO B: ÉXITO (PARCIAL O TOTAL)
    orden.estadoOrden = 'DEVUELTO'
    orden.motivoDevolucion = "Solicitud cliente"
    orden.montoReembolsado = monto_reembolso
    orden.save()
    
    # AQUI ESTÁ EL LOG DE ÉXITO QUE FALTABA
    registrarLog(request.user, f"Devolución Aceptada Orden #{orden.id}. Stock restaurado. Monto ${monto_reembolso}")
    
    messages.success(request, f"Devolución procesada. Se han reembolsado ${monto_reembolso}.")
    return redirect('perfil')