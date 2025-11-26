import os
import django
import time
from django.utils import timezone
from datetime import timedelta

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cesfam_backend.settings')
django.setup()

from intranet.models import Documentos, Funcionarios, Logs_Auditoria
from django.db import connection

def medir_tiempo_busqueda():
    print("--- Midiendo Tiempo de Búsqueda de Documentos ---")
    start_time = time.time()
    # Simula una búsqueda típica
    docs = list(Documentos.objects.filter(titulo__icontains='a'))
    end_time = time.time()
    duration = end_time - start_time
    print(f"Documentos encontrados: {len(docs)}")
    print(f"Tiempo de ejecución: {duration:.6f} segundos")
    if duration < 2.0:
        print("Resultado: CUMPLE (< 2 segundos)")
    else:
        print("Resultado: NO CUMPLE (> 2 segundos)")
    return duration

def medir_tasa_adopcion():
    print("\n--- Midiendo Tasa de Adopción (Semanal) ---")
    total_funcionarios = Funcionarios.objects.filter(is_active=True).count()
    if total_funcionarios == 0:
        print("No hay funcionarios activos registrados.")
        return 0

    one_week_ago = timezone.now() - timedelta(days=7)
    # Usuarios que han hecho login en la última semana
    active_users = Funcionarios.objects.filter(last_login__gte=one_week_ago).count()
    
    # Alternativa: Usuarios que han generado logs en la última semana
    active_users_logs = Logs_Auditoria.objects.filter(fecha_hora__gte=one_week_ago).values('id_usuario_actor').distinct().count()
    
    # Usamos el mayor de los dos para ser más justos
    real_active = max(active_users, active_users_logs)
    
    rate = (real_active / total_funcionarios) * 100
    print(f"Total Funcionarios: {total_funcionarios}")
    print(f"Usuarios Activos (últimos 7 días): {real_active}")
    print(f"Tasa de Adopción: {rate:.2f}%")
    return rate

def verificar_disponibilidad():
    print("\n--- Verificando Disponibilidad del Sistema (Simulado) ---")
    try:
        connection.ensure_connection()
        print("Conexión a Base de Datos: OK")
        print("Estado del Sistema: OPERATIVO")
        print("Disponibilidad Actual: 100% (En este momento)")
        print("Nota: Para medir el 99% mensual real, se requiere un servicio de monitoreo externo (ej: UptimeRobot).")
    except Exception as e:
        print(f"Error de conexión: {e}")
        print("Estado del Sistema: CAÍDO")

if __name__ == "__main__":
    medir_tiempo_busqueda()
    medir_tasa_adopcion()
    verificar_disponibilidad()
