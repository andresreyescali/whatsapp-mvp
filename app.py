import os
import json
import secrets
import time
import uuid
import requests
import re
from flask import Flask, jsonify, request, render_template, session, redirect
from core.config import config
from core.database import db_manager
from core.logger import setup_logging, logger
from whatsapp.webhook import register_webhook_routes
from tenants.onboarding import register_new_tenant
from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from ai.training import trainer
from ai.client import ai_client
from auth.auth import auth_manager
from functools import wraps
from datetime import timedelta
from werkzeug.middleware.proxy_fix import ProxyFix

setup_logging()

# Al inicio de app.py
app = Flask(__name__, 
            template_folder='web/templates',
            static_folder='web/static',
            static_url_path='/static')


app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configuración de sesión - AGREGAR DESPUÉS DE CREAR app
app.secret_key = os.environ['SECRET_KEY']
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SECURE'] = True  # True si usas HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Configurar CORS
@app.after_request
def after_request(response):
    # En producción, restringir a dominios específicos
    allowed_origins = os.environ.get('ALLOWED_ORIGINS', '*')
    response.headers.add('Access-Control-Allow-Origin', allowed_origins)
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    return response

# Inicializar base de datos con reintentos
max_retries = 5
for i in range(max_retries):
    try:
        db_manager.init_global_tables()
        logger.info('Base de datos inicializada correctamente')
        break
    except Exception as e:
        logger.error(f'Intento {i+1} de {max_retries} falló: {e}')
        if i < max_retries - 1:
            time.sleep(3)
        else:
            logger.error('No se pudo conectar a la base de datos')
            raise

register_webhook_routes(app)

# ==================== FUNCIÓN AUXILIAR ====================

def _get_schema_name(tenant_id: str) -> str:
    """Obtiene el schema_name de un tenant"""
    from tenants.repository import tenant_repo
    tenant = tenant_repo.find_by_id(tenant_id)
    if tenant and tenant.get('schema_name'):
        return tenant['schema_name']
    return f"tenant_{tenant_id.replace('-', '_')}"

# ==================== Formatear Telefono ====================

def validar_email(email: str) -> bool:
    """Valida formato de email"""
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(patron, email) is not None

def formatear_telefono(telefono: str) -> str:
    """Formatea el número de teléfono para WhatsApp"""
    if not telefono:
        return None
    
    # Limpiar el número (quitar espacios, guiones, paréntesis)
    telefono_limpio = re.sub(r'[\s\-\(\)]', '', str(telefono))
    
    # Eliminar cualquier + existente para procesar
    if telefono_limpio.startswith('+'):
        telefono_limpio = telefono_limpio[1:]
    
    # Si es número colombiano de 10 dígitos (empieza con 3)
    if len(telefono_limpio) == 10 and telefono_limpio.startswith('3'):
        telefono_formateado = '+57' + telefono_limpio
    # Si ya tiene código de país 57 pero sin +
    elif len(telefono_limpio) == 12 and telefono_limpio.startswith('57'):
        telefono_formateado = '+' + telefono_limpio
    # Si es número internacional (más de 10 dígitos)
    elif len(telefono_limpio) > 10:
        telefono_formateado = '+' + telefono_limpio
    else:
        # Si no cumple ninguna condición, agregar + al inicio
        telefono_formateado = '+' + telefono_limpio
    
    return telefono_formateado

# ==================== DECORADORES DE AUTENTICACIÓN ====================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Para páginas HTML (no API), verificar sesión
        if not request.path.startswith('/api/'):
            if 'usuario_id' not in session and session.get('rol_sistema') != 'super_admin':
                return redirect('/')
            return f(*args, **kwargs)
        
        # Para API, devolver 401 si no autenticado
        if 'usuario_id' not in session and session.get('rol_sistema') != 'super_admin':
            return jsonify({'error': 'No autenticado'}), 401
        return f(*args, **kwargs)
    return decorated_function

def tenant_owner_required(f):
    @wraps(f)
    def decorated_function(tenant_id, *args, **kwargs):
        if 'usuario_id' not in session:
            return jsonify({'error': 'No autenticado'}), 401
        
        if session.get('rol_sistema') == 'super_admin':
            return f(tenant_id, *args, **kwargs)
        
        try:
            negocios = auth_manager.get_negocios_usuario(session['usuario_id'])
            for n in negocios:
                if n['id'] == tenant_id:
                    return f(tenant_id, *args, **kwargs)
        except Exception as e:
            logger.error(f"Error verificando acceso: {e}")
            return jsonify({'error': 'Error de autorización'}), 403
        
        return jsonify({'error': 'No tienes acceso a este negocio'}), 403
    return decorated_function

def tenant_owner_required_from_args(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session:
            return redirect('/')
        
        tenant_id = request.args.get('tenant_id')
        if not tenant_id:
            return "Se requiere tenant_id", 400
        
        if session.get('rol_sistema') == 'super_admin':
            return f(*args, **kwargs)
        
        negocios = auth_manager.get_negocios_usuario(session['usuario_id'])
        for n in negocios:
            if n['id'] == tenant_id:
                return f(*args, **kwargs)
        
        return "No tienes acceso a este negocio", 403
    return decorated_function

def tenant_required(f):
    @wraps(f)
    def decorated_function(tenant_id, *args, **kwargs):
        if 'usuario_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'No autenticado'}), 401
            return redirect('/')
        
        tenant = tenant_repo.find_by_id(tenant_id)
        if not tenant:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Negocio no encontrado'}), 404
            return "Negocio no encontrado", 404
        
        if session.get('rol_sistema') == 'super_admin':
            return f(tenant_id, *args, **kwargs)
        
        negocios = auth_manager.get_negocios_usuario(session['usuario_id'])
        for n in negocios:
            if n['id'] == tenant_id:
                return f(tenant_id, *args, **kwargs)
        
        if request.path.startswith('/api/'):
            return jsonify({'error': 'No tienes acceso a este negocio'}), 403
        return "No tienes acceso a este negocio", 403
    return decorated_function

# ==================== PÁGINAS PÚBLICAS ====================

@app.route('/')
def landing():
    return render_template('index.html')

@app.route('/terminos')
def terminos():
    return render_template('terminos.html')

@app.route('/privacidad')
def privacidad():
    return render_template('privacidad.html')

@app.route('/politicas-uso')
def politicas_uso():
    return render_template('politicas-uso.html')

# ==================== SUPER ADMIN ENDPOINTS ====================

@app.route('/super/admin/login-page')
def super_admin_login_page():
    return render_template('super_admin_login.html')

@app.route('/super/admin/login', methods=['POST'])
def super_admin_login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    super_admin_email = os.environ.get('SUPER_ADMIN_EMAIL', 'admin@whatsappbotsaas.com')
    super_admin_password = os.environ.get('SUPER_ADMIN_PASSWORD', 'Admin123!')
    
    if email == super_admin_email and password == super_admin_password:
        session.clear()
        session['usuario_id'] = 'super_admin'
        session['email'] = email
        session['rol_sistema'] = 'super_admin'
        session['nombre'] = 'Super Administrador'
        return jsonify({'success': True, 'rol': 'super_admin'})
    
    return jsonify({'success': False, 'error': 'Credenciales incorrectas'})

@app.route('/super/admin/check-auth', methods=['GET'])
def super_admin_check_auth():
    if session.get('rol_sistema') == 'super_admin':
        return jsonify({'authenticated': True, 'email': session.get('email')})
    return jsonify({'authenticated': False})

@app.route('/super/admin/dashboard')
def super_admin_dashboard():
    if session.get('rol_sistema') != 'super_admin':
        return redirect('/super/admin/login-page')
    return render_template('super_admin.html')

@app.route('/super/admin/usuarios', methods=['GET'])
def super_admin_usuarios():
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    usuarios = auth_manager.get_all_usuarios()
    return jsonify(usuarios)

@app.route('/super/admin/negocios', methods=['GET'])
def super_admin_negocios():
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    negocios = auth_manager.get_all_negocios()
    return jsonify(negocios)

@app.route('/super/admin/usuario/<usuario_id>', methods=['PUT', 'OPTIONS'])
def super_admin_update_usuario(usuario_id):
    if request.method == 'OPTIONS':
        return '', 200
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    try:
        data = request.json
        result = auth_manager.actualizar_usuario(usuario_id, data)
        if result.get('success'):
            return jsonify({'success': True, 'message': result.get('message', 'Usuario actualizado')})
        return jsonify({'success': False, 'error': result.get('error', 'Error al actualizar')}), 400
    except Exception as e:
        logger.error(f'Error actualizando usuario: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/super/admin/usuario/<usuario_id>', methods=['DELETE'])
def super_admin_delete_usuario(usuario_id):
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    result = auth_manager.eliminar_usuario(usuario_id)
    return jsonify(result)

@app.route('/super/admin/debug', methods=['GET'])
def super_admin_debug():
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.usuarios")
            total_usuarios = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM public.tenants")
            total_negocios = cur.fetchone()[0]
            return jsonify({'total_usuarios': total_usuarios, 'total_negocios': total_negocios})

# ==================== AUTH ENDPOINTS ====================

@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    data = request.json
    result = auth_manager.registrar_usuario(
        email=data.get('email'),
        password=data.get('password'),
        nombre_completo=data.get('nombre_completo'),
        telefono=data.get('telefono')
    )
    return jsonify(result)

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    data = request.json
    result = auth_manager.login(data.get('email'), data.get('password'))
    if result.get('success'):
        session.clear()
        session['usuario_id'] = result['usuario_id']
        session['email'] = result['email']
        session['nombre'] = result.get('nombre')
        session['rol_sistema'] = result.get('rol_sistema', 'admin_cliente')
        session.permanent = True
    return jsonify(result)

@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/negocios/usuario', methods=['GET'])
@login_required
def api_negocios_usuario():
    """Obtiene los negocios del usuario actual"""
    if session.get('rol_sistema') == 'super_admin':
        negocios = tenant_repo.get_all()
        return jsonify([{'id': n['id'], 'nombre': n['nombre'], 'phone_id': n['phone_id'], 'verificado': True} for n in negocios])
    
    negocios = auth_manager.get_negocios_usuario(session['usuario_id'])
    return jsonify(negocios)

# ==================== PERFIL DE USUARIO ====================

@app.route('/api/usuario/perfil', methods=['GET'])
@login_required
def get_perfil():
    if session['usuario_id'] == 'super_admin':
        return jsonify({'error': 'No autenticado'}), 401
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id, email, nombre_completo, telefono, created_at FROM public.usuarios WHERE id = %s', (session['usuario_id'],))
            row = cur.fetchone()
            if row:
                return jsonify({'id': row[0], 'email': row[1], 'nombre': row[2], 'telefono': row[3], 'created_at': row[4]})
    return jsonify({'error': 'Usuario no encontrado'}), 404

@app.route('/api/usuario/perfil', methods=['PUT'])
@login_required
def update_perfil():
    if session['usuario_id'] == 'super_admin':
        return jsonify({'error': 'No autenticado'}), 401
    data = request.json
    updates = []
    params = []
    if data.get('nombre'):
        updates.append("nombre_completo = %s")
        params.append(data['nombre'])
        session['nombre'] = data['nombre']
    if data.get('telefono'):
        updates.append("telefono = %s")
        params.append(data['telefono'])
    if data.get('email') and data['email'] != session['email']:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM public.usuarios WHERE email = %s AND id != %s", (data['email'], session['usuario_id']))
                if cur.fetchone():
                    return jsonify({'error': 'El email ya está en uso'}), 400
        updates.append("email = %s")
        params.append(data['email'])
        session['email'] = data['email']
    if not updates:
        return jsonify({'error': 'No hay datos para actualizar'}), 400
    params.append(session['usuario_id'])
    query = f"UPDATE public.usuarios SET {', '.join(updates)} WHERE id = %s"
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()
    return jsonify({'success': True, 'message': 'Perfil actualizado'})

# ==================== DASHBOARD DEL USUARIO ====================

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')
 

# ==================== NEGOCIOS (TENANTS) ====================

@app.route('/api/negocio/registrar', methods=['POST'])
@login_required
def api_registrar_negocio():
    if session['usuario_id'] == 'super_admin':
        return jsonify({'success': False, 'error': 'No autenticado'}), 401
    data = request.json
    result = auth_manager.crear_negocio(
        usuario_id=session['usuario_id'],
        nombre=data.get('nombre'),
        phone_id=data.get('phone_id'),
        token=data.get('token'),
        tipo_negocio=data.get('tipo_negocio', 'restaurante')
    )
    return jsonify(result)

@app.route('/api/negocio/verificar', methods=['POST'])
@login_required
def api_verificar_negocio():
    if session['usuario_id'] == 'super_admin':
        return jsonify({'success': False, 'error': 'No autenticado'}), 401
    data = request.json
    result = auth_manager.verificar_negocio(tenant_id=data.get('tenant_id'), codigo=data.get('codigo'))
    return jsonify(result)

@app.route('/api/negocio/reenviar_codigo_email/<tenant_id>', methods=['POST'])
@login_required
@tenant_owner_required
def reenviar_codigo_email(tenant_id):
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Negocio no encontrado'}), 404
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT codigo_verificacion FROM public.verificacion_negocio WHERE tenant_id = %s AND verificado = false', (tenant_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Negocio ya verificado o no existe'}), 400
            codigo = row[0]
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT email FROM public.usuarios WHERE id = %s", (session['usuario_id'],))
            row = cur.fetchone()
            email = row[0] if row else None
    if not email:
        return jsonify({'error': 'No hay email registrado'}), 400
    from utils.email_brevo import email_sender
    enviado = email_sender.enviar_codigo_verificacion(email, codigo, tenant['nombre'])
    if enviado:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE public.verificacion_negocio SET codigo_enviado = NOW() WHERE tenant_id = %s', (tenant_id,))
            conn.commit()
        return jsonify({'success': True, 'message': 'Código reenviado exitosamente'})
    return jsonify({'error': 'Error al enviar el código'}), 500

@app.route('/api/negocio/reenviar_codigo/<tenant_id>', methods=['POST'])
@login_required
@tenant_owner_required
def reenviar_codigo(tenant_id):
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Negocio no encontrado'}), 404
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT codigo_verificacion FROM public.verificacion_negocio WHERE tenant_id = %s AND verificado = false', (tenant_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Negocio ya verificado o no existe'}), 400
            codigo = row[0]
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT telefono FROM public.usuarios WHERE id = %s", (session['usuario_id'],))
            row = cur.fetchone()
            telefono = row[0] if row else None
    if not telefono:
        return jsonify({'error': 'No hay número de teléfono registrado'}), 400
    enviado = auth_manager.enviar_codigo_whatsapp(tenant['phone_id'], tenant['token'], codigo, telefono)
    if enviado:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE public.verificacion_negocio SET codigo_enviado = NOW() WHERE tenant_id = %s', (tenant_id,))
            conn.commit()
        return jsonify({'success': True, 'message': 'Código reenviado exitosamente'})
    return jsonify({'error': 'Error al enviar el código'}), 500

# ==================== ROLES Y USUARIOS POR NEGOCIO ====================

@app.route('/api/negocio/<tenant_id>/usuarios', methods=['GET'])
@login_required
@tenant_owner_required
def get_usuarios_negocio(tenant_id):
    usuarios = auth_manager.get_usuarios_negocio(tenant_id)
    mi_rol = auth_manager.get_rol_negocio(session['usuario_id'], tenant_id)
    return jsonify({
        'usuarios': usuarios,
        'mi_rol': mi_rol,
        'puedo_invitar': auth_manager.verificar_permiso(session['usuario_id'], tenant_id, 'invitar_usuarios')
    })

@app.route('/api/negocio/<tenant_id>/invitar', methods=['POST'])
@login_required
@tenant_owner_required
def invitar_usuario(tenant_id):
    data = request.json
    result = auth_manager.invitar_usuario(session['usuario_id'], tenant_id, data.get('email'), data.get('rol', 'viewer'))
    return jsonify(result)

@app.route('/api/negocio/<tenant_id>/usuarios/<usuario_id>', methods=['DELETE'])
@login_required
@tenant_owner_required
def remover_usuario(tenant_id, usuario_id):
    result = auth_manager.remover_usuario(session['usuario_id'], tenant_id, usuario_id)
    return jsonify(result)

@app.route('/api/negocio/<tenant_id>/usuarios/<usuario_id>/rol', methods=['PUT'])
@login_required
@tenant_owner_required
def cambiar_rol_usuario(tenant_id, usuario_id):
    data = request.json
    result = auth_manager.cambiar_rol_usuario(session['usuario_id'], tenant_id, usuario_id, data.get('rol'))
    return jsonify(result)

@app.route('/api/negocio/<tenant_id>/permisos', methods=['GET'])
@login_required
@tenant_owner_required
def verificar_permisos(tenant_id):
    permisos = {
        'editar_negocio': auth_manager.verificar_permiso(session['usuario_id'], tenant_id, 'editar_negocio'),
        'invitar_usuarios': auth_manager.verificar_permiso(session['usuario_id'], tenant_id, 'invitar_usuarios'),
        'editar_menu': auth_manager.verificar_permiso(session['usuario_id'], tenant_id, 'editar_menu'),
        'ver_reportes': auth_manager.verificar_permiso(session['usuario_id'], tenant_id, 'ver_reportes'),
        'entrenar_ia': auth_manager.verificar_permiso(session['usuario_id'], tenant_id, 'entrenar_ia'),
        'ver_pedidos': auth_manager.verificar_permiso(session['usuario_id'], tenant_id, 'ver_pedidos'),
        'eliminar_negocio': auth_manager.verificar_permiso(session['usuario_id'], tenant_id, 'eliminar_negocio')
    }
    mi_rol = auth_manager.get_rol_negocio(session['usuario_id'], tenant_id)
    return jsonify({'permisos': permisos, 'mi_rol': mi_rol})

# ==================== ENDPOINTS BÁSICOS ====================

@app.route('/api/register', methods=['POST'])
def api_register_tenant():
    return register_new_tenant()

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok', 'message': 'WhatsApp SaaS is running'}

# ==================== ADMIN (PANEL ANTIGUO) ====================

@app.route('/admin/tenants')
@login_required
def list_tenants():
    if session.get('rol_sistema') != 'super_admin':
        return redirect('/dashboard')
    tenants = tenant_repo.get_all()
    return render_template('tenants.html', tenants=tenants)

@app.route('/registro')
def registro():
    return render_template('registro.html')

@app.route('/registro_web', methods=['POST'])
def registro_web():
    nombre = request.form.get('nombre')
    phone_id = request.form.get('phone_id')
    token = request.form.get('token')
    tenant = tenant_repo.create(nombre, phone_id, token)
    schema_manager.create_tenant_schema(tenant['id'], 'restaurante')
    return render_template('registro_exito.html', tenant=tenant)

@app.route('/admin/menu', methods=['GET'])
@login_required
@tenant_owner_required_from_args
def admin_menu():
    tenant_id = request.args.get('tenant_id')
    if not tenant_id:
        return redirect('/dashboard')
    
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return redirect('/dashboard')
    
    return render_template('menu.html', tenant=tenant)

@app.route('/admin/train', methods=['GET'])
@login_required
@tenant_owner_required_from_args
def train_ia_page():
    tenant_id = request.args.get('tenant_id')
    if not tenant_id:
        return redirect('/dashboard')
    
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return redirect('/dashboard')
    
    return render_template('train.html', tenant_id=tenant_id)

# ========== PRODUCTOS CON PERSONALIZACIONES (CRUD COMPLETO) ==========
# ========== ACTUALIZADO: soporta imagen_url, tiempo_preparacion, destacado, personalizaciones, adicionales ==========

@app.route('/api/tenant/<tenant_id>/menu', methods=['GET'])
@login_required
@tenant_owner_required
def get_tenant_menu(tenant_id):
    """Obtiene el menú completo del tenant con todos los campos"""
    try:
        menu = schema_manager.get_menu(tenant_id)
        return jsonify(menu)
    except Exception as e:
        logger.error(f"Error obteniendo menú: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/config', methods=['GET'])
@login_required
@tenant_owner_required
def get_tenant_config(tenant_id):
    """Obtiene la configuración del tenant"""
    try:
        tenant = tenant_repo.find_by_id(tenant_id)
        if not tenant:
            return jsonify({'error': 'Tenant no encontrado'}), 404
        return jsonify({'usar_ia': tenant.get('usar_ia', False)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/config/ia', methods=['PUT', 'OPTIONS'])
@login_required
@tenant_owner_required
def update_tenant_ia(tenant_id):
    """Actualiza la configuración de IA del tenant"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        usar_ia = data.get('usar_ia', False)
        tenant_repo.update_ia_config(tenant_id, usar_ia)
        return jsonify({'status': 'ok', 'usar_ia': usar_ia})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/admin/add_product/<tenant_id>', methods=['POST', 'OPTIONS'])
@login_required
@tenant_owner_required
def add_product(tenant_id):
    """Agrega un nuevo producto con todos los campos"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        nombre = data.get('nombre')
        if not nombre:
            return jsonify({'error': 'El nombre es requerido'}), 400
        
        producto = {
            'tenant_id': tenant_id,
            'nombre': nombre,
            'descripcion': data.get('descripcion', ''),
            'precio': data.get('precio', 0),
            'categoria': data.get('categoria', 'general'),
            'disponible': data.get('disponible', True),
            'imagen_url': data.get('imagen_url'),
            'tiempo_preparacion': data.get('tiempo_preparacion'),
            'destacado': data.get('destacado', False),
            'personalizaciones': data.get('personalizaciones', []),
            'adicionales': data.get('adicionales', [])
        }
        
        product_id = schema_manager.add_product(**producto)
        
        return jsonify({
            'success': True,
            'message': 'Producto agregado exitosamente',
            'product_id': product_id
        }), 201
    except Exception as e:
        logger.error(f'Error agregando producto: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/admin/update_product/<tenant_id>/<product_id>', methods=['PUT', 'OPTIONS'])
@login_required
@tenant_owner_required
def update_product(tenant_id, product_id):
    """Actualiza un producto existente con todos los campos"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        
        producto = {
            'tenant_id': tenant_id,
            'product_id': product_id,
            'nombre': data.get('nombre'),
            'descripcion': data.get('descripcion'),
            'precio': data.get('precio'),
            'categoria': data.get('categoria'),
            'disponible': data.get('disponible'),
            'imagen_url': data.get('imagen_url'),
            'tiempo_preparacion': data.get('tiempo_preparacion'),
            'destacado': data.get('destacado'),
            'personalizaciones': data.get('personalizaciones'),
            'adicionales': data.get('adicionales')
        }
        
        # Filtrar None values
        producto = {k: v for k, v in producto.items() if v is not None}
        
        success = schema_manager.update_product(**producto)
        
        if success:
            return jsonify({'success': True, 'message': 'Producto actualizado'})
        else:
            return jsonify({'error': 'No se pudo actualizar el producto'}), 400
    except Exception as e:
        logger.error(f'Error actualizando producto: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/admin/delete_product/<tenant_id>/<product_id>', methods=['DELETE', 'OPTIONS'])
@login_required
@tenant_owner_required
def delete_product(tenant_id, product_id):
    """Elimina un producto"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        success = schema_manager.delete_product(tenant_id, product_id)
        
        if success:
            return jsonify({'success': True, 'message': 'Producto eliminado'})
        else:
            return jsonify({'error': 'No se pudo eliminar el producto'}), 400
    except Exception as e:
        logger.error(f'Error eliminando producto: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/admin/toggle_product/<tenant_id>/<product_id>', methods=['PUT', 'POST', 'OPTIONS'])
@login_required
@tenant_owner_required
def toggle_product(tenant_id, product_id):
    """Cambia el estado disponible/no disponible de un producto"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Methods', 'PUT, POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response, 200
    
    try:
        data = request.get_json(silent=True) or {}
        disponible = data.get('disponible', True)
        
        success = schema_manager.update_product(
            tenant_id=tenant_id,
            product_id=product_id,
            disponible=disponible
        )
        
        if success:
            estado = 'disponible' if disponible else 'no disponible'
            return jsonify({'success': True, 'message': f'Producto {estado}'})
        else:
            return jsonify({'error': 'No se pudo cambiar el estado'}), 400
    except Exception as e:
        logger.error(f'Error toggling producto: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/admin/toggle_featured/<tenant_id>/<product_id>', methods=['PUT', 'OPTIONS'])
@login_required
@tenant_owner_required
def toggle_featured(tenant_id, product_id):
    """Cambia el estado destacado de un producto"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        destacado = data.get('destacado', False)
        
        success = schema_manager.update_product(
            tenant_id=tenant_id,
            product_id=product_id,
            destacado=destacado
        )
        
        if success:
            estado = 'destacado' if destacado else 'no destacado'
            return jsonify({'success': True, 'message': f'Producto {estado}'})
        else:
            return jsonify({'error': 'No se pudo cambiar el estado'}), 400
    except Exception as e:
        logger.error(f'Error en toggle_featured: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/product/<product_id>', methods=['GET'])
@login_required
@tenant_owner_required
def get_product_detail(tenant_id, product_id):
    """Obtiene detalles completos de un producto incluyendo personalizaciones"""
    try:
        product = schema_manager.get_product(tenant_id, product_id)
        if product:
            return jsonify(product)
        else:
            return jsonify({'error': 'Producto no encontrado'}), 404
    except Exception as e:
        logger.error(f'Error en get_product_detail: {e}')
        return jsonify({'error': str(e)}), 500

# ==================== AI TRAINING ====================

@app.route('/admin/train/<tenant_id>', methods=['GET', 'POST'])
@login_required
@tenant_owner_required
def train_ia(tenant_id):
    if request.method == 'GET':
        tenant = tenant_repo.find_by_id(tenant_id)
        return render_template('train.html', tenant_id=tenant_id, tenant=tenant)
    
    try:
        data = request.json
        tipo = data.get('tipo')
        modo = data.get('modo', 'acumular')  # Modo de entrenamiento
        
        # CORRECCIÓN: Pasar tenant_id como primer argumento
        if tipo == 'imagen':
            resultado = trainer.procesar_imagen(tenant_id, data.get('imagen'))
        else:
            resultado = trainer.procesar_texto(tenant_id, data.get('texto'))
        
        if not resultado:
            return jsonify({'error': 'No se pudo procesar'}), 500
        
        # ========== OBTENER CONTEXTO ACTUAL ==========
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT menu_estructurado, instrucciones, horario, ubicacion, 
                           politicas, prompt_personalizado 
                    FROM public.tenant_context 
                    WHERE tenant_id = %s
                ''', (tenant_id,))
                row = cur.fetchone()
                
                contexto_actual = {
                    'productos': [],
                    'instrucciones': '',
                    'horario': '',
                    'ubicacion': '',
                    'politicas': '',
                    'prompt_personalizado': ''
                }
                
                if row:
                    menu_raw = row[0]
                    if menu_raw:
                        if isinstance(menu_raw, str):
                            try:
                                contexto_actual['productos'] = json.loads(menu_raw)
                            except:
                                contexto_actual['productos'] = []
                        elif isinstance(menu_raw, list):
                            contexto_actual['productos'] = menu_raw
                        else:
                            contexto_actual['productos'] = []
                    
                    contexto_actual['instrucciones'] = row[1] or ''
                    contexto_actual['horario'] = row[2] or ''
                    contexto_actual['ubicacion'] = row[3] or ''
                    contexto_actual['politicas'] = row[4] or ''
                    contexto_actual['prompt_personalizado'] = row[5] or ''
        
        # ========== COMBINAR PRODUCTOS (evitar duplicados) ==========
        productos_actuales = contexto_actual.get('productos', [])
        if not isinstance(productos_actuales, list):
            productos_actuales = []
        
        productos_nuevos = resultado.get('productos', [])
        if not isinstance(productos_nuevos, list):
            productos_nuevos = []
        
        # Aplicar modo de entrenamiento
        if modo == 'reemplazar':
            # Reemplazar completamente
            productos_combinados = {}
            for p in productos_nuevos:
                if isinstance(p, dict) and p.get('nombre'):
                    productos_combinados[p.get('nombre')] = p
        else:
            # Acumular (comportamiento por defecto)
            productos_combinados = {}
            for p in productos_actuales:
                if isinstance(p, dict) and p.get('nombre'):
                    productos_combinados[p.get('nombre')] = p
            
            for p in productos_nuevos:
                if isinstance(p, dict) and p.get('nombre'):
                    nombre = p.get('nombre')
                    if nombre in productos_combinados:
                        if p.get('precio'):
                            productos_combinados[nombre]['precio'] = p.get('precio')
                        if p.get('descripcion'):
                            productos_combinados[nombre]['descripcion'] = p.get('descripcion')
                    else:
                        productos_combinados[nombre] = p
        
        productos_finales = list(productos_combinados.values())
        
        # ========== COMBINAR INSTRUCCIONES ==========
        instrucciones_actuales = contexto_actual.get('instrucciones', '')
        instrucciones_nuevas = resultado.get('instrucciones_adicionales', '')
        
        if modo == 'reemplazar':
            instrucciones_finales = instrucciones_nuevas
        else:
            if instrucciones_actuales and instrucciones_nuevas:
                instrucciones_finales = f"{instrucciones_actuales}\n\n{instrucciones_nuevas}"
            elif instrucciones_nuevas:
                instrucciones_finales = instrucciones_nuevas
            else:
                instrucciones_finales = instrucciones_actuales
        
        # ========== COMBINAR POLÍTICAS ==========
        politicas_actuales = contexto_actual.get('politicas', '')
        politicas_nuevas = resultado.get('politicas', '')
        
        if modo == 'reemplazar':
            politicas_finales = politicas_nuevas
        else:
            if politicas_actuales and politicas_nuevas:
                politicas_finales = f"{politicas_actuales}\n\n{politicas_nuevas}"
            elif politicas_nuevas:
                politicas_finales = politicas_nuevas
            else:
                politicas_finales = politicas_actuales
        
        # ========== HORARIO y UBICACIÓN ==========
        if modo == 'reemplazar':
            horario_final = resultado.get('horario', '')
            ubicacion_final = resultado.get('ubicacion', '')
        else:
            horario_final = resultado.get('horario', '') or contexto_actual.get('horario', '')
            ubicacion_final = resultado.get('ubicacion', '') or contexto_actual.get('ubicacion', '')
        
        # ========== GENERAR PROMPT PERSONALIZADO ==========
        contexto_combinado = {
            'productos': productos_finales,
            'horario': horario_final,
            'ubicacion': ubicacion_final,
            'politicas': politicas_finales,
            'instrucciones_adicionales': instrucciones_finales
        }
        prompt_personalizado = trainer.generar_prompt_personalizado(contexto_combinado)
        
        # ========== GUARDAR EN BD ==========
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO public.tenant_context (tenant_id, menu_estructurado, instrucciones, 
                                                       horario, ubicacion, politicas, prompt_personalizado,
                                                       updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (tenant_id) DO UPDATE SET
                        menu_estructurado = EXCLUDED.menu_estructurado,
                        instrucciones = EXCLUDED.instrucciones,
                        horario = EXCLUDED.horario,
                        ubicacion = EXCLUDED.ubicacion,
                        politicas = EXCLUDED.politicas,
                        prompt_personalizado = EXCLUDED.prompt_personalizado,
                        updated_at = NOW()
                ''', (tenant_id, json.dumps(productos_finales), instrucciones_finales, 
                      horario_final, ubicacion_final, politicas_finales, prompt_personalizado))
            conn.commit()
        
        # ========== GUARDAR PRODUCTOS EN EL ESQUEMA DEL TENANT ==========
        schema_name = _get_schema_name(tenant_id)
        productos_agregados = 0
        productos_actualizados = 0
        
        for producto in productos_nuevos:
            if isinstance(producto, dict) and producto.get('nombre') and producto.get('precio'):
                try:
                    nombre = producto.get('nombre').strip()
                    precio = int(producto.get('precio', 0))
                    descripcion = producto.get('descripcion', '')
                    categoria = producto.get('categoria', 'general')
                    es_base = producto.get('es_base', True)
                    
                    with db_manager.get_connection(tenant_id) as conn:
                        with conn.cursor() as cur:
                            cur.execute(f'SELECT id, precio FROM "{schema_name}".productos WHERE nombre ILIKE %s', (nombre,))
                            existing = cur.fetchone()
                            
                            if existing:
                                # Actualizar precio si cambió
                                existing_precio = existing[1]
                                if existing_precio != precio:
                                    cur.execute(f'''
                                        UPDATE "{schema_name}".productos 
                                        SET precio = %s, descripcion = %s, categoria = %s, 
                                            disponible = true, updated_at = NOW()
                                        WHERE nombre ILIKE %s
                                    ''', (precio, descripcion, categoria, nombre))
                                    productos_actualizados += 1
                                    logger.info(f"🔄 [BD] Actualizado: {nombre} ${existing_precio} → ${precio}")
                            else:
                                product_id = str(uuid.uuid4())
                                cur.execute(f'''
                                    INSERT INTO "{schema_name}".productos 
                                    (id, nombre, descripcion, precio, categoria, disponible, es_base)
                                    VALUES (%s, %s, %s, %s, %s, true, %s)
                                ''', (product_id, nombre, descripcion, precio, categoria, es_base))
                                productos_agregados += 1
                                logger.info(f"➕ [BD] Nuevo producto: {nombre} - ${precio}")
                            conn.commit()
                except Exception as e:
                    logger.warning(f'Error guardando producto {producto.get("nombre")}: {e}')
        
        logger.info(f'Entrenamiento completado: +{productos_agregados} nuevos, ~{productos_actualizados} actualizados')
        
        return jsonify({
            'status': 'ok',
            'contexto': contexto_combinado,
            'productos': productos_nuevos,
            'productos_agregados': productos_agregados,
            'productos_actualizados': productos_actualizados,
            'horario': horario_final,
            'ubicacion': ubicacion_final,
            'politicas': politicas_finales,
            'instrucciones_adicionales': instrucciones_finales,
            'message': f'✅ Entrenamiento exitoso. {productos_agregados} productos agregados, {productos_actualizados} actualizados.'
        })
        
    except Exception as e:
        logger.error(f'Error en train_ia: {str(e)}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'details': 'Error interno del servidor'}), 500
    
@app.route('/api/tenant/<tenant_id>/context', methods=['GET', 'DELETE'])
@login_required
@tenant_owner_required
def get_tenant_context(tenant_id):
    if request.method == 'DELETE':
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('DELETE FROM public.tenant_context WHERE tenant_id = %s', (tenant_id,))
                conn.commit()
            return jsonify({'success': True, 'message': 'Contexto eliminado'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM public.tenant_context WHERE tenant_id = %s', (tenant_id,))
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    result = dict(zip(columns, row))
                    if result.get('menu_estructurado') and isinstance(result['menu_estructurado'], str):
                        result['menu_estructurado'] = json.loads(result['menu_estructurado'])
                    return jsonify(result)
                return jsonify({})
    except Exception as e:
        return jsonify({}), 500

@app.route('/api/tenant/<tenant_id>/conversaciones/cliente/<cliente_numero>', methods=['GET'])
@login_required
@tenant_owner_required
def get_conversaciones_cliente(tenant_id, cliente_numero):
    """Obtiene el historial de conversaciones con un cliente específico"""
    try:
        schema_name = _get_schema_name(tenant_id)
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT mensaje, respuesta, created_at, tipo
                    FROM "{schema_name}".conversaciones 
                    WHERE cliente_numero = %s 
                    ORDER BY created_at ASC
                """, (cliente_numero,))
                rows = cur.fetchall()
                conversaciones = []
                for row in rows:
                    conversaciones.append({
                        'mensaje': row[0],
                        'respuesta': row[1],
                        'fecha': row[2],
                        'tipo': row[3] if len(row) > 3 else 'cliente'
                    })
                return jsonify(conversaciones)
    except Exception as e:
        logger.error(f'Error cargando historial: {e}')
        return jsonify([])
    
# ==================== PANEL DEL CLIENTE ====================

@app.route('/panel/<tenant_id>')
@login_required
@tenant_owner_required
def panel_cliente(tenant_id):
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return "Tenant no encontrado", 404
    return render_template('panel_cliente.html', tenant=tenant)

@app.route('/api/pedido/<pedido_id>/estado', methods=['PUT'])
@login_required
def cambiar_estado_pedido(pedido_id):
    """Cambia el estado de un pedido"""
    data = request.json
    nuevo_estado = data.get('estado')
    
    tenants = tenant_repo.get_all()
    tenant_encontrado = None
    schema_name_encontrado = None
    
    for tenant in tenants:
        schema_name = tenant.get('schema_name')
        if not schema_name:
            schema_name = f"tenant_{tenant['id'].replace('-', '_')}"
        
        try:
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, estado FROM "{schema_name}".pedidos 
                        WHERE id = %s
                    """, (pedido_id,))
                    row = cur.fetchone()
                    if row:
                        tenant_encontrado = tenant['id']
                        schema_name_encontrado = schema_name
                        estado_actual = row[1]
                        break
        except Exception as e:
            logger.warning(f"Error buscando pedido en tenant {tenant['id']}: {e}")
            continue
    
    if not tenant_encontrado:
        return jsonify({'error': 'Pedido no encontrado'}), 404
    
    fecha_campo = {
        'pagado': 'pagado_at',
        'enviado': 'enviado_at',
        'cancelado': 'cancelado_at'
    }.get(nuevo_estado)
    
    try:
        with db_manager.get_connection(tenant_encontrado) as conn:
            with conn.cursor() as cur:
                if fecha_campo:
                    cur.execute(f"""
                        UPDATE "{schema_name_encontrado}".pedidos 
                        SET estado = %s, updated_at = NOW(), {fecha_campo} = NOW()
                        WHERE id = %s
                    """, (nuevo_estado, pedido_id))
                else:
                    cur.execute(f"""
                        UPDATE "{schema_name_encontrado}".pedidos 
                        SET estado = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (nuevo_estado, pedido_id))
            conn.commit()
        
        logger.info(f"Pedido {pedido_id} actualizado a estado {nuevo_estado}")
        return jsonify({'success': True, 'mensaje': f'Pedido marcado como {nuevo_estado}'})
        
    except Exception as e:
        logger.error(f'Error actualizando estado del pedido: {e}')
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/pedido/<pedido_id>/detalle', methods=['GET'])
@login_required
def detalle_pedido(pedido_id):
    tenants = tenant_repo.get_all()
    for t in tenants:
        with db_manager.get_connection(t['id']) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM pedidos WHERE id = %s", (pedido_id,))
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    pedido = dict(zip(columns, row))
                    if not pedido.get('cliente_nombre'):
                        pedido['cliente_nombre'] = pedido['cliente_numero']
                    return jsonify(pedido)
    return jsonify({'error': 'Pedido no encontrado'}), 404

@app.route('/api/tenant/<tenant_id>/conversaciones', methods=['GET'])
@login_required
@tenant_owner_required
def get_conversaciones(tenant_id):
    """Obtiene resumen de conversaciones por cliente desde el esquema del tenant"""
    try:
        schema_name = _get_schema_name(tenant_id)
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = 'conversaciones'
                    )
                """, (schema_name,))
                if not cur.fetchone()[0]:
                    return jsonify([])
                
                cur.execute(f"""
                    SELECT cliente_numero, 
                           COUNT(*) as total_mensajes,
                           MAX(created_at) as ultimo_mensaje
                    FROM "{schema_name}".conversaciones 
                    GROUP BY cliente_numero 
                    ORDER BY ultimo_mensaje DESC 
                    LIMIT 50
                """)
                rows = cur.fetchall()
                conversaciones = []
                for row in rows:
                    conversaciones.append({
                        'cliente_numero': row[0],
                        'cliente_nombre': row[0],
                        'total_mensajes': row[1],
                        'ultimo_mensaje': row[2]
                    })
                logger.info(f"Conversaciones encontradas para tenant {tenant_id}: {len(conversaciones)}")
                return jsonify(conversaciones)
    except Exception as e:
        logger.error(f'Error cargando conversaciones: {e}')
        return jsonify([])

@app.route('/api/tenant/<tenant_id>/configuracion', methods=['GET', 'PUT'])
@login_required
@tenant_owner_required
def tenant_configuracion(tenant_id):
    if request.method == 'GET':
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT configuracion FROM public.tenants WHERE id = %s", (tenant_id,))
                row = cur.fetchone()
                config = row[0] if row and row[0] else {}
                return jsonify(config)
    if request.method == 'PUT':
        data = request.json
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE public.tenants SET configuracion = configuracion || %s WHERE id = %s", (json.dumps(data), tenant_id))
            conn.commit()
        return jsonify({'success': True})

@app.route('/api/tenant/<tenant_id>/pedidos/stats', methods=['GET'])
@login_required
@tenant_owner_required
def get_pedidos_stats(tenant_id):
    """Obtiene estadísticas de pedidos"""
    try:
        schema_name = _get_schema_name(tenant_id)
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = 'pedidos'
                    )
                """, (schema_name,))
                if not cur.fetchone()[0]:
                    return jsonify({'nuevo': 0, 'pagado': 0, 'enviado': 0, 'cancelado': 0, 'total': 0})
                
                cur.execute("""
                    SELECT estado, COUNT(*) as total 
                    FROM pedidos 
                    GROUP BY estado
                """)
                rows = cur.fetchall()
                stats = {row[0]: row[1] for row in rows}
                return jsonify({
                    'nuevo': stats.get('nuevo', 0),
                    'pagado': stats.get('pagado', 0),
                    'enviado': stats.get('enviado', 0),
                    'cancelado': stats.get('cancelado', 0),
                    'pendiente_pago': stats.get('pendiente_pago', 0),
                    'total': sum(stats.values())
                })
    except Exception as e:
        logger.error(f'Error obteniendo estadísticas: {e}')
        return jsonify({'nuevo': 0, 'pagado': 0, 'enviado': 0, 'cancelado': 0, 'total': 0})

@app.route('/api/tenant/<tenant_id>/pedidos', methods=['GET'])
@login_required
@tenant_owner_required
def get_pedidos_tenant(tenant_id):
    """Obtiene pedidos del tenant desde el esquema del tenant"""
    estado = request.args.get('estado', 'todos')
    schema_name = _get_schema_name(tenant_id)
    
    logger.info(f"Obteniendo pedidos para tenant {tenant_id}, schema: {schema_name}, estado: {estado}")
    
    try:
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = 'pedidos'
                    )
                """, (schema_name,))
                tabla_existe = cur.fetchone()[0]
                logger.info(f"Tabla pedidos existe: {tabla_existe}")
                
                if not tabla_existe:
                    return jsonify([])
                
                if estado == 'todos':
                    cur.execute("SELECT * FROM pedidos ORDER BY created_at DESC")
                else:
                    cur.execute("SELECT * FROM pedidos WHERE estado = %s ORDER BY created_at DESC", (estado,))
                
                rows = cur.fetchall()
                logger.info(f"Filas obtenidas: {len(rows)}")
                
                if not rows:
                    return jsonify([])
                
                columns = [desc[0] for desc in cur.description]
                pedidos = []
                for row in rows:
                    pedido = dict(zip(columns, row))
                    if pedido.get('items') and isinstance(pedido['items'], str):
                        try:
                            pedido['items'] = json.loads(pedido['items'])
                        except:
                            pedido['items'] = []
                    
                    if not pedido.get('cliente_nombre'):
                        pedido['cliente_nombre'] = pedido.get('cliente_numero', 'N/A')
                    
                    pedidos.append(pedido)
                
                logger.info(f"Pedidos procesados: {len(pedidos)}")
                return jsonify(pedidos)
                
    except Exception as e:
        logger.error(f'Error cargando pedidos: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ================ Traer pedidos Light ====================

@app.route('/api/tenant/<tenant_id>/pedidos/light', methods=['GET'])
@login_required
@tenant_owner_required
def get_pedidos_light(tenant_id):
    """Versión ligera de pedidos (solo datos esenciales)"""
    schema_name = _get_schema_name(tenant_id)
    estado = request.args.get('estado', 'todos')
    
    try:
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = %s AND table_name = 'pedidos'
                """, (schema_name,))
                columnas = [row[0] for row in cur.fetchall()]
                
                select_cols = ['id', 'cliente_numero', 'total', 'estado', 'created_at']
                if 'numero_pedido' in columnas:
                    select_cols.append('numero_pedido')
                if 'cliente_nombre' in columnas:
                    select_cols.append('cliente_nombre')
                
                select_str = ', '.join([f'"{col}"' for col in select_cols])
                
                if estado == 'todos':
                    cur.execute(f"""
                        SELECT {select_str} 
                        FROM "{schema_name}".pedidos 
                        ORDER BY created_at DESC 
                        LIMIT 50
                    """)
                else:
                    cur.execute(f"""
                        SELECT {select_str} 
                        FROM "{schema_name}".pedidos 
                        WHERE estado = %s 
                        ORDER BY created_at DESC 
                        LIMIT 50
                    """, (estado,))
                
                rows = cur.fetchall()
                col_names = [desc[0] for desc in cur.description]
                
                pedidos = []
                for row in rows:
                    pedido = dict(zip(col_names, row))
                    if not pedido.get('cliente_nombre'):
                        pedido['cliente_nombre'] = pedido.get('cliente_numero', 'Cliente')
                    pedidos.append(pedido)
                
                return jsonify(pedidos)
    except Exception as e:
        logger.error(f"Error en pedidos light: {e}")
        return jsonify([])
    
# ========= PERMITE RESPUESTAS MANUALES AL CLIENTE ========

@app.route('/api/responder-manual', methods=['POST'])
@login_required
def responder_manual():
    """Envía una respuesta manual a un cliente desde el panel"""
    from whatsapp.client import whatsapp_client
    from whatsapp.message_handler import message_handler
    
    data = request.json
    tenant_id = data.get('tenant_id')
    numero = data.get('numero')
    mensaje = data.get('mensaje')
    
    if not tenant_id or not numero or not mensaje:
        return jsonify({'error': 'Faltan datos'}), 400
    
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Negocio no encontrado'}), 404
    
    enviado = whatsapp_client.send_message(tenant, numero, mensaje)
    
    if enviado:
        message_handler._guardar_conversacion(tenant_id, numero, f"📝 Respuesta manual: {mensaje}", "Mensaje enviado manualmente")
        return jsonify({'success': True, 'respuesta': 'Mensaje enviado'})
    
    return jsonify({'error': 'No se pudo enviar el mensaje'}), 500

# ==================== PERSONALIZACIÓN DE PRODUCTOS ====================

@app.route('/api/tenant/<tenant_id>/personalizacion/categorias', methods=['GET'])
@login_required
@tenant_owner_required
def get_categorias_personalizacion(tenant_id):
    """Obtiene las categorías de personalización del tenant"""
    categorias = tenant_repo.get_categorias_personalizacion(tenant_id)
    return jsonify(categorias)


@app.route('/api/tenant/<tenant_id>/personalizacion/opciones', methods=['GET'])
@login_required
@tenant_owner_required
def get_opciones_personalizacion(tenant_id):
    """Obtiene las opciones de personalización del tenant"""
    categoria = request.args.get('categoria')
    opciones = tenant_repo.get_opciones_personalizacion(tenant_id, categoria)
    return jsonify(opciones)


@app.route('/api/tenant/<tenant_id>/personalizacion/opciones', methods=['POST'])
@login_required
@tenant_owner_required
def add_opcion_personalizacion(tenant_id):
    """Agrega una nueva opción de personalización"""
    data = request.json
    result = tenant_repo.agregar_opcion_personalizacion(tenant_id, data)
    return jsonify(result)


@app.route('/api/tenant/<tenant_id>/personalizacion/opciones/<int:opcion_id>', methods=['PUT'])
@login_required
@tenant_owner_required
def update_opcion_personalizacion(tenant_id, opcion_id):
    """Actualiza una opción de personalización"""
    data = request.json
    result = tenant_repo.actualizar_opcion_personalizacion(tenant_id, opcion_id, data)
    return jsonify({'success': result})


@app.route('/api/tenant/<tenant_id>/personalizacion/opciones/<int:opcion_id>', methods=['DELETE'])
@login_required
@tenant_owner_required
def delete_opcion_personalizacion(tenant_id, opcion_id):
    """Elimina una opción de personalización"""
    result = tenant_repo.eliminar_opcion_personalizacion(tenant_id, opcion_id)
    return jsonify({'success': result})


@app.route('/api/tenant/<tenant_id>/productos/<product_id>/personalizacion', methods=['GET', 'PUT'])
@login_required
@tenant_owner_required
def gestionar_personalizacion_producto(tenant_id, product_id):
    """Gestiona si un producto es personalizable"""
    schema_name = _get_schema_name(tenant_id)
    
    if request.method == 'GET':
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT es_personalizable, tamanios_disponibles, opciones_base
                        FROM "{schema_name}".productos 
                        WHERE id = %s
                    """, (product_id,))
                    row = cur.fetchone()
                    if row:
                        return jsonify({
                            'es_personalizable': row[0] or False,
                            'tamanios_disponibles': row[1] if row[1] else [],
                            'opciones_base': row[2] if row[2] else {}
                        })
                    return jsonify({})
        except Exception as e:
            logger.error(f"Error obteniendo personalización: {e}")
            return jsonify({'error': str(e)}), 500
    
    if request.method == 'PUT':
        data = request.json
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        UPDATE "{schema_name}".productos 
                        SET es_personalizable = %s, 
                            tamanios_disponibles = %s,
                            opciones_base = %s,
                            updated_at = NOW()
                        WHERE id = %s
                    """, (data.get('es_personalizable', False), 
                          json.dumps(data.get('tamanios_disponibles', [])),
                          json.dumps(data.get('opciones_base', {})),
                          product_id))
                    conn.commit()
                    return jsonify({'success': True})
        except Exception as e:
            logger.error(f"Error actualizando personalización: {e}")
            return jsonify({'error': str(e)}), 500

# ==================== CONFIGURACIÓN DE PERSONALIZACIÓN (NUEVOS ENDPOINTS) ====================

@app.route('/api/tenant/<tenant_id>/personalizacion/configs', methods=['GET'])
@login_required
@tenant_owner_required
def get_configuraciones_personalizacion(tenant_id):
    """Obtiene todas las configuraciones de personalización del tenant"""
    try:
        solo_activos = request.args.get('activos', 'true').lower() == 'true'
        configs = schema_manager.get_configuraciones_personalizacion(tenant_id, solo_activos)
        return jsonify(configs)
    except Exception as e:
        logger.error(f'Error obteniendo configuraciones: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/configs', methods=['POST'])
@login_required
@tenant_owner_required
def create_configuracion_personalizacion(tenant_id):
    """Crea una nueva configuración de personalización"""
    try:
        data = request.json
        nombre = data.get('nombre')
        if not nombre:
            return jsonify({'error': 'El nombre es requerido'}), 400
        
        config_id = schema_manager.create_configuracion_personalizacion(
            tenant_id=tenant_id,
            nombre=nombre,
            descripcion=data.get('descripcion'),
            instrucciones_ia=data.get('instrucciones_ia')
        )
        
        return jsonify({
            'success': True,
            'message': 'Configuración creada exitosamente',
            'config_id': config_id
        }), 201
    except Exception as e:
        logger.error(f'Error creando configuración: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/configs/<int:config_id>', methods=['PUT'])
@login_required
@tenant_owner_required
def update_configuracion_personalizacion(tenant_id, config_id):
    """Actualiza una configuración de personalización"""
    try:
        data = request.json
        success = schema_manager.update_configuracion_personalizacion(
            tenant_id=tenant_id,
            config_id=config_id,
            nombre=data.get('nombre'),
            descripcion=data.get('descripcion'),
            activo=data.get('activo'),
            instrucciones_ia=data.get('instrucciones_ia')
        )
        
        if success:
            return jsonify({'success': True, 'message': 'Configuración actualizada'})
        else:
            return jsonify({'error': 'No se pudo actualizar la configuración'}), 400
    except Exception as e:
        logger.error(f'Error actualizando configuración: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/configs/<int:config_id>', methods=['DELETE'])
@login_required
@tenant_owner_required
def delete_configuracion_personalizacion(tenant_id, config_id):
    """Elimina una configuración de personalización"""
    try:
        success = schema_manager.delete_configuracion_personalizacion(tenant_id, config_id)
        
        if success:
            return jsonify({'success': True, 'message': 'Configuración eliminada'})
        else:
            return jsonify({'error': 'No se pudo eliminar la configuración'}), 400
    except Exception as e:
        logger.error(f'Error eliminando configuración: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/configs/<int:config_id>/atributos', methods=['GET'])
@login_required
@tenant_owner_required
def get_atributos_personalizacion(tenant_id, config_id):
    """Obtiene los atributos de una configuración de personalización"""
    try:
        solo_activos = request.args.get('activos', 'true').lower() == 'true'
        atributos = schema_manager.get_atributos_personalizacion(tenant_id, config_id, solo_activos)
        return jsonify(atributos)
    except Exception as e:
        logger.error(f'Error obteniendo atributos: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/atributos', methods=['POST'])
@login_required
@tenant_owner_required
def create_atributo_personalizacion(tenant_id):
    """Crea un nuevo atributo de personalización"""
    try:
        data = request.json
        config_id = data.get('config_id')
        nombre = data.get('nombre')
        tipo = data.get('tipo')
        pregunta = data.get('pregunta')
        
        if not config_id or not nombre or not tipo or not pregunta:
            return jsonify({'error': 'Faltan campos requeridos'}), 400
        
        attr_id = schema_manager.create_atributo_personalizacion(
            tenant_id=tenant_id,
            config_id=config_id,
            nombre=nombre,
            tipo=tipo,
            pregunta=pregunta,
            opciones=data.get('opciones'),
            requerido=data.get('requerido', True),
            precio_extra=data.get('precio_extra'),
            orden=data.get('orden', 0)
        )
        
        return jsonify({
            'success': True,
            'message': 'Atributo creado exitosamente',
            'attr_id': attr_id
        }), 201
    except Exception as e:
        logger.error(f'Error creando atributo: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/atributos/<int:attr_id>', methods=['PUT'])
@login_required
@tenant_owner_required
def update_atributo_personalizacion(tenant_id, attr_id):
    """Actualiza un atributo de personalización"""
    try:
        data = request.json
        success = schema_manager.update_atributo_personalizacion(
            tenant_id=tenant_id,
            attr_id=attr_id,
            nombre=data.get('nombre'),
            tipo=data.get('tipo'),
            opciones=data.get('opciones'),
            pregunta=data.get('pregunta'),
            requerido=data.get('requerido'),
            precio_extra=data.get('precio_extra'),
            orden=data.get('orden'),
            activo=data.get('activo')
        )
        
        if success:
            return jsonify({'success': True, 'message': 'Atributo actualizado'})
        else:
            return jsonify({'error': 'No se pudo actualizar el atributo'}), 400
    except Exception as e:
        logger.error(f'Error actualizando atributo: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/atributos/<int:attr_id>', methods=['DELETE'])
@login_required
@tenant_owner_required
def delete_atributo_personalizacion(tenant_id, attr_id):
    """Elimina un atributo de personalización"""
    try:
        success = schema_manager.delete_atributo_personalizacion(tenant_id, attr_id)
        
        if success:
            return jsonify({'success': True, 'message': 'Atributo eliminado'})
        else:
            return jsonify({'error': 'No se pudo eliminar el atributo'}), 400
    except Exception as e:
        logger.error(f'Error eliminando atributo: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/configs/<config_nombre>/completa', methods=['GET'])
@login_required
@tenant_owner_required
def get_configuracion_completa(tenant_id, config_nombre):
    """Obtiene una configuración completa con todos sus atributos"""
    try:
        config = schema_manager.get_configuracion_completa(tenant_id, config_nombre)
        if config:
            return jsonify(config)
        else:
            return jsonify({'error': 'Configuración no encontrada'}), 404
    except Exception as e:
        logger.error(f'Error obteniendo configuración completa: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/habilitar', methods=['PUT'])
@login_required
@tenant_owner_required
def habilitar_personalizacion_tenant(tenant_id):
    """Habilita o deshabilita la personalización para el tenant"""
    try:
        data = request.json
        habilitada = data.get('habilitada', True)
        result = tenant_repo.habilitar_personalizacion(tenant_id, habilitada)
        return jsonify(result)
    except Exception as e:
        logger.error(f'Error cambiando estado de personalización: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/activar-config', methods=['POST'])
@login_required
@tenant_owner_required
def activar_configuracion_personalizacion_tenant(tenant_id):
    """Activa una configuración de personalización para el tenant"""
    try:
        data = request.json
        config_id = data.get('config_id')
        if not config_id:
            return jsonify({'error': 'Se requiere config_id'}), 400
        
        result = tenant_repo.activar_configuracion_personalizacion(tenant_id, config_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f'Error activando configuración: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/personalizacion/desactivar-config', methods=['POST'])
@login_required
@tenant_owner_required
def desactivar_configuracion_personalizacion_tenant(tenant_id):
    """Desactiva una configuración de personalización para el tenant"""
    try:
        data = request.json
        config_id = data.get('config_id')
        if not config_id:
            return jsonify({'error': 'Se requiere config_id'}), 400
        
        result = tenant_repo.desactivar_configuracion_personalizacion(tenant_id, config_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f'Error desactivando configuración: {e}')
        return jsonify({'error': str(e)}), 500

# ======== Cambio SubProductos y personalizaciones ========

# ==================== PRODUCTOS CON ADICIONALES Y PERSONALIZACIONES ====================

@app.route('/api/tenant/<tenant_id>/productos/base', methods=['GET'])
@login_required
@tenant_owner_required
def get_productos_base(tenant_id):
    """Obtiene los productos base (no adicionales)"""
    try:
        productos = schema_manager.get_productos_base(tenant_id)
        return jsonify(productos)
    except Exception as e:
        logger.error(f'Error obteniendo productos base: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/productos/<producto_id>/adicionales', methods=['GET'])
@login_required
@tenant_owner_required
def get_adicionales_producto(tenant_id, producto_id):
    """Obtiene los adicionales disponibles para un producto base"""
    try:
        adicionales = schema_manager.get_adicionales_producto(tenant_id, producto_id)
        return jsonify(adicionales)
    except Exception as e:
        logger.error(f'Error obteniendo adicionales: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/productos/<producto_id>/personalizaciones', methods=['GET'])
@login_required
@tenant_owner_required
def get_personalizaciones_producto(tenant_id, producto_id):
    """Obtiene las personalizaciones para un producto base"""
    try:
        personalizaciones = schema_manager.get_personalizaciones_producto(tenant_id, producto_id)
        return jsonify(personalizaciones)
    except Exception as e:
        logger.error(f'Error obteniendo personalizaciones: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/producto/calcular', methods=['POST'])
@login_required
@tenant_owner_required
def calcular_precio_producto(tenant_id):
    """Calcula el precio de un producto base con sus adicionales"""
    try:
        data = request.json
        producto_id = data.get('producto_id')
        adicionales_ids = data.get('adicionales_ids', [])
        cantidades = data.get('cantidades', {})
        
        total = schema_manager.calcular_precio_con_adicionales(
            tenant_id, producto_id, adicionales_ids, cantidades
        )
        
        return jsonify({'total': total})
    except Exception as e:
        logger.error(f'Error calculando precio: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/adicionales', methods=['GET'])
@login_required
@tenant_owner_required
def get_todos_adicionales(tenant_id):
    """Obtiene todos los adicionales disponibles (para administración)"""
    try:
        schema_name = schema_manager._get_schema_name(tenant_id)
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT id, nombre, descripcion, precio, disponible
                    FROM "{schema_name}".productos 
                    WHERE es_base = false
                    ORDER BY nombre
                """)
                rows = cur.fetchall()
                adicionales = [{
                    'id': str(row[0]),
                    'nombre': row[1],
                    'descripcion': row[2] or '',
                    'precio': row[3],
                    'disponible': row[4]
                } for row in rows]
                return jsonify(adicionales)
    except Exception as e:
        logger.error(f'Error obteniendo adicionales: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/admin/add_adicional/<tenant_id>', methods=['POST', 'OPTIONS'])
@login_required
@tenant_owner_required
def add_adicional(tenant_id):
    """Agrega un nuevo adicional (producto con es_base=false)"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        nombre = data.get('nombre')
        if not nombre:
            return jsonify({'error': 'El nombre es requerido'}), 400
        
        schema_name = schema_manager._get_schema_name(tenant_id)
        adicional_id = str(uuid.uuid4())
        
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO "{schema_name}".productos 
                    (id, nombre, descripcion, precio, categoria, es_base, disponible)
                    VALUES (%s, %s, %s, %s, %s, false, true)
                """, (adicional_id, nombre, data.get('descripcion', ''), 
                      data.get('precio', 0), data.get('categoria', 'adicionales')))
            conn.commit()
        
        return jsonify({'success': True, 'message': 'Adicional agregado', 'id': adicional_id}), 201
    except Exception as e:
        logger.error(f'Error agregando adicional: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/admin/relacionar_adicional/<tenant_id>', methods=['POST', 'OPTIONS'])
@login_required
@tenant_owner_required
def relacionar_adicional(tenant_id):
    """Relaciona un adicional con un producto base"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.json
        producto_id = data.get('producto_id')
        adicional_id = data.get('adicional_id')
        cantidad_maxima = data.get('cantidad_maxima', 1)
        
        if not producto_id or not adicional_id:
            return jsonify({'error': 'Faltan producto_id o adicional_id'}), 400
        
        schema_name = schema_manager._get_schema_name(tenant_id)
        
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO "{schema_name}".producto_adicionales 
                    (producto_id, adicional_id, cantidad_maxima)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (producto_id, adicional_id) DO UPDATE
                    SET cantidad_maxima = EXCLUDED.cantidad_maxima
                """, (producto_id, adicional_id, cantidad_maxima))
            conn.commit()
        
        return jsonify({'success': True, 'message': 'Adicional relacionado'})
    except Exception as e:
        logger.error(f'Error relacionando adicional: {e}')
        return jsonify({'error': str(e)}), 500

# ==================== GESTIÓN DE CONTEXTO (ENTRENAMIENTO) ====================

@app.route('/api/tenant/<tenant_id>/contexto', methods=['GET'])
@login_required
@tenant_owner_required
def get_contexto_tenant(tenant_id):
    """Obtiene el contexto actual del tenant"""
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT instrucciones, horario, ubicacion, politicas, prompt_personalizado, 
                           menu_estructurado, updated_at
                    FROM public.tenant_context 
                    WHERE tenant_id = %s
                ''', (tenant_id,))
                row = cur.fetchone()
                
                if row:
                    menu = row[5] if row[5] else []
                    if isinstance(menu, str):
                        try:
                            menu = json.loads(menu)
                        except:
                            menu = []
                    
                    return jsonify({
                        'instrucciones': row[0] or '',
                        'horario': row[1] or '',
                        'ubicacion': row[2] or '',
                        'politicas': row[3] or '',
                        'prompt_personalizado': row[4] or '',
                        'productos': menu[:50] if menu else [],
                        'total_productos': len(menu) if menu else 0,
                        'updated_at': row[6] if row[6] else None
                    })
                else:
                    return jsonify({
                        'instrucciones': '',
                        'horario': '',
                        'ubicacion': '',
                        'politicas': '',
                        'prompt_personalizado': '',
                        'productos': [],
                        'total_productos': 0
                    })
    except Exception as e:
        logger.error(f'Error obteniendo contexto: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/contexto', methods=['PUT'])
@login_required
@tenant_owner_required
def update_contexto_tenant(tenant_id):
    """Actualiza el contexto del tenant (reemplaza o acumula según parámetro)"""
    try:
        data = request.json
        campo = data.get('campo')  # instrucciones, horario, ubicacion, politicas
        valor = data.get('valor', '')
        modo = data.get('modo', 'reemplazar')  # reemplazar, acumular, eliminar
        
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                # Obtener contexto actual
                cur.execute('''
                    SELECT instrucciones, horario, ubicacion, politicas, prompt_personalizado
                    FROM public.tenant_context 
                    WHERE tenant_id = %s
                ''', (tenant_id,))
                row = cur.fetchone()
                
                if not row:
                    # Crear registro inicial
                    cur.execute('''
                        INSERT INTO public.tenant_context (tenant_id, created_at, updated_at)
                        VALUES (%s, NOW(), NOW())
                    ''', (tenant_id,))
                    conn.commit()
                    row = (None, None, None, None, None)
                
                instrucciones_actual = row[0] or ''
                horario_actual = row[1] or ''
                ubicacion_actual = row[2] or ''
                politicas_actual = row[3] or ''
                prompt_actual = row[4] or ''
                
                # Aplicar según modo
                if modo == 'eliminar':
                    nuevo_valor = ''
                elif modo == 'acumular':
                    if valor and valor not in instrucciones_actual:
                        nuevo_valor = f"{instrucciones_actual}\n\n{valor}" if instrucciones_actual else valor
                    else:
                        nuevo_valor = instrucciones_actual
                else:  # reemplazar
                    nuevo_valor = valor
                
                # Actualizar el campo específico
                if campo == 'instrucciones':
                    cur.execute('''
                        UPDATE public.tenant_context 
                        SET instrucciones = %s, updated_at = NOW()
                        WHERE tenant_id = %s
                    ''', (nuevo_valor, tenant_id))
                elif campo == 'horario':
                    cur.execute('''
                        UPDATE public.tenant_context 
                        SET horario = %s, updated_at = NOW()
                        WHERE tenant_id = %s
                    ''', (nuevo_valor, tenant_id))
                elif campo == 'ubicacion':
                    cur.execute('''
                        UPDATE public.tenant_context 
                        SET ubicacion = %s, updated_at = NOW()
                        WHERE tenant_id = %s
                    ''', (nuevo_valor, tenant_id))
                elif campo == 'politicas':
                    cur.execute('''
                        UPDATE public.tenant_context 
                        SET politicas = %s, updated_at = NOW()
                        WHERE tenant_id = %s
                    ''', (nuevo_valor, tenant_id))
                elif campo == 'prompt_personalizado':
                    cur.execute('''
                        UPDATE public.tenant_context 
                        SET prompt_personalizado = %s, updated_at = NOW()
                        WHERE tenant_id = %s
                    ''', (nuevo_valor, tenant_id))
                
                conn.commit()
                
                return jsonify({
                    'success': True,
                    'message': f'Campo "{campo}" actualizado (modo: {modo})',
                    'nuevo_valor': nuevo_valor
                })
                
    except Exception as e:
        logger.error(f'Error actualizando contexto: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/contexto/limpiar', methods=['POST'])
@login_required
@tenant_owner_required
def limpiar_contexto_tenant(tenant_id):
    """Limpia completamente el contexto del tenant"""
    try:
        data = request.json
        campos = data.get('campos', ['instrucciones', 'horario', 'ubicacion', 'politicas'])
        
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                updates = []
                params = []
                
                if 'instrucciones' in campos:
                    updates.append("instrucciones = ''")
                if 'horario' in campos:
                    updates.append("horario = ''")
                if 'ubicacion' in campos:
                    updates.append("ubicacion = ''")
                if 'politicas' in campos:
                    updates.append("politicas = ''")
                
                if updates:
                    updates.append("updated_at = NOW()")
                    query = f"UPDATE public.tenant_context SET {', '.join(updates)} WHERE tenant_id = %s"
                    params.append(tenant_id)
                    cur.execute(query, params)
                    conn.commit()
                
                return jsonify({'success': True, 'message': f'Campos limpiados: {", ".join(campos)}'})
                
    except Exception as e:
        logger.error(f'Error limpiando contexto: {e}')
        return jsonify({'error': str(e)}), 500
    
# ====== Endpoint Adicional para Exportar Productos =======

@app.route('/api/tenant/<tenant_id>/menu/exportar', methods=['GET'])
@login_required
@tenant_owner_required
def exportar_productos(tenant_id):
    """Exporta productos a CSV"""
    try:
        productos = schema_manager.get_menu(tenant_id)
        
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Nombre', 'Precio', 'Categoría', 'Disponible', 'Destacado'])
        
        for p in productos:
            writer.writerow([p['nombre'], p['precio'], p.get('categoria', 'general'), p.get('disponible', True), p.get('destacado', False)])
        
        return output.getvalue(), 200, {
            'Content-Type': 'text/csv',
            'Content-Disposition': 'attachment; filename=productos.csv'
        }
        
    except Exception as e:
        logger.error(f'Error exportando productos: {e}')
        return jsonify({'error': str(e)}), 500

# ================= Recursos Visuales =====================
# ==================== RECURSOS VISUALES ====================

@app.route('/api/tenant/<tenant_id>/recursos', methods=['GET'])
@login_required
@tenant_owner_required
def get_recursos_visuales(tenant_id):
    """Obtiene todos los recursos visuales del tenant"""
    try:
        recursos = schema_manager.get_recursos_visuales(tenant_id)
        return jsonify(recursos)
    except Exception as e:
        logger.error(f'Error obteniendo recursos: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/recursos', methods=['POST'])
@login_required
@tenant_owner_required
def add_recurso_visual(tenant_id):
    """Agrega un nuevo recurso visual"""
    try:
        data = request.json
        nombre = data.get('nombre')
        tipo = data.get('tipo')
        
        if not nombre or not tipo:
            return jsonify({'error': 'nombre y tipo son requeridos'}), 400
        
        recurso_id = schema_manager.agregar_recurso_visual(
            tenant_id=tenant_id,
            nombre=nombre,
            tipo=tipo,
            url=data.get('url'),
            archivos=data.get('archivos'),
            descripcion=data.get('descripcion'),
            orden=data.get('orden', 0)
        )
        
        return jsonify({'success': True, 'id': recurso_id, 'message': 'Recurso agregado'})
    except Exception as e:
        logger.error(f'Error agregando recurso: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/recursos/<int:recurso_id>', methods=['PUT'])
@login_required
@tenant_owner_required
def update_recurso_visual(tenant_id, recurso_id):
    """Actualiza un recurso visual"""
    try:
        data = request.json
        success = schema_manager.update_recurso_visual(
            tenant_id=tenant_id,
            recurso_id=recurso_id,
            nombre=data.get('nombre'),
            descripcion=data.get('descripcion'),
            tipo=data.get('tipo'),
            url=data.get('url'),
            archivos=data.get('archivos'),
            orden=data.get('orden'),
            activo=data.get('activo')
        )
        
        if success:
            return jsonify({'success': True, 'message': 'Recurso actualizado'})
        else:
            return jsonify({'error': 'No se pudo actualizar'}), 400
    except Exception as e:
        logger.error(f'Error actualizando recurso: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenant/<tenant_id>/recursos/<int:recurso_id>', methods=['DELETE'])
@login_required
@tenant_owner_required
def delete_recurso_visual(tenant_id, recurso_id):
    """Elimina un recurso visual"""
    try:
        success = schema_manager.eliminar_recurso_visual(tenant_id, recurso_id)
        
        if success:
            return jsonify({'success': True, 'message': 'Recurso eliminado'})
        else:
            return jsonify({'error': 'No se pudo eliminar'}), 400
    except Exception as e:
        logger.error(f'Error eliminando recurso: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/admin/recursos', methods=['GET'])
@login_required
@tenant_owner_required_from_args
def admin_recursos():
    tenant_id = request.args.get('tenant_id')
    if not tenant_id:
        return redirect('/dashboard')
    
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return redirect('/dashboard')
    
    return render_template('admin/recursos.html', tenant=tenant)

@app.route('/api/recursos/compartir/<tenant_id>/<int:recurso_id>', methods=['POST'])
@login_required
@tenant_owner_required
def compartir_recurso_whatsapp(tenant_id, recurso_id):
    """Comparte un recurso visual por WhatsApp con un cliente"""
    try:
        data = request.json
        numero_cliente = data.get('numero')
        
        if not numero_cliente:
            return jsonify({'error': 'Número de teléfono requerido'}), 400
        
        # Obtener el recurso
        recursos = schema_manager.get_recursos_visuales(tenant_id)
        recurso = next((r for r in recursos if r['id'] == recurso_id), None)
        
        if not recurso:
            return jsonify({'error': 'Recurso no encontrado'}), 404
        
        # Obtener el tenant
        tenant = tenant_repo.find_by_id(tenant_id)
        if not tenant:
            return jsonify({'error': 'Negocio no encontrado'}), 404
        
        # Formatear mensaje según el tipo de recurso
        mensaje = formatear_mensaje_recurso(recurso)
        
        # Enviar por WhatsApp
        from whatsapp.client import whatsapp_client
        enviado = whatsapp_client.send_message(tenant, numero_cliente, mensaje)
        
        if enviado:
            # Guardar en conversación
            from whatsapp.message_handler import message_handler
            message_handler._guardar_conversacion(
                tenant_id, 
                numero_cliente, 
                f"📎 Enviado: {recurso['nombre']} - {recurso['url']}", 
                "Recurso compartido manualmente"
            )
            
            return jsonify({
                'success': True, 
                'message': f'Recurso "{recurso["nombre"]}" enviado a {numero_cliente}'
            })
        else:
            return jsonify({'error': 'No se pudo enviar el mensaje'}), 500
            
    except Exception as e:
        logger.error(f'Error compartiendo recurso: {e}')
        return jsonify({'error': str(e)}), 500

def formatear_mensaje_recurso(recurso):
    """Formatea el mensaje según el tipo de recurso"""
    nombre = recurso['nombre']
    url = recurso['url']
    descripcion = recurso.get('descripcion', '')
    
    # Emoji según tipo
    emojis = {
        'imagen': '🖼️',
        'video': '🎥',
        'pdf': '📄',
        'documento': '📁',
        'enlace': '🔗'
    }
    emoji = emojis.get(recurso.get('tipo', 'enlace'), '📎')
    
    # Construir mensaje
    mensaje = f"{emoji} *{nombre}*\n\n"
    
    if descripcion:
        mensaje += f"{descripcion}\n\n"
    
    mensaje += f"🔗 {url}\n\n"
    mensaje += "_Recurso compartido desde el panel de administración._"
    
    return mensaje

# ==================== DEBUG ENDPOINTS ====================

@app.route('/debug/test', methods=['GET'])
def debug_test():
    return jsonify({'status': 'ok', 'message': 'API funcionando correctamente'})



@app.route('/debug/tesseract', methods=['GET'])
def test_tesseract():
    import subprocess
    try:
        result = subprocess.run(['tesseract', '--version'], capture_output=True, text=True)
        return {'tesseract_installed': True, 'version': result.stdout.split('\n')[0] if result.stdout else 'unknown'}
    except Exception as e:
        return {'tesseract_installed': False, 'error': str(e)}, 500

@app.route('/debug/webhook_info', methods=['GET'])
def webhook_info():
    tenants = tenant_repo.get_all()
    return {'webhook_url': 'https://whatsapp-mvp-docker.onrender.com/webhook', 'tenants_registrados': [{'nombre': t['nombre'], 'phone_id': t['phone_id']} for t in tenants]}

@app.route('/super/admin/debug-session', methods=['GET'])
def debug_session():
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    return jsonify({'session': dict(session), 'rol_sistema': session.get('rol_sistema'), 'usuario_id': session.get('usuario_id')})

@app.route('/debug/send-test-message', methods=['GET'])
def send_test_message():
    tenants = tenant_repo.get_all()
    if not tenants:
        return jsonify({'error': 'No hay tenants'}), 404
    tenant = tenants[0]
    numero = "573155692656"
    from whatsapp.client import whatsapp_client
    result = whatsapp_client.send_message(tenant, numero, "Este es un mensaje de prueba desde el sistema")
    return jsonify({'success': result, 'tenant': tenant['nombre'], 'phone_id': tenant['phone_id'], 'numero_enviado': numero})

@app.route('/debug/check-token/<tenant_id>', methods=['GET'])
def check_token(tenant_id):
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant no encontrado'}), 404
    url = f"https://graph.facebook.com/v18.0/{tenant['phone_id']}"
    headers = {"Authorization": f"Bearer {tenant['token']}"}
    try:
        response = requests.get(url, headers=headers)
        return jsonify({'status_code': response.status_code, 'response': response.json() if response.status_code == 200 else response.text, 'token_valido': response.status_code == 200})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/test-email-now', methods=['GET'])
def test_email_now():
    from utils.email_brevo import email_sender
    email_to = "areyescali@hotmail.com"
    codigo = "123456"
    nombre = "Test"
    result = email_sender.enviar_codigo_verificacion(email_to, codigo, nombre)
    return jsonify({'success': result, 'message': 'Email enviado' if result else 'Error al enviar', 'api_key_configured': bool(os.environ.get('BREVO_API_KEY'))})

def enviar_notificacion_email(tenant, pedido_id):
    from utils.email_brevo import email_sender
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT u.email FROM public.usuarios u JOIN public.usuario_negocio un ON u.id = un.usuario_id WHERE un.tenant_id = %s AND un.rol_id = 1", (tenant['id'],))
            row = cur.fetchone()
            if row:
                email_sender.enviar_notificacion_pedido(row[0], pedido_id, tenant['nombre'])

@app.route('/debug/asignar_negocio', methods=['GET'])
def debug_asignar_negocio():
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    tenants = tenant_repo.get_all()
    if not tenants:
        return jsonify({'error': 'No hay negocios disponibles'}), 404
    tenant = tenants[0]
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM public.usuario_negocio WHERE usuario_id = %s AND tenant_id = %s", (session['usuario_id'], tenant['id']))
            if cur.fetchone():
                return jsonify({'message': f'El negocio {tenant["nombre"]} ya está asociado'})
            cur.execute("SELECT id FROM public.roles_negocio WHERE nombre = 'owner'")
            rol_row = cur.fetchone()
            if not rol_row:
                return jsonify({'error': 'No se encontró el rol owner'}), 500
            rol_owner_id = rol_row[0]
            cur.execute("INSERT INTO public.usuario_negocio (usuario_id, tenant_id, rol_id, invitado_por) VALUES (%s, %s, %s, %s)", (session['usuario_id'], tenant['id'], rol_owner_id, session['usuario_id']))
        conn.commit()
    return jsonify({'success': True, 'message': f'Negocio "{tenant["nombre"]}" asignado al usuario {session["email"]}', 'tenant_id': tenant['id']})

@app.route('/debug/contexto/<tenant_id>', methods=['GET'])
def debug_contexto(tenant_id):
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM public.tenant_context WHERE tenant_id = %s", (tenant_id,))
            row = cur.fetchone()
            if row:
                columns = [desc[0] for desc in cur.description]
                return jsonify(dict(zip(columns, row)))
            return jsonify({'error': 'No hay contexto'}), 404

@app.route('/debug/crear_tabla_conversaciones', methods=['GET'])
def crear_tabla_conversaciones():
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS public.conversaciones_ia (
                        id SERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        cliente_numero TEXT NOT NULL,
                        mensaje TEXT NOT NULL,
                        respuesta TEXT,
                        tipo VARCHAR(20) DEFAULT 'cliente',
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_conversaciones_tenant ON public.conversaciones_ia(tenant_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_conversaciones_cliente ON public.conversaciones_ia(cliente_numero)")
            conn.commit()
        return jsonify({'success': True, 'message': 'Tabla creada'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/verificar_tabla_conversaciones', methods=['GET'])
def verificar_tabla_conversaciones():
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'conversaciones_ia'")
                existe = cur.fetchone()[0] > 0
                
                if existe:
                    cur.execute("SELECT COUNT(*) FROM public.conversaciones_ia")
                    total = cur.fetchone()[0]
                    return jsonify({'tabla_existe': True, 'total_registros': total})
                else:
                    return jsonify({'tabla_existe': False, 'error': 'Tabla no existe'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/crear_tabla_carritos', methods=['GET'])
def crear_tabla_carritos():
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS public.carritos (
                        id SERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        cliente_numero TEXT NOT NULL,
                        items JSONB DEFAULT '[]',
                        total INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                conn.commit()
        return jsonify({'success': True, 'message': 'Tabla carritos creada'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/ver_historial/<tenant_id>/<cliente_numero>', methods=['GET'])
def ver_historial(tenant_id, cliente_numero):
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT mensaje, respuesta, created_at 
                    FROM public.conversaciones_ia 
                    WHERE tenant_id = %s AND cliente_numero = %s 
                    ORDER BY created_at ASC
                """, (tenant_id, cliente_numero))
                rows = cur.fetchall()
                historial = [{'mensaje': r[0], 'respuesta': r[1], 'fecha': r[2]} for r in rows]
                return jsonify({'historial': historial, 'total': len(historial)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/ver_pedidos_directo/<tenant_id>', methods=['GET'])
def debug_ver_pedidos_directo(tenant_id):
    schema_name = _get_schema_name(tenant_id)
    try:
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT numero_pedido, cliente_numero, items, total, estado, created_at FROM "{schema_name}".pedidos ORDER BY created_at DESC')
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                pedidos = [dict(zip(columns, row)) for row in rows]
                return jsonify({
                    'total': len(pedidos),
                    'pedidos': pedidos
                })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/ver_pedidos_recientes/<tenant_id>', methods=['GET'])
def ver_pedidos_recientes(tenant_id):
    schema_name = _get_schema_name(tenant_id)
    try:
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT * FROM "{schema_name}".pedidos ORDER BY created_at DESC LIMIT 5')
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                pedidos = [dict(zip(columns, row)) for row in rows]
                return jsonify(pedidos)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/ver_tablas/<tenant_id>', methods=['GET'])
def debug_ver_tablas(tenant_id):
    schema_name = _get_schema_name(tenant_id)
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s
                """, (schema_name,))
                tables = [row[0] for row in cur.fetchall()]
                return jsonify({'schema': schema_name, 'tablas': tables})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/menu_tenant/<tenant_id>', methods=['GET'])
def debug_menu_tenant(tenant_id):
    try:
        menu = schema_manager.get_menu(tenant_id)
        return jsonify({
            'total': len(menu),
            'productos': [{'nombre': p['nombre'], 'precio': p['precio']} for p in menu[:10]]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/ver_carrito/<tenant_id>/<numero>', methods=['GET'])
def debug_ver_carrito(tenant_id, numero):
    from whatsapp.message_handler import message_handler
    carrito = message_handler._carritos.get(numero, {})
    return jsonify({
        'carrito': carrito,
        'tiene_items': len(carrito.get('items', [])) > 0,
        'total_items': len(carrito.get('items', [])),
        'total_monto': carrito.get('total', 0)
    })

@app.route('/debug/carrito/<tenant_id>/<numero>', methods=['GET'])
def debug_carrito(tenant_id, numero):
    from whatsapp.message_handler import message_handler
    carrito = message_handler._cargar_carrito(tenant_id, numero)
    return jsonify({
        'items': carrito.get('items', []),
        'total': carrito.get('total', 0),
        'cantidad_items': len(carrito.get('items', []))
    })

@app.route('/debug/ver_carrito_bd/<tenant_id>/<cliente_numero>', methods=['GET'])
def debug_ver_carrito_bd(tenant_id, cliente_numero):
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT items, total, created_at, updated_at 
                    FROM public.carritos 
                    WHERE tenant_id = %s AND cliente_numero = %s
                """, (tenant_id, cliente_numero))
                row = cur.fetchone()
                if row:
                    items = row[0]
                    if isinstance(items, str):
                        items = json.loads(items)
                    return jsonify({
                        'items': items,
                        'total': row[1],
                        'created_at': row[2],
                        'updated_at': row[3]
                    })
                return jsonify({'items': [], 'total': 0, 'message': 'Carrito vacío'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/migrar_todos_tenants', methods=['GET'])
def migrar_todos_tenants():
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    
    tenants = tenant_repo.get_all()
    resultados = []
    
    for tenant in tenants:
        tenant_id = tenant['id']
        schema_name = tenant.get('schema_name')
        if not schema_name:
            schema_name = f"tenant_{tenant_id.replace('-', '_')}"
        
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'''
                    CREATE TABLE IF NOT EXISTS "{schema_name}".clientes (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        numero_telefono TEXT UNIQUE NOT NULL,
                        nombre TEXT,
                        cc TEXT,
                        email TEXT,
                        direccion TEXT,
                        direccion_despacho TEXT,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                    ''')
                    
                    cur.execute(f'''
                    DO $$ 
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{schema_name}' AND table_name = 'pedidos' AND column_name = 'cliente_id') THEN
                            ALTER TABLE "{schema_name}".pedidos ADD COLUMN cliente_id UUID REFERENCES "{schema_name}".clientes(id);
                        END IF;
                    END $$;
                    ''')
                    
                    cur.execute(f'''
                    DO $$ 
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{schema_name}' AND table_name = 'pedidos' AND column_name = 'numero_pedido') THEN
                            ALTER TABLE "{schema_name}".pedidos ADD COLUMN numero_pedido TEXT;
                            ALTER TABLE "{schema_name}".pedidos ADD COLUMN secuencial INTEGER;
                        END IF;
                    END $$;
                    ''')
                    
                    conn.commit()
                    resultados.append({'tenant': tenant_id, 'status': 'ok'})
        except Exception as e:
            resultados.append({'tenant': tenant_id, 'status': 'error', 'error': str(e)})
    return jsonify({'resultados': resultados, 'total': len(tenants)})

@app.route('/test-css')
def test_css():
    return '''
    <html>
        <head>
            <link rel="stylesheet" href="/static/css/style.css">
        </head>
        <body>
            <div class="navbar">
                <div>Test</div>
            </div>
            <div class="card">
                <p>Si ves esto con estilos, el CSS funciona</p>
            </div>
            <button class="btn">Botón de prueba</button>
        </body>
    </html>
    '''

@app.route('/api/check-session', methods=['GET'])
def check_session():
    """Verifica si la sesión está activa"""
    if 'usuario_id' in session:
        return jsonify({
            'authenticated': True, 
            'usuario_id': session['usuario_id'],
            'email': session.get('email'),
            'nombre': session.get('nombre')
        })
    return jsonify({'authenticated': False}), 401

@app.route('/debug/migrar_recursos_visuales', methods=['GET'])
def migrar_recursos_visuales():
    """Agrega la columna updated_at a la tabla recursos_visuales de todos los tenants"""
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    
    tenants = tenant_repo.get_all()
    resultados = []
    
    for tenant in tenants:
        tenant_id = tenant['id']
        schema_name = tenant.get('schema_name')
        if not schema_name:
            schema_name = f"tenant_{tenant_id.replace('-', '_')}"
        
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Verificar si la tabla recursos_visuales existe
                    cur.execute(f"""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_schema = '{schema_name}' 
                            AND table_name = 'recursos_visuales'
                        )
                    """)
                    tabla_existe = cur.fetchone()[0]
                    
                    if not tabla_existe:
                        resultados.append({
                            'tenant': tenant_id, 
                            'status': 'tabla no existe, omitiendo'
                        })
                        continue
                    
                    # Verificar si la columna updated_at existe
                    cur.execute(f"""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_schema = '{schema_name}' 
                            AND table_name = 'recursos_visuales' 
                            AND column_name = 'updated_at'
                        )
                    """)
                    columna_existe = cur.fetchone()[0]
                    
                    if not columna_existe:
                        cur.execute(f"""
                            ALTER TABLE "{schema_name}".recursos_visuales 
                            ADD COLUMN updated_at TIMESTAMP DEFAULT NOW()
                        """)
                        conn.commit()
                        resultados.append({
                            'tenant': tenant_id, 
                            'nombre': tenant.get('nombre'),
                            'status': '✅ columna updated_at agregada'
                        })
                    else:
                        resultados.append({
                            'tenant': tenant_id, 
                            'nombre': tenant.get('nombre'),
                            'status': 'ℹ️ columna ya existe'
                        })
        except Exception as e:
            resultados.append({
                'tenant': tenant_id, 
                'nombre': tenant.get('nombre'),
                'status': '❌ error', 
                'error': str(e)
            })
    
    # Resumen
    agregadas = sum(1 for r in resultados if 'agregada' in r.get('status', ''))
    existentes = sum(1 for r in resultados if 'ya existe' in r.get('status', ''))
    errores = sum(1 for r in resultados if 'error' in r.get('status', ''))
    omitidas = sum(1 for r in resultados if 'omitindo' in r.get('status', ''))
    
    return jsonify({
        'resumen': {
            'total_tenants': len(tenants),
            'columnas_agregadas': agregadas,
            'columnas_existentes': existentes,
            'errores': errores,
            'omitidas': omitidas
        },
        'detalles': resultados
    })

if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)