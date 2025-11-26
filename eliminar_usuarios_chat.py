import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cesfam_backend.settings')
django.setup()

from intranet.models import Funcionarios

def eliminar_usuarios_chat():
    usernames_to_delete = ['admin_chat', 'subdireccion_chat', 'funcionario_chat']
    print(f"--- Eliminando usuarios: {', '.join(usernames_to_delete)} ---")
    
    deleted_count = 0
    for username in usernames_to_delete:
        try:
            user = Funcionarios.objects.get(username=username)
            user.delete()
            print(f"Usuario '{username}' eliminado correctamente.")
            deleted_count += 1
        except Funcionarios.DoesNotExist:
            print(f"Usuario '{username}' no encontrado (quizás ya fue eliminado).")
        except Exception as e:
            print(f"Error al eliminar '{username}': {e}")

    print(f"\nTotal eliminados: {deleted_count}")
    
    # Verificar total restante
    total_restante = Funcionarios.objects.count()
    print(f"Total de usuarios restantes en BD: {total_restante}")

if __name__ == "__main__":
    eliminar_usuarios_chat()
