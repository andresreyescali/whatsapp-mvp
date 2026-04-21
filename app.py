import os
import json
import secrets
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

# Inicializar base de datos
db_manager.init_global_tables()
register_webhook_routes(app)

# ==================== ENDPOINTS BÁSICOS ====================

@app.route('/api/register', methods=['POST'])
def api_register():
    return register_new_tenant()

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok', 'message': 'WhatsApp SaaS is running'}

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
    if result['success']:
        session['usuario_id'] = result['usuario_id']
        session['email'] = result['email']
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
        'email': session['email']
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

@app.route('/admin/delete_tenant/<tenant_id>', methods=['DELETE', 'OPTIONS'])
def delete_tenant(tenant_id):
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

@app.route('/admin/update_tenant/<tenant_id>', methods=['PUT', 'OPTIONS'])
def update_tenant(tenant_id):
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
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

# ==================== API ENDPOINTS ====================

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
                cur.execute(f"""
                    UPDATE {tenant_id}.productos 
                    SET disponible = %s
                    WHERE id = %s
                """, (disponible, product_id))
            conn.commit()
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== AI ENDPOINTS ====================

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
        
        # Guardar contexto y productos
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
                        tenant_id,
                        producto.get('nombre'),
                        int(producto.get('precio', 0)),
                        producto.get('descripcion', ''),
                        producto.get('categoria', 'general')
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
        logger.error(f'Error obteniendo contexto: {e}')
        return jsonify({}), 500

# ==================== DEBUG ENDPOINTS ====================

@app.route('/debug/test', methods=['GET'])
def debug_test():
    return jsonify({'status': 'ok', 'message': 'API funcionando'})

@app.route('/debug/tesseract', methods=['GET'])
def test_tesseract():
    import subprocess
    try:
        result = subprocess.run(['tesseract', '--version'], capture_output=True, text=True)
        return {'tesseract_installed': True, 'version': result.stdout.split('\n')[0]}
    except Exception as e:
        return {'tesseract_installed': False, 'error': str(e)}

@app.route('/debug/check_trainer', methods=['GET'])
def check_trainer():
    try:
        from ai.training import trainer
        return jsonify({
            'trainer_available': True,
            'trainer_type': str(type(trainer)),
            'methods': [m for m in dir(trainer) if not m.startswith('_')]
        })
    except Exception as e:
        return jsonify({'trainer_available': False, 'error': str(e)}), 500

if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)