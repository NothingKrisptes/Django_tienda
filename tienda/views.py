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
    if request.method == 'POST':
        orden = get_object_or_404(OrdenVenta, pk=orden_id)
        nuevo_estado = request.POST.get('nuevoEstado')  # Verifica que el nombre coincida con el form
        
        # VALIDACIÓN DEFENSIVA
        if not nuevo_estado or nuevo_estado not in ['REVISION', 'PREPARANDO', 'EN_CAMINO', 'ENTREGADO']:
            messages.error(request, "Estado inválido")
            return redirect('pedidos_bodega')
        
        # Asignar el nuevo estado
        orden.estadoEntrega = nuevo_estado
        
        try:
            orden.save()
            registrarLog(request.user, f"Cambió estado Orden #{orden.id} a {nuevo_estado}")
            messages.success(request, f"✅ Orden #{orden.id} actualizada a {nuevo_estado}")
        except Exception as e:
            messages.error(request, f"Error al actualizar: {str(e)}")
        
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
