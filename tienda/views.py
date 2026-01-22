from urllib import request
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
from django.shortcuts import redirect, render
from tienda.models import Cupon
from datetime import datetime
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from datetime import datetime, timedelta
from django.db.models import Sum, Q
from django.http import FileResponse
import io

# --- HELPERS DE SEGURIDAD (ROLES) ---
def esFinanzas(user): return user.is_superuser or user.groups.filter(name='Finanzas').exists()
def esBodeguero(user): return user.is_superuser or user.groups.filter(name='Bodega').exists()

# --- VISTAS PÚBLICAS Y CLIENTES ---

def vistaInicio(request):
    """Muestra productos y banner de oferta"""
    discosRecientes = ViniloMusical.objects.filter(stockDisponible__gt=0, activo=True).order_by('-id')[:4]
    
    # Buscar cupón de banner
    cuponDestacado = CuponDescuento.objects.filter(es_banner=True, activo=True).first()
    
    # DEBUG TEMPORAL
    print(f"🔍 DEBUG: Cupón encontrado = {cuponDestacado}")
    if cuponDestacado:
        print(f"   - Código: {cuponDestacado.codigoCupon}")
        print(f"   - es_banner: {cuponDestacado.es_banner}")
        print(f"   - activo: {cuponDestacado.activo}")
    else:
        print("   ⚠️ No se encontró ningún cupón con es_banner=True")
    
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
    
    # Lógica de Validación de Cupón (igual que antes)
    if cuponCodigo:
        try:
            potential_cupon = CuponDescuento.objects.get(codigoCupon=cuponCodigo, activo=True)
            
            if request.user.is_authenticated:
                veces_usado = potential_cupon.usuarios_usados.filter(id=request.user.id).count()
                if veces_usado >= potential_cupon.limite_uso:
                    messages.error(request, f"Ya utilizaste el cupón '{cuponCodigo}' anteriormente.")
                    if 'cupon_aplicado' in request.session: del request.session['cupon_aplicado']
                else:
                    cuponObj = potential_cupon
                    request.session['cupon_aplicado'] = cuponCodigo
                    messages.success(request, f"Cupón '{cuponCodigo}' aplicado correctamente.")
            else:
                cuponObj = potential_cupon
                request.session['cupon_aplicado'] = cuponCodigo
                
        except CuponDescuento.DoesNotExist:
            messages.error(request, "El cupón ingresado no existe o venció.")
            if 'cupon_aplicado' in request.session: del request.session['cupon_aplicado']

    datosCompra = GestorFinanciero.calcularTotalesCarrito(carrito, cuponObj)
    
    return render(request, 'tienda/carrito.html', {
        'items': datosCompra['items'],
        'subtotal': datosCompra['subtotal'],        # CON IVA
        'impuesto': datosCompra['impuesto'],        # Desglose de IVA
        'base_imponible': datosCompra['base_imponible'],  # Sin IVA
        'total': datosCompra['total'],
        'descuento': datosCompra['descuento'],
        'cupon': cuponCodigo if cuponObj else None,
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
        # CAPTURAR DATOS DEL FORMULARIO
        numero_tarjeta = request.POST.get('card_number', '0000')[-4:]
        tipo_entrega = request.POST.get('tipo_entrega', 'RETIRO')
        direccion_entrega = request.POST.get('direccion_entrega', '')
        
        carrito = request.session.get('carrito', {})
        cupon_code = request.session.get('cupon_aplicado')
        cuponObj = None
        if cupon_code:
             try: cuponObj = CuponDescuento.objects.get(codigoCupon=cupon_code)
             except: pass

        datosCompra = GestorFinanciero.calcularTotalesCarrito(carrito, cuponObj)
        
        # CREAR ORDEN CON DIRECCIÓN
        nuevaOrden = OrdenVenta.objects.create(
            cliente=request.user,
            subtotalSinImpuestos=datosCompra['subtotal'],
            valorDescuento=datosCompra['descuento'],
            valorImpuestos=datosCompra['impuesto'],
            totalFinal=datosCompra['total'],
            estadoOrden='PAGADO',
            estadoEntrega='REVISION',
            cuponAplicado=cuponObj,
            infoPago=f"Visa terminada en {numero_tarjeta}",
            tipoEntrega=tipo_entrega,  # NUEVO
            direccionEntrega=direccion_entrega if tipo_entrega == 'DOMICILIO' else None  # NUEVO
        )
        
        # ... resto del código (crear detalles, restar stock, etc.) ...
        for item in datosCompra['items']:
             DetalleOrden.objects.create(
                 orden=nuevaOrden, producto=item['producto'],
                 cantidad=item['cantidad'], precioUnitarioHistorico=item['precio_aplicado']
             )
             item['producto'].stockDisponible -= item['cantidad']
             item['producto'].save()

        if cuponObj:
            cuponObj.usuarios_usados.add(request.user)
            del request.session['cupon_aplicado']
        request.session['carrito'] = {}
        
        messages.success(request, f"¡Pago Aprobado! Tu orden #{nuevaOrden.id} se está preparando.")
        return redirect('perfil')
    
    return redirect('carrito')

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
    Cliente SOLICITA devolución (no se procesa automáticamente).
    Staff debe aprobar/rechazar desde el dashboard.
    """
    from .models import SolicitudDevolucion
    
    orden = get_object_or_404(OrdenVenta, pk=orden_id, cliente=request.user)
    
    # Validación 1: Debe estar ENTREGADO
    if orden.estadoEntrega != 'ENTREGADO':
        messages.error(request, f"⚠️ No puedes solicitar devolución de un pedido que aún no ha sido entregado. Estado actual: {orden.get_estadoEntrega_display()}")
        return redirect('perfil')
    
    # Validación 2: Tiempo (7 días desde la ENTREGA, no desde la compra)
    dias_pasados = (timezone.now() - orden.fechaCompra).days
    if dias_pasados > 7:
        messages.error(request, f"⏰ El plazo de devolución expiró hace {dias_pasados - 7} días.")
        registrarLog(request.user, f"Intento devolución Orden #{orden.id}: Rechazado por tiempo")
        return redirect('perfil')
    
    # Validación 3: No está ya devuelta
    if orden.estadoOrden == 'DEVUELTO':
        messages.warning(request, "Esta orden ya fue devuelta.")
        return redirect('perfil')
    
    # Validación 4: No hay solicitud pendiente ya
    if SolicitudDevolucion.objects.filter(orden=orden, estadoSolicitud='PENDIENTE').exists():
        messages.warning(request, "Ya tienes una solicitud de devolución pendiente para esta orden.")
        return redirect('perfil')
    
    # Validación 5: ¿Hay productos devolvibles?
    tiene_devolvibles = any(d.producto.aceptaDevolucion for d in orden.detalles.all())
    if not tiene_devolvibles:
        messages.error(request, "Los productos de esta orden no aceptan devolución (Venta Final).")
        registrarLog(request.user, f"Intento devolución Orden #{orden.id}: Rechazado (Política Venta Final)")
        return redirect('perfil')
    
    # CREAR SOLICITUD (no procesar aún)
    if request.method == 'POST':
        motivo = request.POST.get('motivo', 'Sin especificar')
        
        SolicitudDevolucion.objects.create(
            orden=orden,
            cliente=request.user,
            motivoCliente=motivo
        )
        
        registrarLog(request.user, f"Solicitó devolución Orden #{orden.id}")
        messages.success(request, "✅ Solicitud enviada. El equipo de finanzas/bodega la revisará pronto.")
        return redirect('perfil')
    
    # Renderizar formulario de motivo
    return render(request, 'tienda/solicitar_devolucion.html', {'orden': orden})

# --- ZONA STAFF (ADMIN, BODEGA, FINANZAS) ---

@user_passes_test(esFinanzas)
def dashboardFinanzas(request):
    
    # DEBUG: Ver si detecta el POST
    print(f"🔍 Método: {request.method}")
    if request.method == "POST":
        print(f"🔍 POST data: {request.POST}")
        print(f"🔍 btn_iva presente: {'btn_iva' in request.POST}")
    
    if request.method == "POST":
        # CAMBIAR IVA
        if 'btn_iva' in request.POST:
            print("✅ Detectado cambio de IVA")
            nuevoIva = request.POST.get('nuevo_iva')
            print(f"📊 Nuevo IVA recibido: {nuevoIva}")
            
            try:
                nuevo_valor = Decimal(nuevoIva)
                
                # Validación
                if nuevo_valor <= 0 or nuevo_valor >= 1:
                    messages.error(request, "⚠️ El IVA debe estar entre 0.01 y 0.99")
                    return redirect('finanzas')
                
                config, created = ConfiguracionFiscal.objects.get_or_create(pk=1)
                iva_anterior = config.valorIva
                config.valorIva = nuevo_valor
                config.save()
                
                print(f"💾 IVA guardado: {config.valorIva}")
                
                registrarLog(request.user, f"Actualizó IVA: {float(iva_anterior)*100:.0f}% → {float(nuevo_valor)*100:.0f}%")
                messages.success(request, f"✅ IVA actualizado: {float(iva_anterior)*100:.0f}% → {float(nuevo_valor)*100:.0f}%")
                
            except Exception as e:
                print(f"❌ ERROR: {str(e)}")
                messages.error(request, f"Error: {str(e)}")
            
            return redirect('finanzas')

    # Resto del código (KPIs, cupones, etc.)
    ordenes_pagadas = OrdenVenta.objects.filter(estadoOrden='PAGADO')
    ingresos = sum(o.totalFinal for o in ordenes_pagadas) or Decimal('0')
    total_descuentos_dados = sum(o.valorDescuento for o in ordenes_pagadas) or Decimal('0')
    egresos_estimados = ingresos * Decimal('0.4')
    utilidad_neta = ingresos - egresos_estimados
    cupones = CuponDescuento.objects.all().order_by('-id')
    
    config = ConfiguracionFiscal.objects.first()
    iva_decimal = config.valorIva if config else Decimal('0.12')
    iva_porcentaje = float(iva_decimal) * 100
    
    return render(request, 'tienda/dashboard_finanzas.html', {
        'ingresos': ingresos,
        'descuentos_total': total_descuentos_dados,
        'egresos': egresos_estimados,
        'utilidad': utilidad_neta,
        'cupones': cupones,
        'iva_actual': iva_porcentaje,
        'form_cupon': CuponForm()
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
    """Simula pasarela de pago CON DIRECCIÓN"""
    carrito = request.session.get('carrito', {})
    if not carrito: return redirect('catalogo')
    
    # Recalculamos totales
    cupon_code = request.session.get('cupon_aplicado')
    cuponObj = None
    if cupon_code:
        try:
            cuponObj = CuponDescuento.objects.get(codigoCupon=cupon_code, activo=True)
        except: pass
        
    datos = GestorFinanciero.calcularTotalesCarrito(carrito, cuponObj)
    
    return render(request, 'tienda/pago.html', {
        'total': datos['total'],
        'user': request.user  # Para prellenar nombre
    })

# --- LOGÍSTICA (BODEGA) ---

@user_passes_test(esBodeguero)
def gestionPedidosBodega(request):
    """Panel para que el bodeguero mueva los paquetes"""
    # Traer TODOS los pedidos pagados que no estén entregados
    pedidos_pendientes = OrdenVenta.objects.filter(
        estadoOrden='PAGADO'
    ).exclude(
        estadoEntrega='ENTREGADO'
    ).order_by('fechaCompra')
    
    return render(request, 'tienda/admin_pedidos.html', {'ordenes': pedidos_pendientes})

@user_passes_test(esBodeguero)
def actualizarEstadoEnvio(request, orden_id):
    """Actualiza estado de envío CON VALIDACIÓN IRREVERSIBLE"""
    if request.method == 'POST':
        orden = get_object_or_404(OrdenVenta, pk=orden_id)
        nuevo_estado = request.POST.get('nuevoEstado')
        
        # ORDEN DE ESTADOS (no se puede retroceder)
        ESTADOS_ORDEN = ['REVISION', 'PREPARANDO', 'EN_CAMINO', 'ENTREGADO']
        
        # Validar que el nuevo estado existe
        if nuevo_estado not in ESTADOS_ORDEN:
            messages.error(request, "Estado inválido")
            return redirect('pedidos_bodega')
        
        # Validar que no retroceda
        try:
            indice_actual = ESTADOS_ORDEN.index(orden.estadoEntrega)
            indice_nuevo = ESTADOS_ORDEN.index(nuevo_estado)
            
            if indice_nuevo < indice_actual:
                messages.error(request, f"❌ No se puede retroceder de '{orden.get_estadoEntrega_display()}' a '{dict(orden.ESTADOS_ENVIO)[nuevo_estado]}'")
                return redirect('pedidos_bodega')
        except ValueError:
            messages.error(request, "Error al validar estados")
            return redirect('pedidos_bodega')
        
        # Actualizar
        orden.estadoEntrega = nuevo_estado
        orden.save()
        
        registrarLog(request.user, f"Cambió estado Orden #{orden.id} a {nuevo_estado}")
        messages.success(request, f"✅ Orden #{orden.id} actualizada a {dict(orden.ESTADOS_ENVIO)[nuevo_estado]}")
        
    return redirect('pedidos_bodega')

# --- GESTIÓN DE DEVOLUCIONES (BODEGA/FINANZAS) ---

@user_passes_test(esBodeguero)
def gestionDevolucionesBodega(request):
    """Panel exclusivo de bodeguero"""
    from .models import SolicitudDevolucion
    
    solicitudes_bodega = SolicitudDevolucion.objects.filter(estadoSolicitud='PENDIENTE')
    historial_bodega = SolicitudDevolucion.objects.filter(
        estadoSolicitud__in=['APROBADA_BODEGA', 'RECHAZADA_BODEGA', 'APROBADA_FINANZAS', 'RECHAZADA_FINANZAS']
    )[:20]
    
    return render(request, 'tienda/admin_devoluciones_bodega.html', {
        'solicitudes': solicitudes_bodega,
        'historial': historial_bodega
    })


@user_passes_test(esFinanzas)
def gestionDevolucionesFinanzas(request):
    """Panel exclusivo de finanzas"""
    from .models import SolicitudDevolucion
    
    solicitudes_finanzas = SolicitudDevolucion.objects.filter(estadoSolicitud='APROBADA_BODEGA')
    historial_finanzas = SolicitudDevolucion.objects.filter(
        estadoSolicitud__in=['APROBADA_FINANZAS', 'RECHAZADA_FINANZAS']
    )[:20]
    
    return render(request, 'tienda/admin_devoluciones_finanzas.html', {
        'solicitudes': solicitudes_finanzas,
        'historial': historial_finanzas
    })

@user_passes_test(esBodeguero)
def procesarDevolucionBodega(request, solicitud_id):
    """PASO 1: Bodeguero verifica estado físico"""
    from .models import SolicitudDevolucion
    
    if request.method != 'POST':
        return redirect('devoluciones_bodega')
    
    try:
        solicitud = SolicitudDevolucion.objects.get(pk=solicitud_id)
        print(f"🔍 DEBUG: Solicitud encontrada - Estado actual: {solicitud.estadoSolicitud}")
        
        if solicitud.estadoSolicitud != 'PENDIENTE':
            messages.error(request, f"Esta solicitud ya fue procesada (Estado: {solicitud.get_estadoSolicitud_display()})")
            return redirect('devoluciones_bodega')
            
    except SolicitudDevolucion.DoesNotExist:
        messages.error(request, f"No se encontró la solicitud #{solicitud_id}")
        return redirect('devoluciones_bodega')
    accion = request.POST.get('accion')
    observaciones = request.POST.get('observaciones', '')
    estado_fisico = request.POST.get('estado_fisico', '')
    
    if accion == 'aprobar':
        # RESTAURAR STOCK (Bodeguero confirma que recibió el producto)
        for detalle in solicitud.orden.detalles.all():
            if detalle.producto.aceptaDevolucion:
                detalle.producto.stockDisponible += detalle.cantidad
                detalle.producto.save()
        
        solicitud.estadoSolicitud = 'APROBADA_BODEGA'
        solicitud.revisadoPorBodega = request.user
        solicitud.fechaRevisionBodega = timezone.now()
        solicitud.observacionesBodega = observaciones
        solicitud.estadoFisico = estado_fisico
        solicitud.save()
        
        registrarLog(request.user, f"Bodega aprobó recepción física Solicitud #{solicitud.id}")
        messages.success(request, f"✅ Producto recibido. Ahora Finanzas procesará el reembolso.")
        
    elif accion == 'rechazar':
        solicitud.estadoSolicitud = 'RECHAZADA_BODEGA'
        solicitud.revisadoPorBodega = request.user
        solicitud.fechaRevisionBodega = timezone.now()
        solicitud.observacionesBodega = observaciones
        solicitud.save()
        
        registrarLog(request.user, f"Bodega rechazó devolución Solicitud #{solicitud.id}: {observaciones}")
        messages.warning(request, f"❌ Devolución rechazada. Motivo: {observaciones}")
    
    return redirect('devoluciones_bodega')


@user_passes_test(esFinanzas)
def procesarDevolucionFinanzas(request, solicitud_id):
    """PASO 2: Finanzas procesa el reembolso"""
    from .models import SolicitudDevolucion
    
    if request.method != 'POST':
        return redirect('devoluciones_finanzas')
    
    solicitud = get_object_or_404(SolicitudDevolucion, pk=solicitud_id, estadoSolicitud='APROBADA_BODEGA')
    accion = request.POST.get('accion')
    observaciones = request.POST.get('observaciones', '')
    
    if accion == 'aprobar':
        # CALCULAR REEMBOLSO
        monto_reembolso = 0
        for detalle in solicitud.orden.detalles.all():
            if detalle.producto.aceptaDevolucion:
                monto_reembolso += detalle.precioUnitarioHistorico * detalle.cantidad
        
        solicitud.estadoSolicitud = 'APROBADA_FINANZAS'
        solicitud.revisadoPorFinanzas = request.user
        solicitud.fechaRevisionFinanzas = timezone.now()
        solicitud.observacionesFinanzas = observaciones
        solicitud.montoReembolsado = monto_reembolso
        solicitud.save()
        
        # Actualizar orden
        solicitud.orden.estadoOrden = 'DEVUELTO'
        solicitud.orden.montoReembolsado = monto_reembolso
        solicitud.orden.save()
        
        registrarLog(request.user, f"Finanzas procesó reembolso ${monto_reembolso} - Solicitud #{solicitud.id}")
        messages.success(request, f"✅ Reembolso de ${monto_reembolso} procesado correctamente.")
        
    elif accion == 'rechazar':
        # DEVOLVER STOCK (ya que se rechaza el reembolso)
        for detalle in solicitud.orden.detalles.all():
            if detalle.producto.aceptaDevolucion:
                detalle.producto.stockDisponible -= detalle.cantidad
                detalle.producto.save()
        
        solicitud.estadoSolicitud = 'RECHAZADA_FINANZAS'
        solicitud.revisadoPorFinanzas = request.user
        solicitud.fechaRevisionFinanzas = timezone.now()
        solicitud.observacionesFinanzas = observaciones
        solicitud.save()
        
        registrarLog(request.user, f"Finanzas rechazó reembolso Solicitud #{solicitud.id}")
        messages.warning(request, f"❌ Reembolso rechazado. Stock restaurado.")
    
    return redirect('devoluciones_finanzas')

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

# --- FACTURACIÓN Y DEVOLUCIONES ---

@login_required
def verFactura(request, orden_id):
    """Genera una factura imprimible simple"""
    orden = get_object_or_404(OrdenVenta, pk=orden_id)
    if orden.cliente != request.user and not request.user.is_staff:
        return redirect('inicio')
    return render(request, 'tienda/factura_simple.html', {'orden': orden})

# CUPONES
@login_required
def crearCupon(request):
    """Crear nuevo cupón (solo staff)"""
    if not request.user.is_staff:
        return redirect('inicio')
    
    if request.method == 'POST':
        codigo = request.POST.get('codigo').upper()
        descuento = float(request.POST.get('descuento', 0)) / 100  # IMPORTANTE: Convertir a decimal (15% = 0.15)
        enBanner = request.POST.get('enBanner') == 'on'
        
        # Validar que no exista (USANDO EL MODELO CORRECTO)
        if CuponDescuento.objects.filter(codigoCupon=codigo).exists():
            messages.error(request, f"El código '{codigo}' ya existe.")
            return redirect('finanzas')  # Redirige al dashboard
        
        # CREAR CUPÓN EN EL MODELO CORRECTO
        cupon = CuponDescuento.objects.create(
            codigoCupon=codigo,
            porcentajeDescuento=descuento,
            es_banner=enBanner,  # OJO: El campo se llama 'es_banner' no 'enBanner'
            activo=True
        )
        
        registrarLog(request.user, f"Creó cupón: {codigo} ({descuento*100}%)")
        messages.success(request, f"✓ Cupón {codigo} creado correctamente.")
        return redirect('finanzas')  # Vuelve al dashboard para que veas el cupón
    
    return render(request, 'tienda/crear_cupon.html')

# Editar Cupón
@login_required
def editarCupon(request, cupon_id):
    """Editar cupón existente"""
    if not request.user.is_staff:
        return redirect('inicio')
    
    cupon = get_object_or_404(CuponDescuento, pk=cupon_id)
    
    if request.method == 'POST':
        cupon.codigoCupon = request.POST.get('codigo').upper()
        cupon.porcentajeDescuento = float(request.POST.get('descuento', 0)) / 100
        cupon.es_banner = request.POST.get('enBanner') == 'on'
        cupon.activo = request.POST.get('activo') == 'on'
        cupon.save()
        
        registrarLog(request.user, f"Editó cupón: {cupon.codigoCupon}")
        messages.success(request, "Cupón actualizado correctamente.")
        return redirect('finanzas')
    
    return render(request, 'tienda/editar_cupon.html', {'cupon': cupon})


@login_required
def eliminarCupon(request, cupon_id):
    """Eliminar cupón"""
    if not request.user.is_staff:
        return redirect('inicio')
    
    cupon = get_object_or_404(CuponDescuento, pk=cupon_id)
    codigo = cupon.codigoCupon
    cupon.delete()
    
    registrarLog(request.user, f"Eliminó cupón: {codigo}")
    messages.success(request, f"Cupón {codigo} eliminado.")
    return redirect('finanzas')

# --- PDFS
@login_required
def reporteFinanzasPDF(request):
    """Generar reporte de finanzas en PDF"""
    if not request.user.is_staff:
        return redirect('inicio')
    
    # Crear buffer
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    # Contenido
    elementos = []
    estilos = getSampleStyleSheet()
    
    # Título
    titulo = Paragraph("📊 REPORTE DE FINANZAS SDK VINILOS", estilos['Title'])
    elementos.append(titulo)
    elementos.append(Spacer(1, 0.3*inch))
    
    # Fechas
    fecha_hoy = datetime.now().strftime('%d/%m/%Y')
    
    elementos.append(Paragraph(f"<b>Fecha de Generación:</b> {fecha_hoy}", estilos['Normal']))
    elementos.append(Spacer(1, 0.2*inch))
    
    # CAMBIO AQUÍ: Usar PAGADO en lugar de ENTREGADO para incluir todas las ventas
    ordenes_completadas = OrdenVenta.objects.filter(estadoOrden='PAGADO')
    
    ingresos_brutos = ordenes_completadas.aggregate(Sum('totalFinal'))['totalFinal__sum'] or 0
    total_descuentos = ordenes_completadas.aggregate(Sum('valorDescuento'))['valorDescuento__sum'] or 0
    total_ordenes = ordenes_completadas.count()
    ticket_promedio = ingresos_brutos / total_ordenes if total_ordenes > 0 else 0
    
    utilidad_estimada = ingresos_brutos * Decimal('0.6') if ingresos_brutos else Decimal('0')

    datos_metricas = [
        ['Métrica', 'Valor'],
        ['Ingresos Brutos', f'${ingresos_brutos:.2f}'],
        ['Órdenes Completadas', f'{total_ordenes}'],
        ['Ticket Promedio', f'${ticket_promedio:.2f}'],
        ['Descuentos Aplicados', f'${total_descuentos:.2f}'],
        ['Utilidad Estimada (60%)', f'${utilidad_estimada:.2f}'],
    ]
    
    tabla_metricas = Table(datos_metricas, colWidths=[3*inch, 2*inch])
    tabla_metricas.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1976d2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    elementos.append(tabla_metricas)
    elementos.append(Spacer(1, 0.3*inch))
    
    # Detalle de órdenes
    elementos.append(Paragraph("<b>Últimas 15 Órdenes:</b>", estilos['Heading2']))
    elementos.append(Spacer(1, 0.2*inch))
    
    datos_ordenes = [
        ['Orden', 'Cliente', 'Fecha', 'Total', 'Descuento']
    ]
    
    for orden in ordenes_completadas.order_by('-fechaCompra')[:15]:
        cliente_nombre = orden.cliente.get_full_name() or orden.cliente.username
        datos_ordenes.append([
            f'#{orden.id}',
            cliente_nombre[:20],
            orden.fechaCompra.strftime('%d/%m/%Y'),
            f'${orden.totalFinal:.2f}',
            f'${orden.valorDescuento:.2f}'
        ])
    
    tabla_ordenes = Table(datos_ordenes, colWidths=[0.8*inch, 1.8*inch, 1*inch, 1*inch, 1*inch])
    tabla_ordenes.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1976d2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
    ]))
    
    elementos.append(tabla_ordenes)
    
    # Pie de página
    elementos.append(Spacer(1, 0.3*inch))
    elementos.append(Paragraph(f"<i>Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}</i>", estilos['Normal']))
    
    # Generar PDF
    doc.build(elementos)
    buffer.seek(0)
    
    return FileResponse(buffer, as_attachment=True, filename=f"Reporte_Finanzas_{datetime.now().strftime('%d%m%Y')}.pdf")

@login_required
def reporteBodegaPDF(request):
    """Generar reporte de inventario en PDF"""
    if not request.user.is_staff:
        return redirect('inicio')
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    elementos = []
    estilos = getSampleStyleSheet()
    
    # Título
    titulo = Paragraph("📦 REPORTE DE INVENTARIO - BODEGA", estilos['Title'])
    elementos.append(titulo)
    elementos.append(Spacer(1, 0.3*inch))
    
    elementos.append(Paragraph(f"<b>Fecha:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", estilos['Normal']))
    elementos.append(Spacer(1, 0.2*inch))
    
    # CAMBIO AQUÍ: Usar ViniloMusical en lugar de Producto
    productos = ViniloMusical.objects.filter(activo=True)
    
    datos_inventario = [
        ['ID', 'Producto', 'Categoría', 'Stock', 'Precio', 'Estado']
    ]
    
    for prod in productos:
        estado_stock = 'AGOTADO' if prod.stockDisponible == 0 else ('BAJO' if prod.stockDisponible < 5 else 'OK')
        datos_inventario.append([
            f'{prod.id}',
            prod.tituloDisco[:25],
            prod.categoria,
            f'{prod.stockDisponible}',
            f'${prod.precioUnitario:.2f}',
            estado_stock
        ])
    
    tabla_inventario = Table(datos_inventario, colWidths=[0.5*inch, 1.8*inch, 1.2*inch, 0.8*inch, 1*inch, 0.9*inch])
    tabla_inventario.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#264653')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
    ]))
    
    elementos.append(tabla_inventario)
    
    # Resumen
    elementos.append(Spacer(1, 0.3*inch))
    
    total_stock = productos.aggregate(Sum('stockDisponible'))['stockDisponible__sum'] or 0
    productos_bajos = productos.filter(stockDisponible__lt=5).count()
    productos_agotados = productos.filter(stockDisponible=0).count()
    
    elementos.append(Paragraph(f"<b>Resumen:</b>", estilos['Heading3']))
    elementos.append(Paragraph(f"• Total de Productos Activos: {productos.count()}", estilos['Normal']))
    elementos.append(Paragraph(f"• Stock Total en Bodega: {total_stock} unidades", estilos['Normal']))
    elementos.append(Paragraph(f"• Productos con Stock Bajo (&lt;5): {productos_bajos}", estilos['Normal']))
    elementos.append(Paragraph(f"• Productos Agotados: {productos_agotados}", estilos['Normal']))
    
    # Generar PDF
    doc.build(elementos)
    buffer.seek(0)
    
    return FileResponse(buffer, as_attachment=True, filename=f"Reporte_Bodega_{datetime.now().strftime('%d%m%Y')}.pdf")

# Vinilos
def detalleVinilo(request, disco_id):
    """Página de detalle de un vinilo específico"""
    disco = get_object_or_404(ViniloMusical, pk=disco_id, activo=True)
    return render(request, 'tienda/detalle_disco.html', {'disco': disco})
