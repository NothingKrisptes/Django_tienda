from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Públicas
    path('', views.vistaInicio, name='inicio'),
    path('tienda/', views.vistaCatalogo, name='catalogo'),
    path('agregar/<int:producto_id>/', views.agregarAlCarrito, name='agregar_carrito'),
    path('carrito/', views.verCarrito, name='carrito'),
    
    # Usuario (Cliente)
    path('registro/', views.vistaRegistro, name='registro'),
    path('perfil/', views.vistaPerfil, name='perfil'),
    path('procesar/', views.procesarCompra, name='procesar_compra'),
    path('orden/devolver/<int:orden_id>/', views.solicitarDevolucion, name='devolver_orden'),
    
    # Auth
    path('login/', auth_views.LoginView.as_view(template_name='tienda/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # Carrito
    path('carrito/actualizar/<int:producto_id>/<str:accion>/', views.actualizarCarrito, name='actualizar_carrito'),

    # Logística
    path('checkout/pago/', views.vistaPago, name='vista_pago'),
    path('orden/factura/<int:orden_id>/', views.verFactura, name='ver_factura'),
    
    # DEVOLUCIONES - DEBEN IR ANTES DE LAS RUTAS DE BODEGA GENÉRICAS
    path('bodega/devoluciones/', views.gestionDevolucionesBodega, name='devoluciones_bodega'),
    path('bodega/devoluciones/procesar/<int:solicitud_id>/', views.procesarDevolucionBodega, name='procesar_devolucion_bodega'),
    path('finanzas/devoluciones/', views.gestionDevolucionesFinanzas, name='devoluciones_finanzas'),
    path('finanzas/devoluciones/procesar/<int:solicitud_id>/', views.procesarDevolucionFinanzas, name='procesar_devolucion_finanzas'),
    
    # Bodega (DESPUÉS de devoluciones)
    path('bodega/pedidos/', views.gestionPedidosBodega, name='pedidos_bodega'),
    path('bodega/pedidos/actualizar/<int:orden_id>/', views.actualizarEstadoEnvio, name='actualizar_envio'),
    
    # Staff / Administrativas
    path('finanzas/', views.dashboardFinanzas, name='finanzas'),
    path('finanzas/destacar-cupon/<int:cupon_id>/', views.destacarCupon, name='destacar_cupon'),
    path('inventario/', views.reporteInventario, name='inventario'),
    path('inventario/nuevo/', views.agregarProducto, name='agregar_producto'),
    path('inventario/editar/<int:producto_id>/', views.editarProducto, name='editar_producto'),
    path('inventario/eliminar/<int:producto_id>/', views.eliminarProducto, name='eliminar_producto'),
    path('inventario/reactivar/<int:producto_id>/', views.reactivarProducto, name='reactivar_producto'),
    path('gestion/staff/nuevo/', views.vistaCrearStaff, name='crear_staff'),
    path('gestion/logs/', views.vistaLogs, name='ver_logs'),

    # Cupones
    path('staff/cupones/crear/', views.crearCupon, name='crear_cupon'),
    path('staff/cupones/editar/<int:cupon_id>/', views.editarCupon, name='editar_cupon'),
    path('staff/cupones/eliminar/<int:cupon_id>/', views.eliminarCupon, name='eliminar_cupon'),

    # PDFs
    path('staff/reportes/finanzas/pdf/', views.reporteFinanzasPDF, name='reporte_finanzas_pdf'),
    path('staff/reportes/bodega/pdf/', views.reporteBodegaPDF, name='reporte_bodega_pdf'),

    # Vinilos
    path('disco/<int:disco_id>/', views.detalleVinilo, name='detalle_disco'),
]
