from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group
from .models import ViniloMusical

# --- FORMULARIO DE PRODUCTOS (Para Bodega/Admin) ---
class ViniloForm(forms.ModelForm):
    class Meta:
        model = ViniloMusical
        fields = ['tituloDisco', 'artistaPrincipal', 'precioUnitario', 'stockDisponible', 'categoria', 'imagenPortada', 'esNuevo', 'aceptaDevolucion']
        widgets = {
            'tituloDisco': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Abbey Road'}),
            'artistaPrincipal': forms.TextInput(attrs={'class': 'form-control'}),
            'precioUnitario': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stockDisponible': forms.NumberInput(attrs={'class': 'form-control'}),
            'esNuevo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
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
