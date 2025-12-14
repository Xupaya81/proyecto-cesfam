from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.hashers import check_password
from django.contrib import messages
from .models import Funcionarios, Dias_Administrativos, Comunicados, Documentos, Logs_Auditoria, Licencias, Roles, Logs_Auditoria, Eventos_Calendario, SolicitudesPermiso, Licencias, Unidades
from django.db.models import Sum, F, Q
from django.utils import timezone
from datetime import datetime
from .forms import DiasAdministrativosForm
from django.http import JsonResponse, HttpResponse
import openpyxl
from django.contrib.auth.forms import AuthenticationForm

# --- Funciones de Ayuda (para proteger vistas y verificar roles) ---

def es_director(user):
    """Verifica si el usuario es Director General (máximo nivel)."""
    return user.is_superuser or (user.id_rol and user.id_rol.nombre_rol == 'Director General')

def es_subdireccion(user):
    """Verifica si el usuario es Subdirección o superior (nivel <= 2)."""
    if user.is_superuser:
        return True
    if user.id_rol:
        return user.id_rol.nivel_jerarquico <= 2  # Director o Subdirección
    return False

def es_jefe_unidad(user):
    """Verifica si el usuario es Jefe de Unidad."""
    return user.es_jefe_unidad

def es_admin(user):
    """Verifica si el usuario es superusuario (Director General)."""
    return user.is_superuser

def puede_gestionar(user):
    """Verifica si el usuario puede gestionar solicitudes (Jefe, Subdirección o Director)."""
    if user.is_superuser:
        return True
    if user.is_staff:
        return True
    if user.id_rol:
        return user.id_rol.nivel_jerarquico <= 3 or user.es_jefe_unidad
    return user.es_jefe_unidad

def obtener_funcionarios_de_unidad(user):
    """
    Retorna los funcionarios que el usuario puede gestionar según su rol.
    - Director/Subdirección: Todos
    - Jefe de Unidad: Solo su unidad
    - Otros: Solo él mismo
    """
    if es_subdireccion(user):
        return Funcionarios.objects.all()
    elif user.es_jefe_unidad and user.id_unidad:
        return Funcionarios.objects.filter(id_unidad=user.id_unidad)
    else:
        return Funcionarios.objects.filter(pk=user.pk)

def obtener_solicitudes_para_usuario(user):
    """
    Retorna las solicitudes que el usuario puede ver/gestionar según su rol.
    Implementa la lógica de flujo con casos especiales.
    """
    if es_director(user):
        # Director ve TODO + solicitudes de Subdirección pendientes para él
        return SolicitudesPermiso.objects.all()
    
    elif es_subdireccion(user) and not es_director(user):
        # Subdirección ve:
        # 1. Solicitudes Pre-Aprobadas (listas para aprobación final)
        # 2. Solicitudes Pendientes de funcionarios sin jefe (saltan pre-aprobación)
        # 3. Solicitudes Pendientes de Jefes de Unidad (van directo a Subdirección)
        
        # Solicitudes pre-aprobadas
        pre_aprobadas = Q(estado='Pre-Aprobado')
        
        # Solicitudes pendientes de jefes de unidad (ellos no pueden auto-aprobarse)
        de_jefes = Q(estado='Pendiente', id_funcionario_solicitante__es_jefe_unidad=True)
        
        # Solicitudes pendientes de unidades sin jefe
        unidades_con_jefe = Funcionarios.objects.filter(es_jefe_unidad=True).values_list('id_unidad', flat=True)
        sin_jefe = Q(estado='Pendiente') & ~Q(id_funcionario_solicitante__id_unidad__in=unidades_con_jefe)
        
        return SolicitudesPermiso.objects.filter(pre_aprobadas | de_jefes | sin_jefe)
    
    elif user.es_jefe_unidad and user.id_unidad:
        # Jefe de Unidad ve solicitudes Pendientes de SU unidad (excepto las suyas)
        return SolicitudesPermiso.objects.filter(
            estado='Pendiente',
            id_funcionario_solicitante__id_unidad=user.id_unidad
        ).exclude(id_funcionario_solicitante=user)
    
    else:
        # Funcionario normal: solo ve sus propias solicitudes
        return SolicitudesPermiso.objects.filter(id_funcionario_solicitante=user)

# --- 1. Vistas de Autenticación (Login Robusto) ---

def login_view(request):
    """
    Gestiona el inicio de sesión de los usuarios.
    Utiliza AuthenticationForm de Django para validar credenciales.
    Redirige al dashboard correspondiente según el rol del usuario.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: La página de login o redirección al dashboard.
    """
    if request.method == 'POST':
        # 1. Usa AuthenticationForm: maneja automáticamente request.POST, validación, y autenticación.
        form = AuthenticationForm(request, data=request.POST) 

        if form.is_valid():
            # 2. Si la autenticación es exitosa, obtiene el objeto user.
            user = form.get_user() 
            auth_login(request, user)
            
            # Redirección según Rol
            if user.is_superuser:
                return redirect('roles_gestion')
            else:
                return redirect('dashboard')
        else:
            # 3. Si falla (credenciales incorrectas o campos vacíos), 
            # el objeto 'form' ya contiene los mensajes de error.
            return render(request, 'login.html', {'form': form})
    
    # 4. Si es GET, muestra el formulario vacío.
    form = AuthenticationForm()
    return render(request, 'login.html', {'form': form})          

def logout_view(request):
    """
    Cierra la sesión del usuario actual y redirige al login.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Redirección a la vista de login.
    """
    auth_logout(request)
    return redirect('login')


# --- 2. Vistas Compartidas (Dashboard y Navegación) ---

@login_required(login_url='login')
def dashboard_view(request):
    """
    Vista principal del Dashboard con estadísticas según rol.
    - Funcionario: Sus saldos, solicitudes recientes, comunicados, eventos
    - Jefe Unidad: + Solicitudes de su equipo, estadísticas de unidad
    - Subdirección: + Estadísticas de todo el CESFAM
    """
    user = request.user
    from django.db.models import Q, Count
    from django.utils import timezone
    from datetime import timedelta
    
    hoy = timezone.now().date()
    inicio_mes = hoy.replace(day=1)
    
    # 1. Obtener Saldos del funcionario
    try:
        saldos = Dias_Administrativos.objects.get(id_funcionario=user)
    except Dias_Administrativos.DoesNotExist:
        saldos = Dias_Administrativos.objects.create(
            id_funcionario=user,
            vacaciones_restantes=15,
            admin_restantes=6,
            horas_compensacion=0
        )
    
    # 2. Mis solicitudes recientes (últimas 5)
    mis_solicitudes = SolicitudesPermiso.objects.filter(
        id_funcionario_solicitante=user
    ).order_by('-fecha_solicitud')[:5]
    
    # 3. Comunicados (filtrados por visibilidad)
    if es_subdireccion(user):
        comunicados = Comunicados.objects.all().order_by('-fecha_publicacion')[:5]
    else:
        comunicados = Comunicados.objects.filter(
            Q(unidad_destino__isnull=True) |
            Q(unidad_destino=user.id_unidad)
        ).order_by('-fecha_publicacion')[:5]
    
    # 4. Próximos eventos (7 días)
    proximos_eventos = Eventos_Calendario.objects.filter(
        fecha_inicio__gte=hoy,
        fecha_inicio__lte=hoy + timedelta(days=7)
    ).order_by('fecha_inicio')[:5]
    
    # Contexto base para todos
    context = {
        'saldos': saldos,
        'dias_admin': saldos.admin_restantes,
        'dias_vacas': saldos.vacaciones_restantes,
        'horas_comp': saldos.horas_compensacion,
        'mis_solicitudes': mis_solicitudes,
        'comunicados': comunicados,
        'proximos_eventos': proximos_eventos,
        'es_jefe': user.es_jefe_unidad,
        'es_subdir': es_subdireccion(user),
        'fecha_hoy': hoy,
    }
    
    # 5. Estadísticas para JEFE DE UNIDAD
    if user.es_jefe_unidad and user.id_unidad and not es_subdireccion(user):
        # Funcionarios de mi unidad
        funcionarios_unidad = Funcionarios.objects.filter(
            id_unidad=user.id_unidad, is_active=True
        ).count()
        
        # Solicitudes pendientes de pre-aprobar
        solicitudes_pendientes = SolicitudesPermiso.objects.filter(
            estado='Pendiente',
            id_funcionario_solicitante__id_unidad=user.id_unidad
        ).exclude(id_funcionario_solicitante=user).count()
        
        # Funcionarios con licencia activa hoy
        con_licencia_hoy = Licencias.objects.filter(
            id_funcionario__id_unidad=user.id_unidad,
            fecha_inicio__lte=hoy,
            fecha_fin__gte=hoy
        ).count()
        
        # Ausencias del mes en mi unidad
        ausencias_mes = SolicitudesPermiso.objects.filter(
            id_funcionario_solicitante__id_unidad=user.id_unidad,
            estado='Aprobado',
            fecha_inicio__gte=inicio_mes,
            fecha_inicio__lte=hoy
        ).aggregate(total=Count('id'))['total'] or 0
        
        # Solicitudes pendientes detalle
        solicitudes_pendientes_lista = SolicitudesPermiso.objects.filter(
            estado='Pendiente',
            id_funcionario_solicitante__id_unidad=user.id_unidad
        ).exclude(id_funcionario_solicitante=user).order_by('-fecha_solicitud')[:5]
        
        context.update({
            'unidad_nombre': user.id_unidad.nombre_unidad,
            'funcionarios_unidad': funcionarios_unidad,
            'solicitudes_pendientes': solicitudes_pendientes,
            'con_licencia_hoy': con_licencia_hoy,
            'ausencias_mes': ausencias_mes,
            'solicitudes_pendientes_lista': solicitudes_pendientes_lista,
        })
    
    # 6. Estadísticas para SUBDIRECCIÓN/DIRECTOR
    if es_subdireccion(user):
        # Total funcionarios activos
        total_funcionarios = Funcionarios.objects.filter(is_active=True).count()
        
        # Solicitudes por aprobar (pre-aprobadas + pendientes de jefes/sin jefe)
        unidades_con_jefe = Funcionarios.objects.filter(es_jefe_unidad=True).values_list('id_unidad', flat=True)
        solicitudes_por_aprobar = SolicitudesPermiso.objects.filter(
            Q(estado='Pre-Aprobado') |
            Q(estado='Pendiente', id_funcionario_solicitante__es_jefe_unidad=True) |
            (Q(estado='Pendiente') & ~Q(id_funcionario_solicitante__id_unidad__in=unidades_con_jefe))
        ).count()
        
        # Funcionarios con licencia activa hoy (todo CESFAM)
        con_licencia_hoy_total = Licencias.objects.filter(
            fecha_inicio__lte=hoy,
            fecha_fin__gte=hoy
        ).count()
        
        # Solicitudes por aprobar detalle
        solicitudes_aprobar_lista = SolicitudesPermiso.objects.filter(
            Q(estado='Pre-Aprobado') |
            Q(estado='Pendiente', id_funcionario_solicitante__es_jefe_unidad=True) |
            (Q(estado='Pendiente') & ~Q(id_funcionario_solicitante__id_unidad__in=unidades_con_jefe))
        ).order_by('-fecha_solicitud')[:5]
        
        # Ausencias por unidad este mes
        from intranet.models import Unidades
        ausencias_por_unidad = []
        for unidad in Unidades.objects.filter(activa=True).order_by('nombre_unidad')[:8]:
            dias = SolicitudesPermiso.objects.filter(
                id_funcionario_solicitante__id_unidad=unidad,
                estado='Aprobado',
                fecha_inicio__gte=inicio_mes
            ).aggregate(total=Count('id'))['total'] or 0
            if dias > 0:
                ausencias_por_unidad.append({
                    'unidad': unidad.nombre_unidad,
                    'dias': dias
                })
        ausencias_por_unidad.sort(key=lambda x: x['dias'], reverse=True)
        
        # Cumpleaños del mes (si hay campo de fecha nacimiento - usamos fecha_joined como demo)
        # Como no tenemos fecha_nacimiento, mostramos nuevos funcionarios del mes
        nuevos_mes = Funcionarios.objects.filter(
            date_joined__month=hoy.month,
            is_active=True
        ).count()
        
        context.update({
            'total_funcionarios': total_funcionarios,
            'solicitudes_por_aprobar': solicitudes_por_aprobar,
            'con_licencia_hoy_total': con_licencia_hoy_total,
            'solicitudes_aprobar_lista': solicitudes_aprobar_lista,
            'ausencias_por_unidad': ausencias_por_unidad,
            'nuevos_mes': nuevos_mes,
        })
    
    return render(request, 'dashboard.html', context)

@login_required(login_url='login')
def documentos_view(request):
    """
    Vista para el Repositorio Documental con visibilidad jerárquica inteligente.
    
    Lógica de visibilidad:
    - Funcionarios: Privado, Mi Unidad, Enviar a Jefatura
    - Jefes: + Otros Jefes, Público
    - Subdirección/Director: + Unidad específica, Solo Jefes, Público
    """
    user = request.user
    nivel_usuario = user.id_rol.nivel_jerarquico if user.id_rol else 5
    es_jefe = nivel_usuario == 3
    es_superior = nivel_usuario <= 2  # Subdirección o Director
    
    # Manejo de subida de documentos
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        categoria = request.POST.get('categoria')
        archivo = request.FILES.get('archivo')
        visibilidad = request.POST.get('visibilidad')
        
        if titulo and archivo:
            doc = Documentos.objects.create(
                titulo=titulo,
                categoria=categoria,
                ruta_archivo=archivo,
                id_autor_carga=user,
                publico=False,
                compartir_unidad=False,
                compartir_jefes=False,
                compartir_superiores=False,
                unidad_destino=None
            )
            
            # Aplicar visibilidad según opción seleccionada
            if visibilidad == 'publico':
                doc.publico = True
            elif visibilidad == 'mi_unidad':
                doc.compartir_unidad = True
            elif visibilidad == 'jefatura':
                doc.compartir_superiores = True
            elif visibilidad == 'otros_jefes':
                doc.compartir_jefes = True
                doc.compartir_superiores = True
            elif visibilidad == 'solo_jefes':
                doc.compartir_jefes = True
            elif visibilidad == 'unidad_especifica':
                unidad_id = request.POST.get('unidad_destino')
                if unidad_id:
                    doc.unidad_destino_id = unidad_id
            
            doc.save()
            messages.success(request, f'Documento "{titulo}" subido exitosamente.')
            return redirect('documentos')

    # === FILTRAR DOCUMENTOS SEGÚN VISIBILIDAD ===
    # El usuario puede ver:
    # 1. Documentos que él subió (siempre)
    # 2. Documentos públicos
    # 3. Documentos compartidos con su unidad (si es de esa unidad)
    # 4. Documentos compartidos con jefes (si es jefe o superior)
    # 5. Documentos compartidos con superiores (si es subdirección/director)
    # 6. Documentos destinados a su unidad específica
    
    filtro = Q(id_autor_carga=user) | Q(publico=True)
    
    # Si tiene unidad, ver los compartidos con su unidad
    if user.id_unidad:
        filtro |= Q(compartir_unidad=True, id_autor_carga__id_unidad=user.id_unidad)
        # Ver docs destinados específicamente a su unidad
        filtro |= Q(unidad_destino=user.id_unidad)
    
    # Si es Jefe o superior, ver docs compartidos con jefes
    if es_jefe or es_superior:
        filtro |= Q(compartir_jefes=True)
    
    # Si es superior (Subdirección/Director), ver docs enviados a jefatura
    if es_superior:
        filtro |= Q(compartir_superiores=True)
    
    # Aplicar búsqueda si existe
    query = request.GET.get('q')
    cat_filter = request.GET.get('cat')
    
    docs = Documentos.objects.filter(filtro).distinct().order_by('-fecha_carga')
    
    if query:
        docs = docs.filter(titulo__icontains=query)
    if cat_filter:
        docs = docs.filter(categoria=cat_filter)
    
    # Obtener unidades para el formulario (solo para superiores)
    unidades = Unidades.objects.all() if es_superior else None
        
    return render(request, 'documentos.html', {
        'documentos': docs,
        'unidades': unidades,
        'es_jefe': es_jefe,
        'es_superior': es_superior,
        'nivel_usuario': nivel_usuario,
    })

@login_required(login_url='login')
def eliminar_documento_view(request, doc_id):
    """
    Permite eliminar un documento específico.
    Solo el autor del documento o un superusuario pueden realizar esta acción.
    
    Args:
        request (HttpRequest): La petición HTTP.
        doc_id (int): El ID del documento a eliminar.
        
    Returns:
        HttpResponse: Redirección a la vista de documentos.
    """
    doc = get_object_or_404(Documentos, pk=doc_id)
    
    # Verificación de permisos
    if doc.id_autor_carga == request.user or request.user.is_superuser:
        doc.delete()
        # Opcional: Mensaje de éxito
    
    return redirect('documentos')

@login_required(login_url='login')
def calendario_view(request):
    """
    Vista para mostrar el calendario de eventos.
    Los eventos se cargan dinámicamente vía AJAX desde 'eventos_json_view'.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza 'calendario.html'.
    """
    # Aquí se listarán los eventos del modelo Eventos_Calendario
    return render(request, 'calendario.html')

@login_required(login_url='login')
def manual_view(request):
    """
    Vista para mostrar el manual de usuario o ayuda.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza 'manual.html'.
    """
    return render(request, 'manual.html')

@login_required(login_url='login')
def gestion_solicitudes_view(request):
    """
    Vista para que el Funcionario envíe solicitudes de permisos.
    Tipos: administrativo, vacaciones, sin_goce, hora_medica, licencia, duelo, compensacion
    Implementa validaciones y casos especiales (Director: Auto-aprobación).
    """
    user = request.user
    
    # Obtener saldos del funcionario
    saldos, created = Dias_Administrativos.objects.get_or_create(
        id_funcionario=user,
        defaults={'vacaciones_restantes': 15, 'admin_restantes': 6, 'horas_compensacion': 0}
    )
    
    if request.method == 'POST':
        tipo = request.POST.get('tipo_permiso')
        inicio_str = request.POST.get('fecha_inicio')
        fin_str = request.POST.get('fecha_fin')
        archivo = request.FILES.get('justificativo_archivo')
        observaciones = request.POST.get('observaciones', '')
        horas_str = request.POST.get('horas_solicitadas', '0')
        
        try:
            fecha_inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fin_str, '%Y-%m-%d').date()
            horas = int(horas_str) if horas_str else 0

            if fecha_fin < fecha_inicio:
                return render(request, 'gestion_solicitudes.html', {
                    'error': 'La fecha de término no puede ser anterior a la de inicio.',
                    'saldos': saldos
                })

            dias_solicitados = (fecha_fin - fecha_inicio).days + 1
            
            # --- VALIDACIONES POR TIPO ---
            
            # Día Administrativo: máximo 6/año y verificar saldo
            if tipo == 'administrativo':
                if dias_solicitados > saldos.admin_restantes:
                    return render(request, 'gestion_solicitudes.html', {
                        'error': f'No tienes suficientes días administrativos. Disponibles: {saldos.admin_restantes}, Solicitados: {dias_solicitados}',
                        'saldos': saldos
                    })
            
            # Vacaciones: verificar saldo
            if tipo == 'vacaciones':
                if dias_solicitados > saldos.vacaciones_restantes:
                    return render(request, 'gestion_solicitudes.html', {
                        'error': f'No tienes suficientes días de vacaciones. Disponibles: {saldos.vacaciones_restantes}, Solicitados: {dias_solicitados}',
                        'saldos': saldos
                    })
            
            # Licencia y Duelo: requieren documento
            if tipo in ['licencia', 'duelo'] and not archivo:
                return render(request, 'gestion_solicitudes.html', {
                    'error': f'El tipo "{tipo}" requiere documento justificativo obligatorio.',
                    'saldos': saldos
                })
            
            # Hora médica: máximo 4 horas, mismo día
            if tipo == 'hora_medica':
                if horas < 1 or horas > 4:
                    return render(request, 'gestion_solicitudes.html', {
                        'error': 'Hora médica debe ser entre 1 y 4 horas.',
                        'saldos': saldos
                    })
                fecha_fin = fecha_inicio  # Mismo día
                dias_solicitados = 1
            
            # Compensación: verificar horas acumuladas
            if tipo == 'compensacion':
                horas_necesarias = dias_solicitados * 8  # 8 horas por día
                if horas_necesarias > saldos.horas_compensacion:
                    return render(request, 'gestion_solicitudes.html', {
                        'error': f'No tienes suficientes horas de compensación. Disponibles: {saldos.horas_compensacion}, Necesarias: {horas_necesarias}',
                        'saldos': saldos
                    })
            
            # Duelo: máximo 7 días
            if tipo == 'duelo' and dias_solicitados > 7:
                return render(request, 'gestion_solicitudes.html', {
                    'error': 'El permiso por duelo es de máximo 7 días.',
                    'saldos': saldos
                })
            
            # Crear la solicitud
            solicitud = SolicitudesPermiso.objects.create(
                id_funcionario_solicitante=user,
                tipo_permiso=tipo,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                dias_solicitados=dias_solicitados,
                horas_solicitadas=horas if tipo == 'hora_medica' else 0,
                justificativo_archivo=archivo,
                observaciones=observaciones,
                estado='Pendiente'
            )
            
            # --- CASO ESPECIAL: Director solicita (Auto-aprobación) ---
            if es_director(user):
                # Descontar según tipo
                if tipo == 'vacaciones':
                    saldos.vacaciones_restantes -= dias_solicitados
                    saldos.save()
                elif tipo == 'administrativo':
                    saldos.admin_restantes -= dias_solicitados
                    saldos.save()
                elif tipo == 'compensacion':
                    saldos.horas_compensacion -= (dias_solicitados * 8)
                    saldos.save()
                
                solicitud.estado = 'Aprobado'
                solicitud.aprobado_por = user
                solicitud.fecha_aprobacion = timezone.now()
                solicitud.save()
                
                Logs_Auditoria.objects.create(
                    id_usuario_actor=user,
                    accion='Solicitud Auto-Aprobada (Director)',
                    detalle=f"Director {user.username} auto-aprobó solicitud de {tipo}. Días: {dias_solicitados}"
                )
            
            return redirect('historial_personal')
            
        except ValueError as e:
            return render(request, 'gestion_solicitudes.html', {
                'error': f'Error en los datos: {str(e)}',
                'saldos': saldos
            })

    # Contexto para mostrar info del usuario
    context = {
        'es_director': es_director(user),
        'es_jefe': user.es_jefe_unidad,
        'saldos': saldos,
    }
    return render(request, 'gestion_solicitudes.html', context)

# --- 3. Vistas de Subdirección (Protegidas) ---

@user_passes_test(es_subdireccion, login_url='login')
def gestion_documentos_view(request):
    """
    Vista de gestión de documentos para Subdirección.
    Permite subir documentos oficiales al repositorio.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza el formulario de gestión o redirige tras éxito.
    """
    if request.method == 'POST':

        titulo = request.POST.get('titulo')
        categoria = request.POST.get('categoria')
        
        archivo = request.FILES.get('archivo') 


        if titulo and archivo:
            Documentos.objects.create(
                titulo=titulo,
                categoria=categoria,
                ruta_archivo=archivo,
                id_autor_carga=request.user
            )
            
            return redirect('documentos') 
        else:
            return render(request, 'gestion_documentos.html', {'error': 'Debe completar título y adjuntar un archivo.'})
            
    return render(request, 'gestion_documentos.html')

@user_passes_test(es_subdireccion, login_url='login')
def gestion_calendario_view(request):
    """
    Vista para que la Subdirección agregue eventos al calendario.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza el formulario de gestión de calendario.
    """
    if request.method == 'POST':
        # 1. Obtener los datos
        titulo = request.POST.get('titulo')
        tipo_evento = request.POST.get('tipo_evento')
        fecha_inicio = request.POST.get('fecha_inicio')
        
        # 2. Validar y crear
        if titulo and fecha_inicio:
            Eventos_Calendario.objects.create(
                titulo=titulo,
                tipo_evento=tipo_evento,
                fecha_inicio=fecha_inicio
            )
            # 3. Redirige al calendario (RF7)
            return redirect('calendario')
            
    # Se obtienen datos si se necesitan para un selector, pero por ahora solo renderiza
    return render(request, 'gestion_calendario.html')

@login_required(login_url='login')
def gestion_dias_view(request):
    """
    Vista para gestionar los días administrativos y vacaciones de los funcionarios.
    Filtra según el rol:
    - Director/Subdirección: Ve todos los funcionarios
    - Jefe de Unidad: Solo ve funcionarios de su unidad
    """
    user = request.user
    
    # Verificar permisos
    if not puede_gestionar(user):
        return redirect('dashboard')
    
    # Filtrar funcionarios según rol
    funcionarios_qs = obtener_funcionarios_de_unidad(user).order_by('username')
    funcionarios_data = []
    
    for f in funcionarios_qs:
        try:
            dias = f.dias_administrativos
            vacaciones = dias.vacaciones_restantes
            admin = dias.admin_restantes
        except Dias_Administrativos.DoesNotExist:
            vacaciones = 0
            admin = 0
            
        funcionarios_data.append({
            'pk': f.pk,
            'username': f.username,
            'first_name': f.first_name,
            'last_name': f.last_name,
            'vacaciones': vacaciones,
            'admin': admin,
            'unidad': f.id_unidad.nombre_unidad if f.id_unidad else 'Sin unidad',
            'rol': f.id_rol.nombre_rol if f.id_rol else 'Sin rol',
        })

    # Lógica de PROCESAMIENTO (POST)
    if request.method == 'POST':
        funcionario_id = request.POST.get('funcionario_id')
        funcionario_obj = get_object_or_404(Funcionarios, pk=funcionario_id)
        
        # Verificar que puede modificar a este funcionario
        if not es_subdireccion(user):
            if user.id_unidad != funcionario_obj.id_unidad:
                return redirect('gestion_dias')
        
        dias_obj, created = Dias_Administrativos.objects.get_or_create(
            id_funcionario=funcionario_obj
        )
        
        form = DiasAdministrativosForm(request.POST, instance=dias_obj)

        if form.is_valid():
            form.save()
            
            # Log de auditoría
            Logs_Auditoria.objects.create(
                id_usuario_actor=user,
                accion='Modificación de Días',
                detalle=f"Se modificaron los días de {funcionario_obj.username}"
            )
            return redirect('gestion_dias')
    
    form = DiasAdministrativosForm() 
    
    context = {
        'funcionarios': funcionarios_data,
        'form': form,
        'es_jefe': user.es_jefe_unidad,
        'unidad_usuario': user.id_unidad.nombre_unidad if user.id_unidad else 'Sin unidad',
    }
    return render(request, 'gestion_dias.html', context)
# intranet/views.py

# intranet/views.py (Reemplazar gestion_licencias_view)

@user_passes_test(es_subdireccion, login_url='login')
def gestion_licencias_view(request):
    """
    Vista para registrar manualmente licencias médicas.
    Permite a la Subdirección subir licencias para funcionarios.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza el formulario o redirige al reporte.
    """
    if request.method == 'POST':
        # 1. Obtener los datos y el archivo
        funcionario_id = request.POST.get('funcionario_id')
        fecha_inicio = request.POST.get('fecha_inicio')
        fecha_fin = request.POST.get('fecha_fin')
        foto_licencia = request.FILES.get('foto') # Nombre del campo en el HTML es 'foto'
        
        # 2. Validar
        if funcionario_id and foto_licencia:
            try:
                # Buscamos al funcionario afectado
                funcionario_afectado = Funcionarios.objects.get(pk=funcionario_id)
                
                # 3. Guardar la licencia en la base de datos (Documento Maestro)
                Licencias.objects.create(
                    id_funcionario=funcionario_afectado,
                    id_subdireccion_carga=request.user, # La subdirección logueada es quien sube
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    ruta_foto_licencia=foto_licencia
                )
                # 4. Redirige al reporte para ver el registro
                return redirect('reporte_licencias')
            except Funcionarios.DoesNotExist:
                # Si el ID no corresponde a un funcionario, se sigue mostrando el formulario
                pass
            
    # Lógica de CARGA DE PÁGINA (GET)
    # Se obtienen todos los funcionarios para el selector del formulario
    funcionarios = Funcionarios.objects.all().order_by('username')
    return render(request, 'gestion_licencias.html', {'funcionarios': funcionarios})

@login_required(login_url='login')
def reporte_licencias_view(request):
    """
    Vista para listar licencias registradas.
    - Subdirección/Director: Ve todas las licencias
    - Jefe de Unidad: Ve solo licencias de su unidad
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza 'reporte_licencias.html'.
    """
    user = request.user
    
    # Verificar que puede gestionar (Subdirección o Jefe de Unidad)
    if not puede_gestionar(user):
        return redirect('dashboard')
    
    # Filtrar licencias según rol
    if es_subdireccion(user):
        # Subdirección ve todas las licencias
        licencias = Licencias.objects.all().order_by('-fecha_registro')
    else:
        # Jefe de Unidad ve solo licencias de su unidad
        licencias = Licencias.objects.filter(
            id_funcionario__id_unidad=user.id_unidad
        ).order_by('-fecha_registro')
    
    context = {
        'licencias': licencias,
        # 2. Eliminamos la línea que causaba el FieldError. 
        #    La suma de días es un cálculo complejo que haremos después si sobra tiempo.
        'dias_totales': 0 
    }
    return render(request, 'reporte_licencias.html', context)

# intranet/views.py

@login_required(login_url='login')
def reporte_solicitudes_view(request):
    """
    Vista para revisar y gestionar solicitudes de permiso.
    Filtra según el rol del usuario:
    - Director: Ve todas las solicitudes
    - Subdirección: Ve pre-aprobadas + pendientes sin jefe + de jefes
    - Jefe de Unidad: Ve pendientes de su unidad (para pre-aprobar)
    """
    user = request.user
    
    # Verificar que puede gestionar
    if not puede_gestionar(user):
        return redirect('dashboard')
    
    # Obtener solicitudes según rol
    solicitudes = obtener_solicitudes_para_usuario(user).order_by('-fecha_solicitud')
    
    # Determinar qué acción puede hacer el usuario
    puede_aprobar_final = es_subdireccion(user)
    puede_pre_aprobar = user.es_jefe_unidad and not es_subdireccion(user)
    
    context = {
        'solicitudes': solicitudes,
        'puede_aprobar_final': puede_aprobar_final,
        'puede_pre_aprobar': puede_pre_aprobar,
        'es_jefe': user.es_jefe_unidad,
        'unidad_usuario': user.id_unidad.nombre_unidad if user.id_unidad else 'Sin unidad',
    }
    return render(request, 'reporte_solicitudes.html', context)

@user_passes_test(es_subdireccion, login_url='login')
def exportar_solicitudes_excel(request):
    """
    Exporta las solicitudes pendientes a un archivo Excel.
    Genera un reporte descargable para gestión externa.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Archivo Excel (.xlsx) adjunto.
    """
    response = HttpResponse(content_type='application/ms-excel')
    response['Content-Disposition'] = 'attachment; filename="solicitudes_pendientes.xlsx"'

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Solicitudes Pendientes"

    # Encabezados
    headers = ['Funcionario', 'Tipo Permiso', 'Desde', 'Hasta', 'Días', 'Fecha Solicitud', 'Estado']
    ws.append(headers)

    # Datos
    solicitudes = SolicitudesPermiso.objects.filter(estado='Pendiente').order_by('-fecha_solicitud')
    for sol in solicitudes:
        ws.append([
            f"{sol.id_funcionario_solicitante.first_name} {sol.id_funcionario_solicitante.last_name}",
            sol.tipo_permiso,
            sol.fecha_inicio.strftime('%Y-%m-%d'),
            sol.fecha_fin.strftime('%Y-%m-%d'),
            sol.dias_solicitados,
            sol.fecha_solicitud.strftime('%Y-%m-%d %H:%M'),
            sol.estado
        ])

    wb.save(response)
    return response

@login_required(login_url='login')
def aprobar_solicitud_view(request, solicitud_id):
    """
    Procesa la aprobación/pre-aprobación de una solicitud según el rol del usuario.
    
    Flujo:
    - Director que solicita: Auto-aprobado
    - Subdirección que solicita: Va a Director
    - Jefe que solicita: Va directo a Subdirección
    - Funcionario: Jefe pre-aprueba → Subdirección aprueba final
    - Sin jefe en unidad: Directo a Subdirección
    """
    if request.method == 'POST':
        solicitud = get_object_or_404(SolicitudesPermiso, pk=solicitud_id)
        user = request.user
        accion = request.POST.get('accion', 'aprobar')
        
        # --- RECHAZAR (cualquier nivel puede rechazar) ---
        if accion == 'rechazar':
            comentario = request.POST.get('comentario_rechazo', '')
            solicitud.estado = 'Rechazado'
            solicitud.comentario_rechazo = comentario
            solicitud.save()
            
            # Log de auditoría
            Logs_Auditoria.objects.create(
                id_usuario_actor=user,
                accion='Solicitud Rechazada',
                detalle=f"Solicitud #{solicitud.pk} de {solicitud.id_funcionario_solicitante.username} rechazada. Motivo: {comentario}"
            )
            return redirect('reporte_solicitudes')
        
        # --- PRE-APROBAR (Solo Jefe de Unidad) ---
        if accion == 'pre_aprobar' and solicitud.estado == 'Pendiente':
            if user.es_jefe_unidad:
                solicitud.estado = 'Pre-Aprobado'
                solicitud.pre_aprobado_por = user
                solicitud.fecha_pre_aprobacion = timezone.now()
                solicitud.save()
                
                # Log de auditoría
                Logs_Auditoria.objects.create(
                    id_usuario_actor=user,
                    accion='Solicitud Pre-Aprobada',
                    detalle=f"Solicitud #{solicitud.pk} de {solicitud.id_funcionario_solicitante.username} pre-aprobada por Jefe de Unidad"
                )
            return redirect('reporte_solicitudes')
        
        # --- APROBAR FINAL (Solo Subdirección o Director) ---
        if accion == 'aprobar' and solicitud.estado in ['Pendiente', 'Pre-Aprobado']:
            if es_subdireccion(user):
                
                # Obtener saldos del solicitante
                saldos, created = Dias_Administrativos.objects.get_or_create(
                    id_funcionario=solicitud.id_funcionario_solicitante,
                    defaults={'vacaciones_restantes': 15, 'admin_restantes': 6, 'horas_compensacion': 0}
                )
                
                # Lógica por tipo de permiso
                tipo = solicitud.tipo_permiso
                
                # Licencia Médica: Crea registro en tabla Licencias
                if tipo == 'licencia':
                    Licencias.objects.create(
                        id_funcionario=solicitud.id_funcionario_solicitante,
                        id_subdireccion_carga=user,
                        fecha_inicio=solicitud.fecha_inicio,
                        fecha_fin=solicitud.fecha_fin,
                        ruta_foto_licencia=solicitud.justificativo_archivo 
                    )
                
                # Vacaciones: Descuenta del saldo
                elif tipo == 'vacaciones':
                    saldos.vacaciones_restantes -= solicitud.dias_solicitados
                    saldos.save()
                
                # Día Administrativo: Descuenta del saldo
                elif tipo == 'administrativo':
                    saldos.admin_restantes -= solicitud.dias_solicitados
                    saldos.save()
                
                # Compensación: Descuenta horas (8 por día)
                elif tipo == 'compensacion':
                    saldos.horas_compensacion -= (solicitud.dias_solicitados * 8)
                    saldos.save()
                
                # Sin goce, Duelo, Hora médica: No descuentan saldo
                # (solo se aprueban)
                
                # Marcar como aprobada
                solicitud.estado = 'Aprobado'
                solicitud.aprobado_por = user
                solicitud.fecha_aprobacion = timezone.now()
                solicitud.save()
                
                # Log de auditoría
                tipo_display = dict(SolicitudesPermiso.TIPOS_PERMISO).get(tipo, tipo)
                Logs_Auditoria.objects.create(
                    id_usuario_actor=user,
                    accion='Solicitud Aprobada',
                    detalle=f"Solicitud #{solicitud.pk} ({tipo_display}) de {solicitud.id_funcionario_solicitante.username} aprobada. Días: {solicitud.dias_solicitados}"
                )

    return redirect('reporte_solicitudes')


@login_required(login_url='login')
def crear_solicitud_view(request):
    """
    Vista para que cualquier funcionario cree una solicitud.
    Implementa auto-aprobación para Director y flujo directo para Subdirección.
    """
    if request.method == 'POST':
        user = request.user
        tipo = request.POST.get('tipo_permiso')
        inicio_str = request.POST.get('fecha_inicio')
        fin_str = request.POST.get('fecha_fin')
        archivo = request.FILES.get('justificativo_archivo')
        
        try:
            fecha_inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fin_str, '%Y-%m-%d').date()
            
            if fecha_fin < fecha_inicio:
                return render(request, 'gestion_solicitudes.html', {'error': 'La fecha de término no puede ser anterior a la de inicio.'})
            
            dias_solicitados = (fecha_fin - fecha_inicio).days + 1
            
            # Crear la solicitud
            solicitud = SolicitudesPermiso.objects.create(
                id_funcionario_solicitante=user,
                tipo_permiso=tipo,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                dias_solicitados=dias_solicitados,
                justificativo_archivo=archivo,
                estado='Pendiente'
            )
            
            # --- CASO ESPECIAL: Director solicita (Auto-aprobación) ---
            if es_director(user):
                # Auto-aprobar y descontar días
                if tipo in ['vacaciones', 'administrativo']:
                    campo = 'vacaciones_restantes' if tipo == 'vacaciones' else 'admin_restantes'
                    Dias_Administrativos.objects.filter(id_funcionario=user).update(
                        **{campo: F(campo) - dias_solicitados}
                    )
                
                solicitud.estado = 'Aprobado'
                solicitud.aprobado_por = user
                solicitud.fecha_aprobacion = timezone.now()
                solicitud.save()
                
                Logs_Auditoria.objects.create(
                    id_usuario_actor=user,
                    accion='Solicitud Auto-Aprobada (Director)',
                    detalle=f"Director {user.username} auto-aprobó solicitud de {tipo}. Días: {dias_solicitados}"
                )
            
            return redirect('historial_personal')
            
        except ValueError:
            return render(request, 'gestion_solicitudes.html', {'error': 'Formato de fecha inválido.'})
    
    return render(request, 'gestion_solicitudes.html')

# --- 4. Vistas de Admin (Protegidas) ---

@login_required(login_url='login') 
@user_passes_test(es_admin, login_url='login')
def admin_roles_view(request):
    """
    Vista de administración de roles.
    Permite al Administrador cambiar el rol de los usuarios y sus permisos asociados.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza la tabla de usuarios y roles.
    """
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        new_role_id = request.POST.get('new_role')
        
        try:
            user = Funcionarios.objects.get(pk=user_id)
            role = Roles.objects.get(pk=new_role_id)
            
            # Actualizar Rol
            user.id_rol = role
            
            # Actualizar permisos de Django (is_staff/is_superuser) según el rol
            if role.nombre_rol == 'Administrador':
                user.is_superuser = True
                user.is_staff = True
            elif role.nombre_rol == 'Subdirección':
                user.is_superuser = False
                user.is_staff = True
            else: # Funcionario
                user.is_superuser = False
                user.is_staff = False
                
            user.save()
            
            # Registrar en Logs (RF18)
            Logs_Auditoria.objects.create(
                id_usuario_actor=request.user,
                accion='Cambio de Rol',
                detalle=f"Se cambió el rol de {user.username} a {role.nombre_rol}"
            )
            
        except (Funcionarios.DoesNotExist, Roles.DoesNotExist):
            pass # Manejar error si es necesario

    # Obtener todos los usuarios y roles para mostrarlos en la tabla
    users_list = Funcionarios.objects.all().order_by('username')
    roles_list = Roles.objects.all()
    
    context = {
        'users': users_list,
        'roles': roles_list
    }
    return render(request, 'admin_roles.html', context)

@login_required(login_url='login') 
@user_passes_test(es_admin, login_url='login')
def admin_logs_view(request):
    """
    Vista para visualizar los logs de auditoría del sistema.
    Permite al Administrador rastrear acciones críticas.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza la tabla de logs.
    """
    logs_list = Logs_Auditoria.objects.all().order_by('-fecha_hora')
    context = {
        'logs': logs_list
    }
    return render(request, 'admin_logs.html', context)

# intranet/views.py

@login_required(login_url='login')
def historial_personal_view(request):
    """
    Vista para que el Funcionario vea su historial de solicitudes y licencias.
    Muestra tanto las solicitudes realizadas como las licencias médicas registradas.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza 'historial_personal.html'.
    """
    user = request.user
    
    # 1. Solicitudes de permiso: propias del usuario logueado
    solicitudes = SolicitudesPermiso.objects.filter(id_funcionario_solicitante=user).order_by('-fecha_solicitud')
    
    # 2. Historial de licencias: licencias emitidas a este funcionario
    licencias_recibidas = Licencias.objects.filter(id_funcionario=user).order_by('-fecha_inicio')
    
    # 3. Saldos del funcionario
    saldos, created = Dias_Administrativos.objects.get_or_create(
        id_funcionario=user,
        defaults={'vacaciones_restantes': 15, 'admin_restantes': 6, 'horas_compensacion': 0}
    )
    
    context = {
        'solicitudes': solicitudes,
        'licencias_recibidas': licencias_recibidas,
        'saldos': saldos,
    }
    return render(request, 'historial_personal.html', context)

@login_required(login_url='login')
def eventos_json_view(request):
    """
    Vista que retorna los eventos del calendario en formato JSON para FullCalendar.
    Adapta los datos del modelo Eventos_Calendario al formato esperado por la librería JS.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        JsonResponse: Lista de eventos en formato JSON.
    """
    # 1. Obtener todos los eventos
    eventos = Eventos_Calendario.objects.all()
    
    # 2. Adaptar los datos al formato específico que FullCalendar espera
    data = []
    for evento in eventos:
        data.append({
            'title': f"{evento.tipo_evento}: {evento.titulo}",
            # Formato YYYY-MM-DD para FullCalendar
            'start': evento.fecha_inicio.strftime('%Y-%m-%d'), 
            # Si hay fecha fin, la usa, sino, usa la de inicio
            'end': evento.fecha_fin.strftime('%Y-%m-%d') if evento.fecha_fin else evento.fecha_inicio.strftime('%Y-%m-%d'),
            'color': '#f4a460' if evento.tipo_evento == 'Feriado' else '#1E4A7B',
            'allDay': True,
        })
        
    return JsonResponse(data, safe=False)

@login_required(login_url='login')
def crear_comunicado_view(request):
    """
    Vista para crear comunicados.
    - Director/Subdirección: Puede crear comunicados globales o para unidades específicas
    - Jefe de Unidad: Solo puede crear comunicados para su propia unidad
    """
    user = request.user
    
    # Verificar permisos: debe ser Subdirección o Jefe de Unidad
    if not (es_subdireccion(user) or user.es_jefe_unidad):
        return redirect('dashboard')
    
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        cuerpo = request.POST.get('cuerpo')
        unidad_destino_id = request.POST.get('unidad_destino')
        
        if titulo and cuerpo:
            # Determinar la unidad destino
            unidad_destino = None
            
            if es_subdireccion(user):
                # Director/Subdirección puede elegir: global (vacío) o unidad específica
                if unidad_destino_id:
                    unidad_destino = Unidades.objects.filter(pk=unidad_destino_id).first()
            else:
                # Jefe de Unidad: solo puede publicar para su unidad
                unidad_destino = user.id_unidad
            
            comunicado = Comunicados.objects.create(
                titulo=titulo,
                cuerpo=cuerpo,
                id_autor=user,
                unidad_destino=unidad_destino
            )
            
            # Registrar en Logs
            destino_txt = "Global" if unidad_destino is None else unidad_destino.nombre_unidad
            Logs_Auditoria.objects.create(
                id_usuario_actor=user,
                accion='Creación de Comunicado',
                detalle=f"Se publicó comunicado '{titulo}' para: {destino_txt}"
            )
            
            return redirect('dashboard')
    
    # Contexto para el template
    context = {
        'es_subdireccion': es_subdireccion(user),
        'es_jefe': user.es_jefe_unidad,
        'unidad_usuario': user.id_unidad,
        'unidades': Unidades.objects.filter(activa=True) if es_subdireccion(user) else None,
    }
    return render(request, 'crear_comunicado.html', context)

@login_required(login_url='login')
def editar_comunicado_view(request, comunicado_id):
    """
    Vista para editar un comunicado existente.
    - Director/Subdirección pueden editar cualquier comunicado
    - Jefes de Unidad solo pueden editar sus propios comunicados
    """
    comunicado = get_object_or_404(Comunicados, pk=comunicado_id)
    user = request.user
    
    # Verificar permisos: Subdirección o autor del comunicado
    if not (es_subdireccion(user) or comunicado.id_autor == user):
        return redirect('dashboard')
    
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        cuerpo = request.POST.get('cuerpo')
        
        if titulo and cuerpo:
            comunicado.titulo = titulo
            comunicado.cuerpo = cuerpo
            comunicado.save()
            
            # Registrar en Logs
            Logs_Auditoria.objects.create(
                id_usuario_actor=user,
                accion='Edición de Comunicado',
                detalle=f"Se editó el comunicado ID {comunicado.id}: {titulo}"
            )
            
            return redirect('dashboard')
            
    return render(request, 'editar_comunicado.html', {'comunicado': comunicado})

@login_required(login_url='login')
def eliminar_comunicado_view(request, comunicado_id):
    """
    Vista para eliminar un comunicado.
    - Director/Subdirección pueden eliminar cualquier comunicado
    - Jefes de Unidad solo pueden eliminar sus propios comunicados
    """
    comunicado = get_object_or_404(Comunicados, pk=comunicado_id)
    user = request.user
    
    # Verificar permisos: Subdirección o autor del comunicado
    if not (es_subdireccion(user) or comunicado.id_autor == user):
        return redirect('dashboard')
    
    # Registrar en Logs antes de borrar
    Logs_Auditoria.objects.create(
        id_usuario_actor=user,
        accion='Eliminación de Comunicado',
        detalle=f"Se eliminó el comunicado: {comunicado.titulo}"
    )
    
    comunicado.delete()
    return redirect('dashboard')


# =============================================================================
# GESTIÓN DE USUARIOS (RRHH)
# =============================================================================

@login_required(login_url='login')
def gestion_usuarios_view(request):
    """
    Vista para gestionar usuarios del sistema.
    Solo accesible para Director, Subdirección y Encargado RRHH (nivel <= 2).
    """
    user = request.user
    
    if not es_subdireccion(user):
        return redirect('dashboard')
    
    # Obtener todos los funcionarios (excepto superusuarios)
    funcionarios = Funcionarios.objects.filter(is_superuser=False).select_related('id_rol', 'id_unidad').order_by('id_unidad__nombre_unidad', 'last_name')
    unidades = Unidades.objects.filter(activa=True).order_by('nombre_unidad')
    roles = Roles.objects.all().order_by('nivel_jerarquico')
    
    context = {
        'funcionarios': funcionarios,
        'unidades': unidades,
        'roles': roles,
    }
    return render(request, 'gestion_usuarios.html', context)


@login_required(login_url='login')
def crear_usuario_view(request):
    """
    Vista para crear un nuevo usuario.
    Solo accesible para Director, Subdirección y Encargado RRHH.
    """
    user = request.user
    
    if not es_subdireccion(user):
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email', '')
        id_rol_id = request.POST.get('id_rol')
        id_unidad_id = request.POST.get('id_unidad')
        es_jefe = request.POST.get('es_jefe_unidad') == 'on'
        
        if username and password and first_name and last_name:
            # Verificar que el username no exista
            if Funcionarios.objects.filter(username=username).exists():
                return render(request, 'crear_usuario.html', {
                    'error': 'El nombre de usuario ya existe',
                    'unidades': Unidades.objects.filter(activa=True),
                    'roles': Roles.objects.all().order_by('nivel_jerarquico'),
                })
            
            # Crear usuario
            nuevo_usuario = Funcionarios.objects.create_user(
                username=username,
                password=password,
                first_name=first_name,
                last_name=last_name,
                email=email,
                id_rol_id=id_rol_id if id_rol_id else None,
                id_unidad_id=id_unidad_id if id_unidad_id else None,
                es_jefe_unidad=es_jefe,
                is_staff=es_jefe,  # Los jefes tienen is_staff
            )
            
            # Crear registro de días administrativos
            Dias_Administrativos.objects.create(id_funcionario=nuevo_usuario)
            
            # Registrar en logs
            Logs_Auditoria.objects.create(
                id_usuario_actor=user,
                accion='Creación de Usuario',
                detalle=f"Se creó el usuario: {username} ({first_name} {last_name}) - Unidad: {nuevo_usuario.id_unidad}"
            )
            
            return redirect('gestion_usuarios')
    
    context = {
        'unidades': Unidades.objects.filter(activa=True).order_by('nombre_unidad'),
        'roles': Roles.objects.all().order_by('nivel_jerarquico'),
    }
    return render(request, 'crear_usuario.html', context)


@login_required(login_url='login')
def editar_usuario_view(request, usuario_id):
    """
    Vista para editar un usuario existente.
    """
    user = request.user
    
    if not es_subdireccion(user):
        return redirect('dashboard')
    
    usuario = get_object_or_404(Funcionarios, pk=usuario_id)
    
    # No permitir editar superusuarios
    if usuario.is_superuser:
        return redirect('gestion_usuarios')
    
    if request.method == 'POST':
        usuario.first_name = request.POST.get('first_name', usuario.first_name)
        usuario.last_name = request.POST.get('last_name', usuario.last_name)
        usuario.email = request.POST.get('email', usuario.email)
        
        id_rol_id = request.POST.get('id_rol')
        id_unidad_id = request.POST.get('id_unidad')
        es_jefe = request.POST.get('es_jefe_unidad') == 'on'
        
        usuario.id_rol_id = id_rol_id if id_rol_id else None
        usuario.id_unidad_id = id_unidad_id if id_unidad_id else None
        usuario.es_jefe_unidad = es_jefe
        usuario.is_staff = es_jefe or (usuario.id_rol and usuario.id_rol.nivel_jerarquico <= 2)
        
        # Cambiar contraseña si se proporciona
        nueva_password = request.POST.get('password')
        if nueva_password:
            usuario.set_password(nueva_password)
        
        usuario.save()
        
        # Registrar en logs
        Logs_Auditoria.objects.create(
            id_usuario_actor=user,
            accion='Edición de Usuario',
            detalle=f"Se editó el usuario: {usuario.username}"
        )
        
        return redirect('gestion_usuarios')
    
    context = {
        'usuario': usuario,
        'unidades': Unidades.objects.filter(activa=True).order_by('nombre_unidad'),
        'roles': Roles.objects.all().order_by('nivel_jerarquico'),
    }
    return render(request, 'editar_usuario.html', context)


@login_required(login_url='login')
def desactivar_usuario_view(request, usuario_id):
    """
    Vista para desactivar (no eliminar) un usuario.
    """
    user = request.user
    
    if not es_subdireccion(user):
        return redirect('dashboard')
    
    usuario = get_object_or_404(Funcionarios, pk=usuario_id)
    
    # No permitir desactivar superusuarios ni a uno mismo
    if usuario.is_superuser or usuario == user:
        return redirect('gestion_usuarios')
    
    usuario.is_active = not usuario.is_active  # Toggle
    usuario.save()
    
    estado = "activado" if usuario.is_active else "desactivado"
    Logs_Auditoria.objects.create(
        id_usuario_actor=user,
        accion=f'Usuario {estado.capitalize()}',
        detalle=f"Se {estado} el usuario: {usuario.username}"
    )
    
    return redirect('gestion_usuarios')