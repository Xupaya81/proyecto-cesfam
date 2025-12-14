from django.urls import path
from . import views

# Definición de rutas de la aplicación 'intranet'
# Cada path asocia una URL con una vista específica en views.py

urlpatterns = [
    # --- Vistas de Autenticación y Comunes ---
    # Rutas accesibles para todos los usuarios autenticados
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('documentos/', views.documentos_view, name='documentos'),
    path('documentos/eliminar/<int:doc_id>/', views.eliminar_documento_view, name='eliminar_documento'),
    path('calendario/', views.calendario_view, name='calendario'),
    path('manual/', views.manual_view, name='manual'),
    path('gestion/solicitudes/', views.gestion_solicitudes_view, name='gestion_solicitudes'),

    # --- Vistas de Dashboard Unificado ---
    # Punto de entrada principal tras el login
    path('dashboard/', views.dashboard_view, name='dashboard'), # <-- VISTA UNIFICADA
    
    # Redireccionamos los nombres viejos a la vista unificada (esto es clave para compatibilidad)
    path('dashboard/funcionario/', views.dashboard_view, name='dashboard_funcionario'), # <-- APUNTA A VISTA UNIFICADA
    path('dashboard/subdireccion/', views.dashboard_view, name='dashboard_subdireccion'), # <-- APUNTA A VISTA UNIFICADA

    # --- Vistas de Admin ---
    # Rutas exclusivas para superusuarios
    path('roles/gestion/', views.admin_roles_view, name='roles_gestion'), 
    path('logs/auditoria/', views.admin_logs_view, name='logs_auditoria'),
    
    # --- Gestión de Usuarios (RRHH) ---
    path('gestion/usuarios/', views.gestion_usuarios_view, name='gestion_usuarios'),
    path('gestion/usuarios/crear/', views.crear_usuario_view, name='crear_usuario'),
    path('gestion/usuarios/editar/<int:usuario_id>/', views.editar_usuario_view, name='editar_usuario'),
    path('gestion/usuarios/toggle/<int:usuario_id>/', views.desactivar_usuario_view, name='toggle_usuario'),

    # --- Vistas de Subdirección (Gestión) ---
    # Rutas para usuarios con rol de Subdirección (is_staff)
    path('gestion/calendario/', views.gestion_calendario_view, name='gestion_calendario'),
    path('gestion/dias/', views.gestion_dias_view, name='gestion_dias'),
    path('gestion/documentos/', views.gestion_documentos_view, name='gestion_documentos'),
    path('gestion/licencias/', views.gestion_licencias_view, name='gestion_licencias'),
    
    # Gestión de Comunicados
    path('gestion/comunicados/', views.crear_comunicado_view, name='crear_comunicado'),
    path('gestion/comunicados/editar/<int:comunicado_id>/', views.editar_comunicado_view, name='editar_comunicado'),
    path('gestion/comunicados/eliminar/<int:comunicado_id>/', views.eliminar_comunicado_view, name='eliminar_comunicado'),
    
    # Reportes y Aprobaciones
    path('reporte/licencias/', views.reporte_licencias_view, name='reporte_licencias'),
    path('reportes/solicitudes/', views.reporte_solicitudes_view, name='reporte_solicitudes'),
    path('reportes/solicitudes/exportar/', views.exportar_solicitudes_excel, name='exportar_solicitudes_excel'),
    path('gestion/solicitudes/aprobar/<int:solicitud_id>/', views.aprobar_solicitud_view, name='aprobar_solicitud'),
    
    # --- Historial Personal ---
    # Vista para que el funcionario vea sus propios registros
    path('mi-historial/', views.historial_personal_view, name='historial_personal'),

    # --- Página de Inicio ---
    # Redirige al login por defecto
    path('', views.login_view, name='index'), 

   # --- API Endpoints ---
   # Rutas que retornan JSON para consumo asíncrono (AJAX)
    path('api/eventos/', views.eventos_json_view, name='eventos_json'),
    
]