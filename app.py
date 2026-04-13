from flask import Flask, jsonify, request
from core.config import config
from core.database import db_manager
from core.logger import setup_logging, logger
from whatsapp.webhook import register_webhook_routes
from tenants.onboarding import register_new_tenant
from psycopg.rows import dict_row

setup_logging()

app = Flask(__name__)
db_manager.init_global_tables()
register_webhook_routes(app)

@app.route('/api/register', methods=['POST'])
def api_register():
    return register_new_tenant()

@app.route('/health')
def health():
    return {'status': 'ok'}

@app.route('/')
def index():
    return {'message': 'WhatsApp SaaS API', 'status': 'running'}

# Agregar estos endpoints a tu app.py

from flask import render_template

@app.route('/admin/menu', methods=['GET'])
def admin_menu():
    """Panel de administración de menú"""
    return render_template('admin_menu.html')

@app.route('/api/tenant/<tenant_id>/config', methods=['GET'])
def get_tenant_config(tenant_id):
    """Obtener configuración del tenant"""
    from tenants.repository import tenant_repo
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant no encontrado'}), 404
    return jsonify({
        'usar_ia': tenant.get('usar_ia', False)
    })

@app.route('/admin/delete_product/<tenant_id>/<product_id>', methods=['DELETE'])
def delete_product(tenant_id, product_id):
    """Eliminar producto del menú"""
    from core.database import db_manager
    try:
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {tenant_id}.productos WHERE id = %s", (product_id,))
            conn.commit()
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)