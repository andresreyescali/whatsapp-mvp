import os
import json
import secrets
import time
import requests
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

setup_logging()

app = Flask(__name__, template_folder='web/templates')

# Configuración de sesión
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Configurar CORS
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
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

# ==================== PÁGINAS PÚBLICAS ====================

@app.route('/')
def landing():
    """Página de inicio"""
    return render_template('landing.html')

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
    """Página de login para super administrador"""
    return render_template('super_admin_login.html')

@app.route('/super/admin/login', methods=['POST'])
def super_admin_login():
    """Login especial para super admin (con credenciales especiales)"""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    # Verificar credenciales de super admin
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
    """Verifica si el usuario actual es super admin"""
    if session.get('rol_sistema') == 'super_admin':
        return jsonify({'authenticated': True, 'email': session.get('email')})
    return jsonify({'authenticated': False})

@app.route('/super/admin/dashboard')
def super_admin_dashboard():
    """Panel de super administrador"""
    if session.get('rol_sistema') != 'super_admin':
        return redirect('/super/admin/login-page')
    
    return render_template('super_admin.html')

@app.route('/super/admin/usuarios', methods=['GET'])
def super_admin_usuarios():
    """Lista todos los usuarios (solo super_admin)"""
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    
    usuarios = auth_manager.get_all_usuarios()
    return jsonify(usuarios)

@app.route('/super/admin/negocios', methods=['GET'])
def super_admin_negocios():
    """Lista todos los negocios (solo super_admin)"""
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    
    negocios = auth_manager.get_all_negocios()
    return jsonify(negocios)

@app.route('/super/admin/usuario/<usuario_id>', methods=['PUT', 'OPTIONS'])
def super_admin_update_usuario(usuario_id):
    """Actualiza un usuario (solo super_admin)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Verificar autenticación de super admin
    if session.get('rol_sistema') != 'super_admin':
        logger.warning(f'Intento no autorizado de actualización: session={dict(session)}')
        return jsonify({'error': 'No autorizado. Debes iniciar sesión como Super Administrador.'}), 403
    
    try:
        data = request.json
        logger.info(f'Super Admin actualizando usuario {usuario_id}: {data}')
        
        result = auth_manager.actualizar_usuario(usuario_id, data)
        
        if result.get('success'):
            return jsonify({'success': True, 'message': result.get('message', 'Usuario actualizado')})
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Error al actualizar')}), 400
            
    except Exception as e:
        logger.error(f'Error actualizando usuario: {e}')
        return jsonify({'error': str(e)}), 500
    
@app.route('/super/admin/usuario/<usuario_id>', methods=['DELETE'])
def super_admin_delete_usuario(usuario_id):
    """Elimina un usuario (solo super_admin)"""
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    
    result = auth_manager.eliminar_usuario(usuario_id)
    return jsonify(result)

@app.route('/super/admin/debug', methods=['GET'])
def super_admin_debug():
    """Diagnóstico para super admin"""
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.usuarios")
            total_usuarios = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM public.tenants")
            total_negocios = cur.fetchone()[0]
            
            return jsonify({
                'total_usuarios': total_usuarios,
                'total_negocios': total_negocios,
                'message': 'Si ves números aquí, los datos existen'
            })

# ==================== AUTH ENDPOINTS (Usuarios normales) ====================

@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    """Registro de nuevo usuario"""
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
    """Login de usuario normal"""
    data = request.json
    result = auth_manager.login(data.get('email'), data.get('password'))
    if result.get('success'):
        session['usuario_id'] = result['usuario_id']
        session['email'] = result['email']
        session['nombre'] = result.get('nombre')
        session['rol_sistema'] = result.get('rol_sistema', 'admin_cliente')
    return jsonify(result)

@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """Logout de usuario"""
    session.clear()
    return jsonify({'success': True})

# ==================== PERFIL DE USUARIO ====================

@app.route('/api/usuario/perfil', methods=['GET'])
def get_perfil():
    """Obtiene el perfil del usuario actual"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
        return jsonify({'error': 'No autenticado'}), 401
    
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT id, email, nombre_completo, telefono, created_at
                FROM public.usuarios WHERE id = %s
            ''', (session['usuario_id'],))
            row = cur.fetchone()
            if row:
                return jsonify({
                    'id': row[0],
                    'email': row[1],
                    'nombre': row[2],
                    'telefono': row[3],
                    'created_at': row[4]
                })
    return jsonify({'error': 'Usuario no encontrado'}), 404

@app.route('/api/usuario/perfil', methods=['PUT'])
def update_perfil():
    """Actualiza el perfil del usuario actual"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
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
                cur.execute("SELECT id FROM public.usuarios WHERE email = %s AND id != %s", 
                           (data['email'], session['usuario_id']))
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
def dashboard():
    """Dashboard del usuario (múltiples negocios)"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
        return redirect('/')
    
    usuario = {
        'id': session['usuario_id'],
        'email': session['email'],
        'nombre': session.get('nombre')
    }
    negocios = auth_manager.get_negocios_usuario(session['usuario_id'])
    
    return render_template('dashboard_usuario.html', usuario=usuario, negocios=negocios)

# ==================== NEGOCIOS (TENANTS) ====================

@app.route('/api/negocio/registrar', methods=['POST'])
def api_registrar_negocio():
    """Registro de nuevo negocio por usuario autenticado"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
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
def api_verificar_negocio():
    """Verificación de negocio"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
        return jsonify({'success': False, 'error': 'No autenticado'}), 401
    
    data = request.json
    result = auth_manager.verificar_negocio(
        tenant_id=data.get('tenant_id'),
        codigo=data.get('codigo')
    )
    return jsonify(result)

@app.route('/api/negocio/reenviar_codigo/<tenant_id>', methods=['POST'])
def reenviar_codigo(tenant_id):
    """Reenvía el código de verificación por WhatsApp"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
        return jsonify({'error': 'No autenticado'}), 401
    
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Negocio no encontrado'}), 404
    
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT codigo_verificacion FROM public.verificacion_negocio 
                WHERE tenant_id = %s AND verificado = false
            ''', (tenant_id,))
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
    
    enviado = auth_manager.enviar_codigo_whatsapp(
        tenant['phone_id'], tenant['token'], codigo, telefono
    )
    
    if enviado:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    UPDATE public.verificacion_negocio SET codigo_enviado = NOW()
                    WHERE tenant_id = %s
                ''', (tenant_id,))
            conn.commit()
        return jsonify({'success': True, 'message': 'Código reenviado exitosamente'})
    else:
        return jsonify({'error': 'Error al enviar el código'}), 500

# ==================== ROLES Y USUARIOS POR NEGOCIO ====================

@app.route('/api/negocio/<tenant_id>/usuarios', methods=['GET'])
def get_usuarios_negocio(tenant_id):
    """Obtiene todos los usuarios de un negocio"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
        return jsonify({'error': 'No autenticado'}), 401
    
    usuarios = auth_manager.get_usuarios_negocio(tenant_id)
    mi_rol = auth_manager.get_rol_negocio(session['usuario_id'], tenant_id)
    
    return jsonify({
        'usuarios': usuarios,
        'mi_rol': mi_rol,
        'puedo_invitar': auth_manager.verificar_permiso(session['usuario_id'], tenant_id, 'invitar_usuarios')
    })

@app.route('/api/negocio/<tenant_id>/invitar', methods=['POST'])
def invitar_usuario(tenant_id):
    """Invita a un usuario a un negocio"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
        return jsonify({'error': 'No autenticado'}), 401
    
    data = request.json
    result = auth_manager.invitar_usuario(
        session['usuario_id'], tenant_id, data.get('email'), data.get('rol', 'viewer')
    )
    return jsonify(result)

@app.route('/api/negocio/<tenant_id>/usuarios/<usuario_id>', methods=['DELETE'])
def remover_usuario(tenant_id, usuario_id):
    """Remueve un usuario de un negocio"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
        return jsonify({'error': 'No autenticado'}), 401
    
    result = auth_manager.remover_usuario(session['usuario_id'], tenant_id, usuario_id)
    return jsonify(result)

@app.route('/api/negocio/<tenant_id>/usuarios/<usuario_id>/rol', methods=['PUT'])
def cambiar_rol_usuario(tenant_id, usuario_id):
    """Cambia el rol de un usuario en un negocio"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
        return jsonify({'error': 'No autenticado'}), 401
    
    data = request.json
    result = auth_manager.cambiar_rol_usuario(
        session['usuario_id'], tenant_id, usuario_id, data.get('rol')
    )
    return jsonify(result)

@app.route('/api/negocio/<tenant_id>/permisos', methods=['GET'])
def verificar_permisos(tenant_id):
    """Verifica los permisos del usuario actual en el negocio"""
    if 'usuario_id' not in session or session['usuario_id'] == 'super_admin':
        return jsonify({'error': 'No autenticado'}), 401
    
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
    """Registro de tenant (para onboarding manual)"""
    return register_new_tenant()

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok', 'message': 'WhatsApp SaaS is running'}

# ==================== ADMIN (PANEL ANTIGUO) ====================

@app.route('/admin/tenants')
def list_tenants():
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
def admin_menu():
    tenant_id = request.args.get('tenant_id')
    if not tenant_id:
        return "Se requiere tenant_id", 400
    
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return f"Tenant no encontrado: {tenant_id}", 404
    
    return render_template('menu.html', tenant=tenant)

# ==================== PRODUCTOS (CRUD) ====================

@app.route('/api/tenant/<tenant_id>/menu', methods=['GET'])
def get_tenant_menu(tenant_id):
    try:
        menu = schema_manager.get_menu(tenant_id)
        return jsonify(menu)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tenant/<tenant_id>/config', methods=['GET'])
def get_tenant_config(tenant_id):
    try:
        tenant = tenant_repo.find_by_id(tenant_id)
        if not tenant:
            return jsonify({'error': 'Tenant no encontrado'}), 404
        return jsonify({'usar_ia': tenant.get('usar_ia', False)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tenant/<tenant_id>/config/ia', methods=['PUT', 'OPTIONS'])
def update_tenant_ia(tenant_id):
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
def add_product(tenant_id):
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        nombre = data.get('nombre')
        precio = data.get('precio')
        if not nombre or not precio:
            return jsonify({'error': 'Faltan nombre o precio'}), 400
        product_id = schema_manager.add_product(
            tenant_id, nombre, int(precio),
            data.get('descripcion', ''),
            data.get('categoria', 'general')
        )
        return jsonify({'status': 'ok', 'product_id': product_id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/delete_product/<tenant_id>/<product_id>', methods=['DELETE', 'OPTIONS'])
def delete_product(tenant_id, product_id):
    if request.method == 'OPTIONS':
        return '', 200
    try:
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {tenant_id}.productos WHERE id = %s", (product_id,))
            conn.commit()
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/update_product/<tenant_id>/<product_id>', methods=['PUT', 'OPTIONS'])
def update_product(tenant_id, product_id):
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.json
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {tenant_id}.productos 
                    SET nombre = %s, descripcion = %s, precio = %s, categoria = %s, disponible = %s
                    WHERE id = %s
                """, (
                    data.get('nombre'), data.get('descripcion'), data.get('precio'),
                    data.get('categoria', 'general'), data.get('disponible', True), product_id
                ))
            conn.commit()
        return jsonify({'status': 'ok', 'message': 'Producto actualizado'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/toggle_product/<tenant_id>/<product_id>', methods=['PUT', 'OPTIONS'])
def toggle_product(tenant_id, product_id):
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.json
        disponible = data.get('disponible', True)
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE {tenant_id}.productos SET disponible = %s WHERE id = %s", (disponible, product_id))
            conn.commit()
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/update_tenant/<tenant_id>', methods=['PUT', 'OPTIONS'])
def update_tenant(tenant_id):
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.json
        tenant_repo.update_tenant(
            tenant_id, data.get('nombre'), data.get('phone_id'),
            data.get('token'), data.get('usar_ia', False)
        )
        return jsonify({'status': 'ok', 'message': 'Tenant actualizado'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/delete_tenant/<tenant_id>', methods=['DELETE', 'OPTIONS'])
def delete_tenant(tenant_id):
    if request.method == 'OPTIONS':
        return '', 200
    try:
        tenant = tenant_repo.find_by_id(tenant_id)
        if not tenant:
            return jsonify({'error': 'Tenant no encontrado'}), 404
        tenant_repo.delete(tenant_id)
        return jsonify({'status': 'ok', 'message': 'Tenant eliminado'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== AI TRAINING ====================

@app.route('/admin/train/<tenant_id>', methods=['GET', 'POST'])
def train_ia(tenant_id):
    if request.method == 'GET':
        return render_template('train.html', tenant_id=tenant_id)
    
    try:
        data = request.json
        tipo = data.get('tipo')
        
        if tipo == 'imagen':
            resultado = trainer.procesar_imagen(data.get('imagen'))
        else:
            resultado = trainer.procesar_texto(data.get('texto'))
        
        if not resultado:
            return jsonify({'error': 'No se pudo procesar'}), 500
        
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                prompt_personalizado = trainer.generar_prompt_personalizado(resultado)
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
                ''', (
                    tenant_id,
                    json.dumps(resultado.get('productos', [])),
                    resultado.get('instrucciones_adicionales', ''),
                    resultado.get('horario', ''),
                    resultado.get('ubicacion', ''),
                    resultado.get('politicas', ''),
                    prompt_personalizado
                ))
            conn.commit()
        
        for producto in resultado.get('productos', []):
            if producto.get('nombre') and producto.get('precio'):
                try:
                    schema_manager.add_product(
                        tenant_id, producto.get('nombre'), int(producto.get('precio', 0)),
                        producto.get('descripcion', ''), producto.get('categoria', 'general')
                    )
                except Exception as e:
                    logger.warning(f'Error guardando producto: {e}')
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tenant/<tenant_id>/context', methods=['GET'])
def get_tenant_context(tenant_id):
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
    return {
        'webhook_url': 'https://whatsapp-mvp-docker.onrender.com/webhook',
        'tenants_registrados': [{'nombre': t['nombre'], 'phone_id': t['phone_id']} for t in tenants]
    }


@app.route('/super/admin/debug-session', methods=['GET'])
def debug_session():
    """Muestra la sesión actual (solo para diagnóstico)"""
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    
    return jsonify({
        'session': dict(session),
        'rol_sistema': session.get('rol_sistema'),
        'usuario_id': session.get('usuario_id')
    })

@app.route('/debug/send-test-message', methods=['GET'])
def send_test_message():
    """Envía un mensaje de prueba al número configurado"""
    # Obtener el primer tenant
    tenants = tenant_repo.get_all()
    if not tenants:
        return jsonify({'error': 'No hay tenants'}), 404
    
    tenant = tenants[0]
    numero = "573155692656"  # Tu número de prueba
    
    from whatsapp.client import whatsapp_client
    result = whatsapp_client.send_message(tenant, numero, "Este es un mensaje de prueba desde el sistema")
    
    return jsonify({
        'success': result,
        'tenant': tenant['nombre'],
        'phone_id': tenant['phone_id'],
        'numero_enviado': numero
    })

@app.route('/debug/check-token/<tenant_id>', methods=['GET'])
def check_token(tenant_id):
    """Verifica si el token de WhatsApp es válido"""
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant no encontrado'}), 404
    
    # Probar obtener información del número
    url = f"https://graph.facebook.com/v18.0/{tenant['phone_id']}"
    headers = {"Authorization": f"Bearer {tenant['token']}"}
    
    try:
        response = requests.get(url, headers=headers)
        return jsonify({
            'status_code': response.status_code,
            'response': response.json() if response.status_code == 200 else response.text,
            'token_valido': response.status_code == 200
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/debug/test-email-only', methods=['GET'])
def test_email_only():
    """Prueba solo el envío de email"""
    from utils.email_brevo import email_sender
    
    result = email_sender.enviar_codigo_verificacion(
        email_to="tu-email@gmail.com",  # Cambia por tu email
        codigo="123456",
        nombre_negocio="Test Negocio"
    )
    
    return jsonify({'success': result})

if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)