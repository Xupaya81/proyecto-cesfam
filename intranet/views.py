from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.hashers import check_password
from .models import Funcionarios, Dias_Administrativos, Comunicados, Documentos, Logs_Auditoria, Licencias, Roles, Logs_Auditoria, Eventos_Calendario, SolicitudesPermiso, Licencias
from django.db.models import Sum, F, Q
from django.utils import timezone
from datetime import datetime
from .forms import DiasAdministrativosForm
from django.http import JsonResponse, HttpResponse
import openpyxl
from django.contrib.auth.forms import AuthenticationForm

# --- Funciones de Ayuda (para proteger vistas) ---

def es_admin(user):
    """
    Verifica si el usuario es superusuario (Administrador).
    
    Args:
        user (User): El usuario a verificar.
        
    Returns:
        bool: True si es superusuario, False en caso contrario.
    """
    return user.is_superuser

def es_subdireccion(user):
    """
    Verifica si el usuario pertenece a Subdirección o es Administrador.
    Se utiliza para restringir el acceso a vistas de gestión.
    
    Args:
        user (User): El usuario a verificar.
        
    Returns:
        bool: True si es staff (Subdirección) o superusuario, False en caso contrario.
    """
    return user.is_staff or user.is_superuser

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
    Vista principal del Dashboard.
    Muestra información relevante para el usuario, como días administrativos restantes,
    vacaciones disponibles y los últimos comunicados.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza la plantilla 'dashboard.html' con el contexto.
    """
    # 1. Obtener Días Administrativos (Crear si no existen)
    try:
        dias = Dias_Administrativos.objects.get(id_funcionario=request.user)
    except Dias_Administrativos.DoesNotExist:
        # Crear un registro inicial si no existe
        dias = Dias_Administrativos.objects.create(id_funcionario=request.user)

    # 2. Obtener los últimos 3 Comunicados
    comunicados = Comunicados.objects.all().order_by('-fecha_publicacion')[:3]

    # 3. Enviar datos al HTML
    context = {
        'dias_admin': dias.admin_restantes,
        'dias_vacas': dias.vacaciones_restantes,
        'comunicados': comunicados
    }
    # La misma plantilla (dashboard.html) se usa, y el menú se adapta por user.is_staff
    return render(request, 'dashboard.html', context)

@login_required(login_url='login')
def documentos_view(request):
    """
    Vista para el Repositorio Documental.
    Permite listar, filtrar y subir documentos.
    Implementa lógica de visibilidad: Privado, Público y Compartido por Roles.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza 'documentos.html' con la lista de documentos y roles.
    """
    # Manejo de subida de documentos
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        categoria = request.POST.get('categoria')
        archivo = request.FILES.get('archivo')
        
        # Lógica de visibilidad
        visibilidad = request.POST.get('visibilidad') # 'privado', 'publico', 'roles'
        es_publico = (visibilidad == 'publico')
        roles_seleccionados = request.POST.getlist('roles_ids') # Lista de IDs

        if titulo and archivo:
            doc = Documentos.objects.create(
                titulo=titulo,
                categoria=categoria,
                ruta_archivo=archivo,
                id_autor_carga=request.user,
                publico=es_publico
            )
            
            # Si eligió compartir con roles específicos
            if visibilidad == 'roles' and roles_seleccionados:
                doc.roles_permitidos.set(roles_seleccionados)
                
            return redirect('documentos')

    # Obtener documentos: Públicos O Propios O Compartidos con mi Rol
    query = request.GET.get('q')
    
    # Filtro base: 
    # 1. Documentos Públicos
    # 2. Documentos que YO subí
    # 3. Documentos compartidos con MI ROL
    base_filter = Q(publico=True) | Q(id_autor_carga=request.user)
    
    if request.user.id_rol:
        base_filter = base_filter | Q(roles_permitidos=request.user.id_rol)
    
    if query:
        docs = Documentos.objects.filter(base_filter, titulo__icontains=query).distinct().order_by('-fecha_carga')
    else:
        docs = Documentos.objects.filter(base_filter).distinct().order_by('-fecha_carga')
    
    # Obtener roles para el formulario de carga
    roles_disponibles = Roles.objects.all()
        
    return render(request, 'documentos.html', {
        'documentos': docs,
        'roles': roles_disponibles
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
    Vista para que el Funcionario envíe solicitudes de días administrativos, vacaciones o licencias.
    Calcula automáticamente la cantidad de días solicitados.
    La aprobación posterior se gestiona en la vista de RRHH/Subdirección.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza el formulario o redirige al historial tras éxito.
    """
    if request.method == 'POST':
        # 1. Obtener los datos del formulario
        tipo = request.POST.get('tipo_permiso')
        inicio_str = request.POST.get('fecha_inicio')
        fin_str = request.POST.get('fecha_fin')
        archivo = request.FILES.get('justificativo_archivo') # Obtener archivo si existe
        
        try:
            # Convertir strings a objetos date
            fecha_inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fin_str, '%Y-%m-%d').date()

            # Validar fechas
            if fecha_fin < fecha_inicio:
                return render(request, 'gestion_solicitudes.html', {'error': 'La fecha de término no puede ser anterior a la de inicio.'})

            # 2. Calcular los días solicitados (diferencia de fechas)
            diferencia = fecha_fin - fecha_inicio
            dias_solicitados = diferencia.days + 1 # +1 para incluir el día de inicio
            
            # 3. Guardar la solicitud en la base de datos
            SolicitudesPermiso.objects.create(
                id_funcionario_solicitante=request.user, # El usuario logueado
                tipo_permiso=tipo,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                dias_solicitados=dias_solicitados,
                justificativo_archivo=archivo, # Guardar el archivo
                estado='Pendiente'
            )
            
            # 4. Redirigir al historial para ver la solicitud creada
            return redirect('historial_personal')
            
        except ValueError:
             return render(request, 'gestion_solicitudes.html', {'error': 'Formato de fecha inválido.'})

    # Renderiza el formulario de solicitud
    return render(request, 'gestion_solicitudes.html')

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

@user_passes_test(es_subdireccion, login_url='login')
def gestion_dias_view(request):
    """
    Vista para gestionar los días administrativos y vacaciones de los funcionarios.
    Permite a la Subdirección ver y modificar los saldos de días.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza la tabla de funcionarios y el formulario de edición.
    """
    # Obtenemos funcionarios y preparamos datos para el frontend
    funcionarios_qs = Funcionarios.objects.all().order_by('username')
    funcionarios_data = []
    
    for f in funcionarios_qs:
        # Intentamos obtener sus días, si no existe, asumimos valores por defecto (o 0)
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
            'admin': admin
        })

    # 1. Lógica de PROCESAMIENTO (POST)
    if request.method == 'POST':
        funcionario_id = request.POST.get('funcionario_id')
        
        # Buscamos o creamos el registro de días
        dias_obj, created = Dias_Administrativos.objects.get_or_create(
            id_funcionario=get_object_or_404(Funcionarios, pk=funcionario_id)
        )
        
        # Le pasamos los datos del formulario (request.POST) al Formulario de Django
        form = DiasAdministrativosForm(request.POST, instance=dias_obj)

        if form.is_valid():
            # Django hace el casteo y la validación. Solo guardamos.
            form.save()
            return redirect('gestion_dias') # Redirigir a la misma página para seguir editando
        
        # Si no es válido, se sigue mostrando el formulario con errores (no implementado en este prototipo)
    
    # 2. Lógica de CARGA DE PÁGINA (GET)
    # Creamos un formulario vacío para el primer funcionario (por defecto)
    form = DiasAdministrativosForm() 
    
    context = {
        'funcionarios': funcionarios_data, # Pasamos la lista procesada
        'form': form 
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

@user_passes_test(es_subdireccion, login_url='login')
def reporte_licencias_view(request):
    """
    Vista para listar todas las licencias registradas (Lectura funcional).
    Muestra un historial completo de licencias médicas.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza 'reporte_licencias.html'.
    """
    # 1. Se obtienen todas las licencias de la base de datos
    licencias = Licencias.objects.all().order_by('-fecha_registro')
    
    context = {
        'licencias': licencias,
        # 2. Eliminamos la línea que causaba el FieldError. 
        #    La suma de días es un cálculo complejo que haremos después si sobra tiempo.
        'dias_totales': 0 
    }
    return render(request, 'reporte_licencias.html', context)

# intranet/views.py

@user_passes_test(es_subdireccion, login_url='login')
def reporte_solicitudes_view(request):
    """
    Vista para que la Subdirección revise las solicitudes de permiso (solo lectura).
    Muestra las solicitudes pendientes de aprobación.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza 'reporte_solicitudes.html'.
    """
    # Obtenemos todas las solicitudes que están en estado 'Pendiente'
    solicitudes = SolicitudesPermiso.objects.filter(estado='Pendiente').order_by('-fecha_solicitud')
    
    context = {
        'solicitudes': solicitudes
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

@user_passes_test(es_subdireccion, login_url='login')
def aprobar_solicitud_view(request, solicitud_id):
    """
    Procesa la aprobación de una solicitud.
    Si es licencia, crea el registro correspondiente.
    Si son vacaciones o días administrativos, descuenta del balance del funcionario.
    
    Args:
        request (HttpRequest): La petición HTTP.
        solicitud_id (int): ID de la solicitud a aprobar.
        
    Returns:
        HttpResponse: Redirección al reporte de solicitudes.
    """
    if request.method == 'POST':
        # 1. Obtener la solicitud
        solicitud = get_object_or_404(SolicitudesPermiso, pk=solicitud_id)
        
        if solicitud.estado == 'Pendiente':
            
            # --- 2. Lógica para Licencia Médica (Crea un registro, no descuenta días) ---
            if solicitud.tipo_permiso == 'licencia':
                
                # 2.1. Crear el registro en la tabla Licencias (historial)
                Licencias.objects.create(
                    id_funcionario=solicitud.id_funcionario_solicitante,
                    id_subdireccion_carga=request.user, # Subdirector que aprueba
                    fecha_inicio=solicitud.fecha_inicio,
                    fecha_fin=solicitud.fecha_fin,
                    # El archivo subido en el formulario de solicitud se traslada aquí
                    ruta_foto_licencia=solicitud.justificativo_archivo 
                )
                
            # --- 3. Lógica para Días/Vacaciones (Descuenta del balance) ---
            elif solicitud.tipo_permiso in ['vacaciones', 'administrativo']:
                
                # 3.1. Determinar qué campo del balance actualizar
                if solicitud.tipo_permiso == 'vacaciones':
                    campo_balance = 'vacaciones_restantes'
                else:
                    campo_balance = 'admin_restantes'
                    
                # 3.2. ACTUALIZACIÓN ATÓMICA del balance
                Dias_Administrativos.objects.filter(id_funcionario=solicitud.id_funcionario_solicitante).update(
                    **{campo_balance: F(campo_balance) - solicitud.dias_solicitados}
                )

            # 4. Marcar la solicitud como aprobada
            solicitud.estado = 'Aprobado'
            solicitud.save()

    return redirect('reporte_solicitudes')

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
    # 1. Solicitudes de permiso: propias del usuario logueado
    solicitudes = SolicitudesPermiso.objects.filter(id_funcionario_solicitante=request.user).order_by('-fecha_solicitud')
    
    # 2. Historial de licencias: licencias emitidas a este funcionario
    licencias_recibidas = Licencias.objects.filter(id_funcionario=request.user).order_by('-fecha_inicio')
    
    context = {
        'solicitudes': solicitudes,
        'licencias_recibidas': licencias_recibidas,
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

@user_passes_test(es_subdireccion, login_url='login')
def crear_comunicado_view(request):
    """
    Vista para que Subdirección o Admin creen nuevos comunicados.
    Registra la acción en los logs de auditoría.
    
    Args:
        request (HttpRequest): La petición HTTP.
        
    Returns:
        HttpResponse: Renderiza el formulario o redirige al dashboard.
    """
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        cuerpo = request.POST.get('cuerpo')
        
        if titulo and cuerpo:
            Comunicados.objects.create(
                titulo=titulo,
                cuerpo=cuerpo,
                id_autor=request.user
            )
            
            # Registrar en Logs (RF18)
            Logs_Auditoria.objects.create(
                id_usuario_actor=request.user,
                accion='Creación de Comunicado',
                detalle=f"Se publicó el comunicado: {titulo}"
            )
            
            return redirect('dashboard')
            
    return render(request, 'crear_comunicado.html')

@user_passes_test(es_subdireccion, login_url='login')
def editar_comunicado_view(request, comunicado_id):
    """
    Vista para editar un comunicado existente.
    Permite modificar título y cuerpo, registrando el cambio en logs.
    
    Args:
        request (HttpRequest): La petición HTTP.
        comunicado_id (int): ID del comunicado a editar.
        
    Returns:
        HttpResponse: Renderiza el formulario de edición o redirige al dashboard.
    """
    comunicado = get_object_or_404(Comunicados, pk=comunicado_id)
    
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        cuerpo = request.POST.get('cuerpo')
        
        if titulo and cuerpo:
            comunicado.titulo = titulo
            comunicado.cuerpo = cuerpo
            comunicado.save()
            
            # Registrar en Logs
            Logs_Auditoria.objects.create(
                id_usuario_actor=request.user,
                accion='Edición de Comunicado',
                detalle=f"Se editó el comunicado ID {comunicado.id}: {titulo}"
            )
            
            return redirect('dashboard')
            
    return render(request, 'editar_comunicado.html', {'comunicado': comunicado})

@user_passes_test(es_subdireccion, login_url='login')
def eliminar_comunicado_view(request, comunicado_id):
    """
    Vista para eliminar un comunicado.
    Borra el comunicado y registra la acción en los logs.
    
    Args:
        request (HttpRequest): La petición HTTP.
        comunicado_id (int): ID del comunicado a eliminar.
        
    Returns:
        HttpResponse: Redirección al dashboard.
    """
    comunicado = get_object_or_404(Comunicados, pk=comunicado_id)
    
    # Registrar en Logs antes de borrar
    Logs_Auditoria.objects.create(
        id_usuario_actor=request.user,
        accion='Eliminación de Comunicado',
        detalle=f"Se eliminó el comunicado: {comunicado.titulo}"
    )
    
    comunicado.delete()
    return redirect('dashboard')