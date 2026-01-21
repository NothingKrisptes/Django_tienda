from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import Group
from django.contrib.auth import login
from .models import ViniloMusical, OrdenVenta, DetalleOrden, CuponDescuento, ConfiguracionFiscal, LogAuditoria
from .services.gestorFinanciero import GestorFinanciero
from .services.logger import registrarLog
from .forms import ViniloForm, RegistroClienteForm, CreacionStaffForm, CuponForm

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
        carrito = request.session.get('carrito', {})
        if not carrito: return redirect('inicio')
        
        # Recuperar cupón validado de la sesión
        cupon_code = request.session.get('cupon_aplicado')
        cuponObj = None
        if cupon_code:
            try:
                cuponObj = CuponDescuento.objects.get(codigoCupon=cupon_code, activo=True)
                # Re-validación final de seguridad
                if cuponObj.usuarios_usados.filter(id=request.user.id).count() >= cuponObj.limite_uso:
                    cuponObj = None # Anular si intenta trampa
            except CuponDescuento.DoesNotExist:
                pass

        datosCompra = GestorFinanciero.calcularTotalesCarrito(carrito, cuponObj)
        
        # Crear Orden
        nuevaOrden = OrdenVenta.objects.create(
            cliente=request.user,
            subtotalSinImpuestos=datosCompra['subtotal'],
            valorDescuento=datosCompra['descuento'],
            valorImpuestos=datosCompra['impuesto'],
            totalFinal=datosCompra['total'],
            estadoOrden='PAGADO',
            cuponAplicado=cuponObj
        )
        
        # Guardar Detalles y Restar Stock
        for item in datosCompra['items']:
            producto = item['producto']
            cantidad = item['cantidad']
            
            DetalleOrden.objects.create(
                orden=nuevaOrden,
                producto=producto,
                cantidad=cantidad,
                precioUnitarioHistorico=item['precio_aplicado']
            )
            
            producto.stockDisponible -= cantidad
            producto.save()
            
        # Registrar uso del cupón
        if cuponObj:
            cuponObj.usuarios_usados.add(request.user)
            del request.session['cupon_aplicado']
            
        request.session['carrito'] = {} # Vaciar carrito
        
        registrarLog(request.user, f"Compra Orden #{nuevaOrden.id} por ${nuevaOrden.totalFinal}")
        messages.success(request, f"¡Compra exitosa! Orden #{nuevaOrden.id} generada.")
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
    orden = get_object_or_404(OrdenVenta, pk=orden_id, cliente=request.user)
    
    if not orden.puedeDevolver():
        messages.error(request, "Plazo de devolución expirado.")
        return redirect('perfil')
        
    if orden.estadoOrden == 'DEVUELTO':
        return redirect('perfil')

    # Restaurar Stock
    for detalle in orden.detalles.all():
        if detalle.producto.aceptaDevolucion:
            detalle.producto.stockDisponible += detalle.cantidad
            detalle.producto.save()
    
    orden.estadoOrden = 'DEVUELTO'
    orden.save()
    
    registrarLog(request.user, f"Solicitó devolución Orden #{orden.id}")
    messages.success(request, "Devolución aceptada. Se ha generado la nota de crédito.")
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
