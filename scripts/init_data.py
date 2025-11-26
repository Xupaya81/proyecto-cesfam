import os
import sys
import django

# Add the project root to the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cesfam_backend.settings')
django.setup()

from intranet.models import Funcionarios, Roles

def create_roles():
    roles = ['Administrador', 'Subdirección', 'Funcionario']
    for r in roles:
        obj, created = Roles.objects.get_or_create(nombre_rol=r)
        if created:
            print(f"Rol creado: {r}")
        else:
            print(f"Rol existente: {r}")

def create_users():
    # Admin
    try:
        admin_rol = Roles.objects.get(nombre_rol='Administrador')
        if not Funcionarios.objects.filter(username='admin').exists():
            u = Funcionarios.objects.create_superuser('admin', 'admin@cesfam.cl', 'administrador1234')
            u.id_rol = admin_rol
            u.save()
            print("Usuario admin creado.")
        else:
            print("Usuario admin ya existe.")
    except Exception as e:
        print(f"Error creando admin: {e}")

    # Subdireccion
    try:
        sub_rol = Roles.objects.get(nombre_rol='Subdirección')
        if not Funcionarios.objects.filter(username='subdireccion').exists():
            u = Funcionarios.objects.create_user('subdireccion', 'subdireccion@cesfam.cl', 'Escarabajo.123')
            u.id_rol = sub_rol
            u.is_staff = True 
            u.save()
            print("Usuario subdireccion creado.")
        else:
            print("Usuario subdireccion ya existe.")
    except Exception as e:
        print(f"Error creando subdireccion: {e}")

    # Funcionario
    try:
        func_rol = Roles.objects.get(nombre_rol='Funcionario')
        if not Funcionarios.objects.filter(username='funcionario').exists():
            u = Funcionarios.objects.create_user('funcionario', 'funcionario@cesfam.cl', 'Elefante.123')
            u.id_rol = func_rol
            u.save()
            print("Usuario funcionario creado.")
        else:
            print("Usuario funcionario ya existe.")
    except Exception as e:
        print(f"Error creando funcionario: {e}")

if __name__ == '__main__':
    print("Iniciando carga de datos...")
    create_roles()
    create_users()
    print("Carga finalizada.")
