from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group
from .models import ViniloMusical, CuponDescuento

# --- FORMULARIO DE PRODUCTOS (Para Bodega/Admin) ---
class ViniloForm(forms.ModelForm):
    class Meta:
        model = ViniloMusical
        fields = ['tituloDisco', 
                  'artistaPrincipal', 
                  'precioUnitario', 
                  'stockDisponible', 
                  'categoria',
                  'porcentajeDescuento',
                  'imagenPortada', 
                  'imagenUrl', 
                  'esNuevo', 
                  'aceptaDevolucion']
        
        # AQUÍ ESTÁ LA MAGIA PARA SEPARAR PALABRAS
        labels = {
            'tituloDisco': 'Título del Álbum',
            'artistaPrincipal': 'Artista / Banda',
            'precioUnitario': 'Precio de Venta ($)',
            'stockDisponible': 'Stock Disponible',
            'categoria': 'Género Musical (Elegir o Escribir)',
            'porcentajeDescuento': 'Descuento Individual (%)',
            'imagenPortada': 'Subir Portada (Archivo)',
            'imagenUrl': 'O pegar URL de imagen',
            'esNuevo': '¿Es nuevo?',
            'aceptaDevolucion': '¿Acepta Devolución?'
        }

        widgets = {
            'tituloDisco': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Abbey Road'}),
            'artistaPrincipal': forms.TextInput(attrs={'class': 'form-control'}),
            'precioUnitario': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stockDisponible': forms.NumberInput(attrs={'class': 'form-control'}),
            'imagenUrl': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            # Quitamos estilos extra a los checkbox para manejarlos en el template
            'esNuevo': forms.CheckboxInput(attrs={'class': 'checkbox-custom'}),
            'aceptaDevolucion': forms.CheckboxInput(attrs={'class': 'checkbox-custom'}),
            'categoria': forms.TextInput(attrs={
                'class': 'form-control', 
                'list': 'lista-generos', # Esto conecta con el datalist del HTML
                'placeholder': 'Escribe o selecciona...'
            }),
        }

# --- FORMULARIO DE REGISTRO PÚBLICO (CLIENTE) ---
class RegistroClienteForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text="Requerido para facturación")

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']

# --- FORMULARIO DE STAFF (SOLO ADMIN) ---
class CreacionStaffForm(UserCreationForm):
    rolSeleccionado = forms.ModelChoiceField(
        queryset=Group.objects.exclude(name='Cliente'), # El admin solo crea empleados aquí
        label="Rol a Asignar",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']

class CuponForm(forms.ModelForm):
    class Meta:
        model = CuponDescuento
        fields = ['codigoCupon', 'porcentajeDescuento', 'activo']
        labels = {
            'codigoCupon': 'Código (Ej: SALE2026)',
            'porcentajeDescuento': 'Descuento (Ej: 0.10 para 10%)',
            'activo': '¿Activo?'
        }
        widgets = {
            'codigoCupon': forms.TextInput(attrs={'class': 'form-control', 'style': 'text-transform:uppercase;'}),
            'porcentajeDescuento': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }
