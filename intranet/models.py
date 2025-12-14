from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import os

# --- MODELOS BASADOS EN TU INFORME (Cesfam PRINTEGRADO (1).docx) ---

# Tabla: Roles
class Roles(models.Model):
    """
    Modelo que define los roles de usuario en el sistema.
    Roles: Director General, Subdirección, Jefe de Unidad, Administrativo, Funcionario Base.
    """
    nombre_rol = models.CharField(max_length=100, unique=True)
    # Nivel jerárquico: 1=Director (más alto), 5=Funcionario Base (más bajo)
    nivel_jerarquico = models.IntegerField(default=5)
    
    def __str__(self):
        return self.nombre_rol
    
    class Meta:
        verbose_name_plural = "Roles"


# Tabla: Unidades (Departamentos del CESFAM)
class Unidades(models.Model):
    """
    Modelo que define las unidades/departamentos del CESFAM.
    Ej: Medicina General, Odontología, Kinesiología, SOME, etc.
    """
    nombre_unidad = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    activa = models.BooleanField(default=True)
    
    def __str__(self):
        return self.nombre_unidad
    
    class Meta:
        verbose_name_plural = "Unidades"


# 2.Tabla: Funcionarios
class Funcionarios(AbstractUser):
    """
    Modelo de usuario personalizado que extiende de AbstractUser de Django.
    Incluye la relación con el rol, unidad y campo de jefatura.
    """
    # 'email', 'username', 'password' ya vienen en AbstractUser.
    nombre = models.CharField(max_length=100, blank=True)
    id_rol = models.ForeignKey(Roles, on_delete=models.SET_NULL, null=True, blank=True)
    # Nueva relación con Unidad/Departamento
    id_unidad = models.ForeignKey(Unidades, on_delete=models.SET_NULL, null=True, blank=True)
    # Indica si es jefe de su unidad (puede pre-aprobar solicitudes de su equipo)
    es_jefe_unidad = models.BooleanField(default=False, verbose_name="Es Jefe de Unidad")

# 3. Tabla: Dias_Administrativos (Saldos de permisos)
class Dias_Administrativos(models.Model):
    """
    Almacena el saldo de días/horas disponibles para cada funcionario.
    Incluye: vacaciones, días administrativos, horas de compensación.
    Relación 1 a 1 con el modelo Funcionarios.
    """
    # OneToOneField asegura que solo haya UN registro por funcionario
    id_funcionario = models.OneToOneField(Funcionarios, on_delete=models.CASCADE, primary_key=True)
    # Vacaciones legales: 15 días base (aumenta con antigüedad)
    vacaciones_restantes = models.IntegerField(default=15, verbose_name="Vacaciones restantes")
    # Días administrativos: 6 por año según estatuto
    admin_restantes = models.IntegerField(default=6, verbose_name="Días administrativos")
    # Horas de compensación acumuladas (para trabajar horas extra)
    horas_compensacion = models.IntegerField(default=0, verbose_name="Horas compensación")
    # Año del saldo (para resetear anualmente si se desea)
    anio_saldo = models.IntegerField(default=2025, verbose_name="Año del saldo")

# 4. Tabla: Documentos
class Documentos(models.Model):
    """
    Modelo para el Repositorio Documental.
    Permite subir archivos con visibilidad inteligente según jerarquía.
    """
    titulo = models.CharField(max_length=255)
    categoria = models.CharField(max_length=100, blank=True, null=True)
    ruta_archivo = models.FileField(upload_to='documentos/') 
    fecha_carga = models.DateTimeField(auto_now_add=True)
    id_autor_carga = models.ForeignKey(Funcionarios, on_delete=models.SET_NULL, null=True, blank=True)
    
    # === NUEVA LÓGICA DE VISIBILIDAD ===
    # Privacidad base
    publico = models.BooleanField(default=False, verbose_name="Visible para todos")
    
    # Compartir con mi unidad
    compartir_unidad = models.BooleanField(default=False, verbose_name="Compartir con mi unidad")
    
    # Compartir con otros jefes (solo aplica si el autor es Jefe de Unidad)
    compartir_jefes = models.BooleanField(default=False, verbose_name="Compartir con otros Jefes")
    
    # Compartir con superiores (Subdirección/Dirección)
    compartir_superiores = models.BooleanField(default=False, verbose_name="Compartir con superiores")
    
    # Compartir con unidad específica (para Subdirección)
    unidad_destino = models.ForeignKey('Unidades', on_delete=models.SET_NULL, null=True, blank=True, 
                                        verbose_name="Unidad destino específica")
    
    # Campo legacy para compatibilidad (se puede eliminar después)
    roles_permitidos = models.ManyToManyField(Roles, blank=True, related_name='documentos_visibles')

    def get_extension(self):
        """Retorna la extensión del archivo (ej: .pdf, .docx)"""
        name, extension = os.path.splitext(self.ruta_archivo.name)
        return extension.lower()

    def get_icon(self):
        """Retorna la clase de FontAwesome correspondiente al tipo de archivo"""
        ext = self.get_extension()
        if ext in ['.pdf']:
            return 'fas fa-file-pdf text-danger'
        elif ext in ['.doc', '.docx']:
            return 'fas fa-file-word text-primary'
        elif ext in ['.xls', '.xlsx']:
            return 'fas fa-file-excel text-success'
        elif ext in ['.ppt', '.pptx']:
            return 'fas fa-file-powerpoint text-warning'
        elif ext in ['.jpg', '.jpeg', '.png', '.gif']:
            return 'fas fa-file-image text-info'
        elif ext in ['.zip', '.rar']:
            return 'fas fa-file-archive text-secondary'
        elif ext in ['.txt']:
            return 'fas fa-file-alt text-dark'
        else:
            return 'fas fa-file text-secondary'

# 5. Tabla: Comunicados 
class Comunicados(models.Model):
    """
    Modelo para noticias o anuncios importantes que aparecen en el Dashboard.
    - Si unidad_destino es NULL → Comunicado global (para todos)
    - Si unidad_destino tiene valor → Solo visible para esa unidad
    """
    titulo = models.CharField(max_length=255)
    cuerpo = models.TextField()
    fecha_publicacion = models.DateTimeField(auto_now_add=True)
    # Registra QUIÉN publicó el comunicado
    id_autor = models.ForeignKey(Funcionarios, on_delete=models.SET_NULL, null=True)
    # Nueva: Unidad destino (NULL = global, con valor = solo esa unidad)
    unidad_destino = models.ForeignKey(
        Unidades, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='comunicados_unidad',
        verbose_name="Unidad destino (vacío = todos)"
    )
    
    def es_global(self):
        """Retorna True si el comunicado es para toda la comunidad"""
        return self.unidad_destino is None
    
    def __str__(self):
        destino = "Global" if self.es_global() else self.unidad_destino.nombre_unidad
        return f"{self.titulo} ({destino})"

# [cite_start]6. Tabla: Eventos_Calendario (Soporta RF7, RF8) [cite: 216, 226, 227]
# Para reuniones, capacitaciones, feriados
class Eventos_Calendario(models.Model):
    """
    Modelo para gestionar eventos en el calendario institucional.
    """
    # Ya que el formulario HTML solo pide la fecha, usamos DateField para evitar errores de hora
    titulo = models.CharField(max_length=200)
    fecha_inicio = models.DateField() 
    fecha_fin = models.DateField(null=True, blank=True)
    tipo_evento = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.titulo} ({self.fecha_inicio})"

    class Meta:
        # Esto es necesario porque tu tabla ya existe con guiones bajos en el nombre
        db_table = 'intranet_eventos_calendario' 
        verbose_name_plural = "Eventos del Calendario"

# [cite_start]7. Tabla: Logs_Auditoria (Soporta RF18) [cite: 237]
# Almacena los cambios de roles y accesos
class Logs_Auditoria(models.Model):
    """
    Registro de auditoría para acciones críticas (ej: cambios de rol, eliminación de comunicados).
    """
    fecha_hora = models.DateTimeField(auto_now_add=True)
    id_usuario_actor = models.ForeignKey(Funcionarios, on_delete=models.SET_NULL, null=True, blank=True)
    accion = models.CharField(max_length=255)
    detalle = models.TextField(blank=True, null=True)

# --- MODELO BASADO EN EL "DOCUMENTO MAESTRO" (Requisito Extra) ---

# [cite_start]8. Tabla: Licencias (Requisito "Documento Maestro") [cite: 53-54]
# Flujo de Subdirección para ingresar licencias
class Licencias(models.Model):
    """
    Modelo para registrar licencias médicas ingresadas por Subdirección.
    """
    # El funcionario al que pertenece la licencia
    id_funcionario = models.ForeignKey(Funcionarios, on_delete=models.CASCADE, related_name='licencias_recibidas')
    # El funcionario (Subdirección) que cargó la licencia
    id_subdireccion_carga = models.ForeignKey(Funcionarios, on_delete=models.SET_NULL, null=True, related_name='licencias_cargadas')
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    ruta_foto_licencia = models.FileField(upload_to='licencias/')
    fecha_registro = models.DateTimeField(auto_now_add=True)

class SolicitudesPermiso(models.Model):
    """
    Modelo para gestionar las solicitudes de permisos funcionarios CESFAM.
    Flujo: Pendiente → Pre-Aprobado (Jefe Unidad) → Aprobado (Subdirección) o Rechazado.
    """
    
    # Tipos de permiso basados en la realidad de un CESFAM chileno
    TIPOS_PERMISO = [
        ('administrativo', 'Día Administrativo'),
        ('vacaciones', 'Feriado Legal (Vacaciones)'),
        ('sin_goce', 'Permiso sin Goce de Sueldo'),
        ('hora_medica', 'Hora Médica'),
        ('licencia', 'Licencia Médica'),
        ('duelo', 'Permiso por Duelo Familiar'),
        ('compensacion', 'Compensación de Horas'),
    ]
    
    ESTADOS = [
        ('Pendiente', 'Pendiente'),
        ('Pre-Aprobado', 'Pre-Aprobado'),
        ('Aprobado', 'Aprobado'),
        ('Rechazado', 'Rechazado'),
    ]
    
    # Funcionario que solicita
    id_funcionario_solicitante = models.ForeignKey(Funcionarios, on_delete=models.CASCADE, related_name='solicitudes_enviadas')
    tipo_permiso = models.CharField(max_length=50, choices=TIPOS_PERMISO)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    dias_solicitados = models.IntegerField(default=0)
    # Para hora médica: cantidad de horas (1-4)
    horas_solicitadas = models.IntegerField(default=0, blank=True)
    justificativo_archivo = models.FileField(upload_to='solicitudes/', null=True, blank=True)
    fecha_solicitud = models.DateTimeField(default=timezone.now)
    estado = models.CharField(max_length=50, choices=ESTADOS, default='Pendiente')
    # Observaciones adicionales del solicitante
    observaciones = models.TextField(blank=True, null=True, verbose_name="Observaciones")
    
    # Campos para el flujo de aprobación por niveles
    pre_aprobado_por = models.ForeignKey(
        Funcionarios, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='solicitudes_pre_aprobadas',
        verbose_name="Pre-aprobado por (Jefe Unidad)"
    )
    fecha_pre_aprobacion = models.DateTimeField(null=True, blank=True)
    aprobado_por = models.ForeignKey(
        Funcionarios, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='solicitudes_aprobadas_final',
        verbose_name="Aprobado por (Subdirección)"
    )
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    comentario_rechazo = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"Solicitud de {self.id_funcionario_solicitante.username} ({self.estado})"

    class Meta:
        verbose_name_plural = "Solicitudes de Permiso"