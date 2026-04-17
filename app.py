from flask import Flask, jsonify, request
from core.config import config
from core.database import db_manager
from core.logger import setup_logging, logger
from whatsapp.webhook import register_webhook_routes
from tenants.onboarding import register_new_tenant
from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from flask import render_template


setup_logging()

#app = Flask(__name__)
app = Flask(__name__, template_folder='web/templates')

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


# ==================== HEALTH CHECK ====================

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

@app.route('/admin/test_delete', methods=['GET'])
def test_delete():
    """Endpoint de prueba para verificar que la API funciona"""
    return jsonify({'status': 'ok', 'message': 'API de eliminación funciona'})

if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)