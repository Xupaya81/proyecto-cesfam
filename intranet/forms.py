# intranet/forms.py

from django import forms
from .models import Dias_Administrativos, Funcionarios # Importamos modelos necesarios
from django.core.exceptions import ValidationError


class DiasAdministrativosForm(forms.ModelForm):
    """
    Formulario para la gestión de días administrativos y vacaciones.
    Permite a la Subdirección actualizar los saldos de días de los funcionarios.
    Incluye validaciones para evitar valores negativos.
    """
    # Este formulario se basa en tu modelo Dias_Administrativos (Update Days)
    
    # 1. Sobrescribimos los campos para añadir VALIDACIÓN (min_value=0)
    admin_restantes = forms.IntegerField(
        label="Nuevos Días Administrativos", 
        min_value=0, # <-- Asegura que el número no sea negativo
        required=True
    )
    vacaciones_restantes = forms.IntegerField(
        label="Nuevas Vacaciones", 
        min_value=0, # <-- Asegura que el número no sea negativo
        required=True
    )
    
    class Meta:
        model = Dias_Administrativos
        # 2. Solo necesitamos los campos que estamos modificando
        fields = ['admin_restantes', 'vacaciones_restantes']
    
    