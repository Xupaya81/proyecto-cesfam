from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import os

# --- MODELOS BASADOS EN TU INFORME (Cesfam PRINTEGRADO (1).docx) ---

# Tabla: Roles
class Roles(models.Model):
    """
    Modelo que define los roles de usuario en el sistema (Ej: Administrador, Funcionario, Subdirección).
    Se utiliza para gestionar permisos y accesos en las vistas.
    """
    nombre_rol = models.CharField(max_length=100, unique=True)
    
    def __str__(self):
        return self.nombre_rol

# 2.Tabla: Funcionarios
class Funcionarios(AbstractUser):
    """
    Modelo de usuario personalizado que extiende de AbstractUser de Django.
    Incluye la relación con el rol y campos adicionales si fueran necesarios.
    """
    # 'email', 'username', 'password' ya vienen en AbstractUser.
    nombre = models.CharField(max_length=100, blank=True)
    id_rol = models.ForeignKey(Roles, on_delete=models.SET_NULL, null=True, blank=True)

# 3. Tabla: Dias_Administrativos
class Dias_Administrativos(models.Model):
    """
    Almacena el saldo de días administrativos y vacaciones disponibles para cada funcionario.
    Relación 1 a 1 con el modelo Funcionarios.
    """
    # OneToOneField asegura que solo haya UN registro por funcionario
    id_funcionario = models.OneToOneField(Funcionarios, on_delete=models.CASCADE, primary_key=True)
    vacaciones_restantes = models.IntegerField(default=20)
    admin_restantes = models.IntegerField(default=5)

# 4. Tabla: Documentos
class Documentos(models.Model):
    """
    Modelo para el Repositorio Documental.
    Permite subir archivos, categorizarlos y gestionar su visibilidad (Público/Privado/Por Rol).
    """
    titulo = models.CharField(max_length=255)
    categoria = models.CharField(max_length=100, blank=True, null=True)
    # FileField es clave: Django manejará la subida de archivos (PDF, Word)
    ruta_archivo = models.FileField(upload_to='documentos/') 
    fecha_carga = models.DateTimeField(auto_now_add=True)
    # [cite_start]Registra QUIÉN subió el documento [cite: 232]
    id_autor_carga = models.ForeignKey(Funcionarios, on_delete=models.SET_NULL, null=True, blank=True)
    # Privacidad: Si es True, todos lo ven. Si es False, solo el autor.
    publico = models.BooleanField(default=False, verbose_name="Es Público")
    # Compartir con roles específicos
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
    """
    titulo = models.CharField(max_length=255)
    cuerpo = models.TextField()
    fecha_publicacion = models.DateTimeField(auto_now_add=True)
    # [cite_start]Registra QUIÉN publicó el comunicado [cite: 224]
    id_autor = models.ForeignKey(Funcionarios, on_delete=models.SET_NULL, null=True)

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
    Modelo para gestionar las solicitudes de días administrativos o vacaciones.
    Incluye estado (Pendiente, Aprobado, Rechazado) y archivo justificativo.
    """
    # Este modelo registra la solicitud que el funcionario envía (HU4)
    id_funcionario_solicitante = models.ForeignKey(Funcionarios, on_delete=models.CASCADE, related_name='solicitudes_enviadas')
    tipo_permiso = models.CharField(max_length=50) # 'vacaciones', 'administrativo', 'otro'
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    dias_solicitados = models.IntegerField(default=0)
    justificativo_archivo = models.FileField(upload_to='solicitudes/', null=True, blank=True)
    fecha_solicitud = models.DateTimeField(default=timezone.now)
    estado = models.CharField(max_length=50, default='Pendiente') # 'Pendiente', 'Aprobado', 'Rechazado'
    
    def __str__(self):
        return f"Solicitud de {self.id_funcionario_solicitante.username} ({self.estado})"

    class Meta:
        verbose_name_plural = "Solicitudes de Permiso"