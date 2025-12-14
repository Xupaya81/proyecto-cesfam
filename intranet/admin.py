from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Funcionarios, Dias_Administrativos, Comunicados, Documentos, Logs_Auditoria, Licencias, Roles, Logs_Auditoria, Eventos_Calendario, SolicitudesPermiso, Unidades

# --- 1. El Panel de Admin para tu Usuario Personalizado ---
# Le decimos a Django que use el panel de admin de usuarios, 
# pero que también muestre nuestro campo "id_rol"
class FuncionarioAdmin(UserAdmin):
    """
    Configuración personalizada del panel de administración para el modelo Funcionarios.
    Extiende UserAdmin para incluir campos personalizados como 'id_rol', 'id_unidad', 'es_jefe_unidad'.
    """
    fieldsets = UserAdmin.fieldsets + (
        ('Campos Personalizados', {'fields': ('id_rol', 'nombre', 'id_unidad', 'es_jefe_unidad')}),
    )
    list_display = ('username', 'email', 'id_rol', 'id_unidad', 'es_jefe_unidad', 'is_staff')
    list_filter = ('id_rol', 'id_unidad', 'es_jefe_unidad', 'is_staff')

# --- 2. Registramos todos los modelos ---

# ¡IMPORTANTE! 
# Des-registramos "Funcionarios" de la forma simple y 
# lo registramos con la nueva clase "FuncionarioAdmin"
admin.site.register(Funcionarios, FuncionarioAdmin)

# El resto de tus modelos se registran de forma normal
admin.site.register(Roles)
admin.site.register(Unidades)  # Nuevo modelo de Unidades/Departamentos
admin.site.register(Dias_Administrativos)
admin.site.register(Documentos)
admin.site.register(Comunicados)
admin.site.register(Eventos_Calendario)
admin.site.register(Licencias)
admin.site.register(Logs_Auditoria)
admin.site.register(SolicitudesPermiso)