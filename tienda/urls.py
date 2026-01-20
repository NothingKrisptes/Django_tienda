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
]
