from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.vistaInicio, name='inicio'),
    path('tienda/', views.vistaCatalogo, name='catalogo'),
    path('agregar/<int:producto_id>/', views.agregarAlCarrito, name='agregar_carrito'),
    path('carrito/', views.verCarrito, name='carrito'),
    path('procesar/', views.procesarCompra, name='procesar_compra'),
    path('perfil/', views.vistaPerfil, name='perfil'),
    
    # Administrativas
    path('finanzas/', views.dashboardFinanzas, name='finanzas'),
    path('inventario/', views.reporteInventario, name='inventario'),
    
    # Auth
    path('login/', auth_views.LoginView.as_view(template_name='tienda/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
