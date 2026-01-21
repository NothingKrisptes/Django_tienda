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
    
    # Staff / Administrativas
    path('finanzas/', views.dashboardFinanzas, name='finanzas'),
    path('inventario/', views.reporteInventario, name='inventario'),
    path('inventario/nuevo/', views.agregarProducto, name='agregar_producto'),
    path('gestion/staff/nuevo/', views.vistaCrearStaff, name='crear_staff'), # Solo Admin
    
    # Auth
    path('login/', auth_views.LoginView.as_view(template_name='tienda/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # Logs
    path('gestion/logs/', views.vistaLogs, name='ver_logs'), # Solo Admin

    # Carrito
    path('inventario/editar/<int:producto_id>/', views.editarProducto, name='editar_producto'),
    path('inventario/eliminar/<int:producto_id>/', views.eliminarProducto, name='eliminar_producto'),
    path('inventario/reactivar/<int:producto_id>/', views.reactivarProducto, name='reactivar_producto'),
    path('carrito/actualizar/<int:producto_id>/<str:accion>/', views.actualizarCarrito, name='actualizar_carrito'),

    # Logística
    path('checkout/pago/', views.vistaPago, name='vista_pago'), # Pantalla tarjeta
    path('orden/factura/<int:orden_id>/', views.verFactura, name='ver_factura'), # PDF/HTML
    path('finanzas/destacar-cupon/<int:cupon_id>/', views.destacarCupon, name='destacar_cupon'),
    path('bodega/pedidos/', views.gestionPedidosBodega, name='pedidos_bodega'),
    path('bodega/pedidos/actualizar/<int:orden_id>/', views.actualizarEstadoEnvio, name='actualizar_envio'),

]
