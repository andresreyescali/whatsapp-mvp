import os
import json
import secrets
import time
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

# ==================== SUPER ADMIN ENDPOINTS ====================

@app.route('/super/admin/login', methods=['POST'])
def super_admin_login():
    """Login especial para super admin (con credenciales especiales)"""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    # Verificar credenciales de super admin
    if email == 'admin@whatsappbotsaas.com' and password == os.environ.get('SUPER_ADMIN_PASSWORD', 'Admin123!'):
        session['usuario_id'] = 'super_admin'
        session['email'] = email
        session['rol_sistema'] = 'super_admin'
        return jsonify({'success': True, 'rol': 'super_admin'})
    
    return jsonify({'success': False, 'error': 'Credenciales incorrectas'})

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

@app.route('/super/admin/usuario/<usuario_id>', methods=['PUT'])
def super_admin_update_usuario(usuario_id):
    """Actualiza un usuario (solo super_admin)"""
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    
    data = request.json
    result = auth_manager.actualizar_usuario(usuario_id, data)
    return jsonify(result)

@app.route('/super/admin/usuario/<usuario_id>', methods=['DELETE'])
def super_admin_delete_usuario(usuario_id):
    """Elimina un usuario (solo super_admin)"""
    if session.get('rol_sistema') != 'super_admin':
        return jsonify({'error': 'No autorizado'}), 403
    
    result = auth_manager.eliminar_usuario(usuario_id)
    return jsonify(result)

@app.route('/super/admin/dashboard')
def super_admin_dashboard():
    """Panel de super administrador"""
    if session.get('rol_sistema') != 'super_admin':
        return redirect('/')
    
    return render_template('super_admin.html')

# ==================== AUTH ENDPOINTS ====================

@app.route('/')
def landing():
    """Página de inicio"""
    return render_template('landing.html')

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
    """Login de usuario"""
    data = request.json
    result = auth_manager.login(data.get('email'), data.get('password'))
    if result.get('success'):
        session['usuario_id'] = result['usuario_id']
        session['email'] = result['email']
        session['nombre'] = result.get('nombre')
    return jsonify(result)

@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """Logout de usuario"""
    session.clear()
    return jsonify({'success': True})

@app.route('/dashboard')
def dashboard():
    """Dashboard del usuario (múltiples negocios)"""
    if 'usuario_id' not in session:
        return redirect('/')
    
    usuario = {
        'id': session['usuario_id'],
        'email': session['email'],
        'nombre': session.get('nombre')
    }
    negocios = auth_manager.get_negocios_usuario(session['usuario_id'])
    
    return render_template('dashboard_usuario.html', usuario=usuario, negocios=negocios)

@app.route('/api/negocio/registrar', methods=['POST'])
def api_registrar_negocio():
    """Registro de nuevo negocio por usuario autenticado"""
    if 'usuario_id' not in session:
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
    if 'usuario_id' not in session:
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
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    
    # Obtener información del negocio
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Negocio no encontrado'}), 404
    
    # Obtener código de verificación
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
    
    # Obtener teléfono del usuario
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT telefono FROM public.usuarios WHERE id = %s", (session['usuario_id'],))
            row = cur.fetchone()
            telefono = row[0] if row else None
    
    if not telefono:
        return jsonify({'error': 'No hay número de teléfono registrado'}), 400
    
    # Formatear número
    if not telefono.startswith('+'):
        telefono = '+' + telefono
    
    # Reenviar código
    enviado = auth_manager.enviar_codigo_whatsapp(
        tenant['phone_id'], 
        tenant['token'], 
        codigo, 
        telefono
    )
    
    if enviado:
        # Actualizar fecha de envío
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    UPDATE public.verificacion_negocio 
                    SET codigo_enviado = NOW()
                    WHERE tenant_id = %s
                ''', (tenant_id,))
            conn.commit()
        return jsonify({'success': True, 'message': 'Código reenviado exitosamente'})
    else:
        return jsonify({'error': 'Error al enviar el código'}), 500

# ==================== ENDPOINTS DE ROLES Y USUARIOS ====================

@app.route('/api/negocio/<tenant_id>/usuarios', methods=['GET'])
def get_usuarios_negocio(tenant_id):
    """Obtiene todos los usuarios de un negocio"""
    if 'usuario_id' not in session:
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
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    
    data = request.json
    result = auth_manager.invitar_usuario(
        session['usuario_id'],
        tenant_id,
        data.get('email'),
        data.get('rol', 'viewer')
    )
    return jsonify(result)

@app.route('/api/negocio/<tenant_id>/usuarios/<usuario_id>', methods=['DELETE'])
def remover_usuario(tenant_id, usuario_id):
    """Remueve un usuario de un negocio"""
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    
    result = auth_manager.remover_usuario(session['usuario_id'], tenant_id, usuario_id)
    return jsonify(result)

@app.route('/api/negocio/<tenant_id>/usuarios/<usuario_id>/rol', methods=['PUT'])
def cambiar_rol_usuario(tenant_id, usuario_id):
    """Cambia el rol de un usuario en un negocio"""
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    
    data = request.json
    result = auth_manager.cambiar_rol_usuario(
        session['usuario_id'],
        tenant_id,
        usuario_id,
        data.get('rol')
    )
    return jsonify(result)

@app.route('/api/negocio/<tenant_id>/permisos', methods=['GET'])
def verificar_permisos(tenant_id):
    """Verifica los permisos del usuario actual en el negocio"""
    if 'usuario_id' not in session:
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
    
    return jsonify({
        'permisos': permisos,
        'mi_rol': mi_rol
    })

# ==================== PÁGINAS LEGALES ====================

@app.route('/terminos')
def terminos():
    return render_template('terminos.html')

@app.route('/privacidad')
def privacidad():
    return render_template('privacidad.html')

@app.route('/politicas-uso')
def politicas_uso():
    return render_template('politicas-uso.html')

# ==================== ENDPOINTS BÁSICOS ====================

@app.route('/api/register', methods=['POST'])
def api_register_tenant():
    """Registro de tenant (para onboarding manual)"""
    return register_new_tenant()

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok', 'message': 'WhatsApp SaaS is running'}

# ==================== ENDPOINTS PARA EL PANEL DE ADMIN ====================

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

@app.route('/admin/update_product/<tenant_id>/<product_id>', methods=['PUT', 'OPTIONS'])
def update_product(tenant_id, product_id):
    """Actualiza un producto del menú"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        logger.info(f'Actualizando producto {product_id} en tenant {tenant_id}: {data}')
        
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {tenant_id}.productos 
                    SET nombre = %s, descripcion = %s, precio = %s, categoria = %s, disponible = %s
                    WHERE id = %s
                """, (
                    data.get('nombre'),
                    data.get('descripcion'),
                    data.get('precio'),
                    data.get('categoria', 'general'),
                    data.get('disponible', True),
                    product_id
                ))
            conn.commit()
        
        return jsonify({'status': 'ok', 'message': 'Producto actualizado'}), 200
        
    except Exception as e:
        logger.error(f'Error actualizando producto: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/admin/toggle_product/<tenant_id>/<product_id>', methods=['PUT', 'OPTIONS'])
def toggle_product(tenant_id, product_id):
    """Activa o desactiva un producto"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        disponible = data.get('disponible', True)
        logger.info(f'Cambiando estado del producto {product_id} a {disponible}')
        
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {tenant_id}.productos 
                    SET disponible = %s
                    WHERE id = %s
                """, (disponible, product_id))
            conn.commit()
        
        estado = "activado" if disponible else "desactivado"
        return jsonify({'status': 'ok', 'message': f'Producto {estado}'}), 200
        
    except Exception as e:
        logger.error(f'Error cambiando estado del producto: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/admin/update_tenant/<tenant_id>', methods=['PUT', 'OPTIONS'])
def update_tenant(tenant_id):
    """Actualiza los datos de un tenant"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        logger.info(f'Actualizando tenant {tenant_id}: {data}')
        
        tenant_repo.update_tenant(
            tenant_id,
            data.get('nombre'),
            data.get('phone_id'),
            data.get('token'),
            data.get('usar_ia', False)
        )
        
        return jsonify({'status': 'ok', 'message': 'Tenant actualizado'}), 200
        
    except Exception as e:
        logger.error(f'Error actualizando tenant: {str(e)}')
        return jsonify({'error': str(e)}), 500
    
@app.route('/admin/delete_tenant/<tenant_id>', methods=['DELETE', 'OPTIONS'])
def delete_tenant(tenant_id):
    """Elimina un tenant y todos sus datos"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        logger.info(f'Eliminando tenant: {tenant_id}')
        
        tenant = tenant_repo.find_by_id(tenant_id)
        if not tenant:
            return jsonify({'error': 'Tenant no encontrado'}), 404
        
        tenant_repo.delete(tenant_id)
        
        return jsonify({'status': 'ok', 'message': 'Tenant eliminado'}), 200
        
    except Exception as e:
        logger.error(f'Error eliminando tenant: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ==================== API ENDPOINTS ====================

@app.route('/api/tenant/<tenant_id>/menu', methods=['GET'])
def get_tenant_menu(tenant_id):
    """Obtiene el menú del tenant"""
    try:
        logger.info(f'Obteniendo menú para tenant: {tenant_id}')
        menu = schema_manager.get_menu(tenant_id)
        return jsonify(menu)
    except Exception as e:
        logger.error(f'Error obteniendo menú: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/tenant/<tenant_id>/config', methods=['GET'])
def get_tenant_config(tenant_id):
    """Obtiene configuración del tenant"""
    try:
        tenant = tenant_repo.find_by_id(tenant_id)
        if not tenant:
            return jsonify({'error': 'Tenant no encontrado'}), 404
        return jsonify({'usar_ia': tenant.get('usar_ia', False)})
    except Exception as e:
        logger.error(f'Error obteniendo config: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/tenant/<tenant_id>/config/ia', methods=['PUT', 'OPTIONS'])
def update_tenant_ia(tenant_id):
    """Actualiza configuración de IA del tenant"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        usar_ia = data.get('usar_ia', False)
        tenant_repo.update_ia_config(tenant_id, usar_ia)
        logger.info(f'IA {"activada" if usar_ia else "desactivada"} para tenant {tenant_id}')
        return jsonify({'status': 'ok', 'usar_ia': usar_ia})
    except Exception as e:
        logger.error(f'Error actualizando IA: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/admin/add_product/<tenant_id>', methods=['POST', 'OPTIONS'])
def add_product(tenant_id):
    """Agrega un producto al menú del tenant"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        logger.info(f'Recibido producto para tenant {tenant_id}: {data}')
        
        if not data:
            return jsonify({'error': 'No se recibieron datos'}), 400
        
        nombre = data.get('nombre')
        precio = data.get('precio')
        
        if not nombre or not precio:
            return jsonify({'error': 'Faltan nombre o precio'}), 400
        
        product_id = schema_manager.add_product(
            tenant_id,
            nombre,
            int(precio),
            data.get('descripcion', ''),
            data.get('categoria', 'general')
        )
        
        logger.info(f'Producto agregado: {nombre} (ID: {product_id})')
        return jsonify({'status': 'ok', 'product_id': product_id}), 201
        
    except Exception as e:
        logger.error(f'Error agregando producto: {str(e)}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/admin/delete_product/<tenant_id>/<product_id>', methods=['DELETE', 'OPTIONS'])
def delete_product(tenant_id, product_id):
    """Elimina un producto del menú"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        logger.info(f'Eliminando producto {product_id} de tenant {tenant_id}')
        
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {tenant_id}.productos WHERE id = %s", (product_id,))
                if cur.rowcount == 0:
                    return jsonify({'error': 'Producto no encontrado'}), 404
            conn.commit()
        
        logger.info(f'Producto {product_id} eliminado')
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f'Error eliminando producto: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ==================== AI ENDPOINTS ====================

@app.route('/admin/train/<tenant_id>', methods=['GET', 'POST'])
def train_ia(tenant_id):
    """Panel para entrenar la IA del negocio"""
    
    if request.method == 'GET':
        return render_template('train.html', tenant_id=tenant_id)
    
    # POST: procesar el entrenamiento
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No se recibieron datos'}), 400
        
        tipo = data.get('tipo')
        logger.info(f'Entrenando IA para tenant {tenant_id}, tipo: {tipo}')
        
        if tipo == 'imagen':
            image_base64 = data.get('imagen')
            if not image_base64:
                return jsonify({'error': 'No se recibió la imagen'}), 400
            resultado = trainer.procesar_imagen(image_base64)
        elif tipo == 'texto':
            texto = data.get('texto')
            if not texto:
                return jsonify({'error': 'No se recibió el texto'}), 400
            resultado = trainer.procesar_texto(texto)
        else:
            return jsonify({'error': 'Tipo no válido. Use "imagen" o "texto"'}), 400
        
        if not resultado:
            logger.error('El procesamiento devolvió None')
            return jsonify({'error': 'No se pudo procesar el contenido. Verifica que la imagen sea clara o el texto tenga información válida.'}), 500
        
        # Guardar contexto en base de datos
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                # Generar prompt personalizado
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
        
        # También guardar los productos en el menú del tenant
        productos_agregados = 0
        for producto in resultado.get('productos', []):
            try:
                if producto.get('nombre') and producto.get('precio'):
                    schema_manager.add_product(
                        tenant_id,
                        producto.get('nombre'),
                        int(producto.get('precio', 0)),
                        producto.get('descripcion', ''),
                        producto.get('categoria', 'general')
                    )
                    productos_agregados += 1
            except Exception as e:
                logger.warning(f'Error guardando producto {producto.get("nombre")}: {e}')
        
        logger.info(f'Entrenamiento completado: {productos_agregados} productos guardados')
        
        return jsonify({
            'status': 'ok', 
            'contexto': resultado,
            'productos_guardados': productos_agregados,
            'message': f'Entrenamiento exitoso. Se guardaron {productos_agregados} productos.'
        })
        
    except Exception as e:
        logger.error(f'Error en train_ia: {str(e)}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'details': 'Error interno del servidor'}), 500

@app.route('/api/tenant/<tenant_id>/context', methods=['GET'])
def get_tenant_context(tenant_id):
    """Obtiene el contexto de IA del tenant"""
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
        logger.error(f'Error obteniendo contexto: {e}')
        return jsonify({}), 500

# ==================== DEBUG ENDPOINTS ====================

@app.route('/debug/train_test', methods=['GET'])
def train_test():
    """Prueba simple para verificar que el entrenamiento funciona"""
    return jsonify({
        'status': 'ok',
        'message': 'Endpoint de entrenamiento disponible',
        'trainer_available': 'trainer' in globals()
    })

@app.route('/debug/check_trainer', methods=['GET'])
def check_trainer():
    """Verifica que el trainer está disponible"""
    try:
        from ai.training import trainer
        return jsonify({
            'trainer_available': True,
            'trainer_type': str(type(trainer)),
            'methods': [m for m in dir(trainer) if not m.startswith('_')]
        })
    except Exception as e:
        return jsonify({
            'trainer_available': False,
            'error': str(e)
        }), 500

@app.route('/debug/test_deepseek', methods=['POST'])
def test_deepseek():
    """Prueba qué devuelve DeepSeek con un texto simple"""
    try:
        data = request.json
        texto = data.get('texto', 'Pizza Margarita 25000')
        
        response = ai_client.client.chat.completions.create(
            model=ai_client.model,
            messages=[{"role": "user", "content": f"Extrae productos de: {texto}. Devuelve SOLO JSON: {{\"productos\": [{{\"nombre\": \"\", \"precio\": 0}}]}}"}],
            max_tokens=500
        )
        
        return jsonify({
            'respuesta_original': response.choices[0].message.content,
            'status': 'ok'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/test', methods=['GET'])
def debug_test():
    """Endpoint de prueba para verificar que la API funciona"""
    return jsonify({
        'status': 'ok',
        'message': 'API funcionando correctamente',
        'endpoints': [
            '/admin/tenants',
            '/admin/menu?tenant_id=xxx',
            '/api/tenant/xxx/menu',
            '/admin/add_product/xxx',
            '/api/tenant/xxx/config/ia'
        ]
    })

@app.route('/debug/tesseract', methods=['GET'])
def test_tesseract():
    import subprocess
    try:
        result = subprocess.run(['tesseract', '--version'], capture_output=True, text=True)
        return {
            'tesseract_installed': True,
            'version': result.stdout.split('\n')[0] if result.stdout else 'unknown',
            'status': 'ok'
        }
    except Exception as e:
        return {'tesseract_installed': False, 'error': str(e), 'status': 'fail'}, 500

@app.route('/debug/webhook_info', methods=['GET'])
def webhook_info():
    """Muestra la configuración actual del webhook"""
    tenants = tenant_repo.get_all()
    return {
        'webhook_url': 'https://whatsapp-mvp-docker.onrender.com/webhook',
        'tenants_registrados': [
            {'nombre': t['nombre'], 'phone_id': t['phone_id']} 
            for t in tenants
        ]
    }

@app.route('/debug/tenant/<phone_id>', methods=['GET'])
def debug_tenant(phone_id):
    """Verifica si existe un tenant con ese phone_id"""
    tenant = tenant_repo.find_by_phone_id(phone_id)
    if tenant:
        return jsonify({
            'exists': True,
            'tenant': tenant
        })
    else:
        return jsonify({
            'exists': False,
            'message': f'No se encontró tenant con phone_id: {phone_id}',
            'tenants_available': tenant_repo.get_all()
        })

@app.route('/admin/test_delete', methods=['GET'])
def test_delete():
    """Endpoint de prueba para verificar que la API funciona"""
    return jsonify({'status': 'ok', 'message': 'API de eliminación funciona'})

# ==================== SUPER USER ENDPOINTS ====================

@app.route('/super/admin/check-auth', methods=['GET'])
def super_admin_check_auth():
    """Verifica si el usuario actual es super admin"""
    if session.get('rol_sistema') == 'super_admin':
        return jsonify({'authenticated': True, 'email': session.get('email')})
    return jsonify({'authenticated': False})

@app.route('/super/admin/dashboard')
def super_admin_dashboard():
    """Panel de super administrador"""
    # Si no está autenticado como super admin, redirigir al login
    if session.get('rol_sistema') != 'super_admin':
        return redirect('/super/admin/login-page')
    
    return render_template('super_admin.html')

# Agrega este endpoint si no existe
@app.route('/super/admin/login-page')
def super_admin_login_page():
    """Página de login para super administrador"""
    return render_template('super_admin_login.html')

if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)