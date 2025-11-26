import os
import django
from django.utils import timezone
from datetime import timedelta

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cesfam_backend.settings')
django.setup()

from intranet.models import Funcionarios, Logs_Auditoria

def analizar_usuarios():
    print("--- Análisis Detallado de Usuarios Activos ---")
    
    one_week_ago = timezone.now() - timedelta(days=7)
    
    users = Funcionarios.objects.all()
    
    print(f"{'ID':<5} {'Username':<30} {'Último Login':<20} {'Activo?'}")
    print("-" * 70)

    for user in users:
        last_login = user.last_login
        has_recent_login = last_login and last_login >= one_week_ago
        
        logs_count = Logs_Auditoria.objects.filter(
            id_usuario_actor=user, 
            fecha_hora__gte=one_week_ago
        ).count()
        has_recent_logs = logs_count > 0

        is_active = has_recent_login or has_recent_logs
        status = "SÍ" if is_active else "NO"
        last_login_str = last_login.strftime('%Y-%m-%d') if last_login else "Nunca"
        
        print(f"{user.id:<5} {user.username:<30} {last_login_str:<20} {status}")

    print("-" * 70)
    print(f"Total en BD: {users.count()}")

if __name__ == "__main__":
    analizar_usuarios()
