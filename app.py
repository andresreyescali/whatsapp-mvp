from flask import Flask, jsonify, request
from core.config import config
from core.database import db_manager
from core.logger import setup_logging, logger
from whatsapp.webhook import register_webhook_routes
from tenants.onboarding import register_new_tenant
from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager

setup_logging()

app = Flask(__name__)
db_manager.init_global_tables()
register_webhook_routes(app)

@app.route('/api/register', methods=['POST'])
def api_register():
    return register_new_tenant()

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok', 'message': 'WhatsApp SaaS is running'}

# ==================== PANEL DE ADMINISTRACIÓN ====================

@app.route('/admin/menu', methods=['GET'])
def admin_menu():
    """Panel de administración de menú"""
    tenant_id = request.args.get('tenant_id')
    
    if not tenant_id:
        return "<h1>Error</h1><p>Se requiere tenant_id</p>", 400
    
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return f"<h1>Error</h1><p>Tenant no encontrado: {tenant_id}</p>", 404
    
    # Generar HTML directamente
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Gestión de Menú - {tenant['nombre']}</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: Arial, sans-serif; background: #f0f0f0; padding: 20px; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .header {{ background: #25D366; color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
            .card {{ background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .card h2 {{ margin-bottom: 15px; color: #333; }}
            .form-group {{ margin-bottom: 15px; }}
            label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
            input, textarea, select {{ width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 5px; }}
            button {{ background: #25D366; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }}
            button:hover {{ background: #128C7E; }}
            .delete-btn {{ background: #e74c3c; padding: 5px 10px; font-size: 12px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #f5f5f5; }}
            .success {{ background: #d4edda; color: #155724; padding: 10px; border-radius: 5px; margin-bottom: 10px; }}
            .error {{ background: #f8d7da; color: #721c24; padding: 10px; border-radius: 5px; margin-bottom: 10px; }}
            .hidden {{ display: none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🍕 {tenant['nombre']}</h1>
                <p>Gestiona el menú de tu negocio</p>
                <p><small>ID: {tenant_id}</small></p>
            </div>
            
            <div id="alert" class="hidden"></div>
            
            <div class="card">
                <h2>➕ Agregar Producto</h2>
                <form id="productForm">
                    <div class="form-group">
                        <label>Nombre del producto *</label>
                        <input type="text" id="nombre" required placeholder="Ej: Pizza Margarita">
                    </div>
                    <div class="form-group">
                        <label>Descripción</label>
                        <textarea id="descripcion" rows="2" placeholder="Describe el producto..."></textarea>
                    </div>
                    <div class="form-group">
                        <label>Precio ($) *</label>
                        <input type="number" id="precio" required placeholder="25000">
                    </div>
                    <div class="form-group">
                        <label>Categoría</label>
                        <select id="categoria">
                            <option value="pizzas">🍕 Pizzas</option>
                            <option value="hamburguesas">🍔 Hamburguesas</option>
                            <option value="bebidas">🥤 Bebidas</option>
                            <option value="postres">🍰 Postres</option>
                        </select>
                    </div>
                    <button type="submit">Agregar Producto</button>
                </form>
            </div>
            
            <div class="card">
                <h2>📋 Mi Menú</h2>
                <div id="menuContainer">Cargando...</div>
            </div>
            
            <div class="card">
                <h2>⚙️ Configuración</h2>
                <label>
                    <input type="checkbox" id="usarIA" {'checked' if tenant.get('usar_ia') else ''}>
                    Activar respuestas con Inteligencia Artificial
                </label>
                <button id="saveConfigBtn" style="margin-top: 15px;">Guardar</button>
            </div>
        </div>
        
        <script>
            const tenantId = '{tenant_id}';
            const API_BASE = window.location.origin;
            
            async function loadMenu() {{
                try {{
                    const response = await fetch(`${{API_BASE}}/api/tenant/${{tenantId}}/menu`);
                    const menu = await response.json();
                    
                    if (menu.length === 0) {{
                        document.getElementById('menuContainer').innerHTML = '<p>No hay productos. Agrega tu primer producto.</p>';
                        return;
                    }}
                    
                    let html = '<table><thead><tr><th>Producto</th><th>Descripción</th><th>Precio</th><th>Acciones</th></tr></thead><tbody>';
                    menu.forEach(item => {{
                        html += `
                            <tr>
                                <td>${{item.nombre}}</strong></td>
                                <td>${{item.descripcion || '-'}}</td>
                                <td>$${{item.precio.toLocaleString()}}</td>
                                <td><button class="delete-btn" onclick="deleteProduct('${{item.id}}')">Eliminar</button></td>
                            </tr>
                        `;
                    }});
                    html += '</tbody></div>';
                    document.getElementById('menuContainer').innerHTML = html;
                }} catch (error) {{
                    document.getElementById('menuContainer').innerHTML = '<p style="color:red">Error al cargar el menú</p>';
                }}
            }}
            
            document.getElementById('productForm').addEventListener('submit', async (e) => {{
                e.preventDefault();
                const producto = {{
                    nombre: document.getElementById('nombre').value,
                    descripcion: document.getElementById('descripcion').value,
                    precio: parseInt(document.getElementById('precio').value),
                    categoria: document.getElementById('categoria').value
                }};
                
                try {{
                    const response = await fetch(`${{API_BASE}}/admin/add_product/${{tenantId}}`, {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify(producto)
                    }});
                    
                    if (response.ok) {{
                        showAlert('success', 'Producto agregado');
                        document.getElementById('productForm').reset();
                        loadMenu();
                    }} else {{
                        showAlert('error', 'Error al agregar');
                    }}
                }} catch (error) {{
                    showAlert('error', 'Error de conexión');
                }}
            }});
            
            document.getElementById('saveConfigBtn').addEventListener('click', async () => {{
                const usarIA = document.getElementById('usarIA').checked;
                try {{
                    const response = await fetch(`${{API_BASE}}/api/tenant/${{tenantId}}/config/ia`, {{
                        method: 'PUT',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{ usar_ia: usarIA }})
                    }});
                    if (response.ok) {{
                        showAlert('success', 'Configuración guardada');
                    }}
                }} catch (error) {{
                    showAlert('error', 'Error al guardar');
                }}
            }});
            
            window.deleteProduct = async (productId) => {{
                if (!confirm('¿Eliminar este producto?')) return;
                try {{
                    await fetch(`${{API_BASE}}/admin/delete_product/${{tenantId}}/${{productId}}`, {{ method: 'DELETE' }});
                    loadMenu();
                    showAlert('success', 'Producto eliminado');
                }} catch (error) {{
                    showAlert('error', 'Error al eliminar');
                }}
            }};
            
            function showAlert(type, message) {{
                const alertDiv = document.getElementById('alert');
                alertDiv.className = type === 'success' ? 'success' : 'error';
                alertDiv.innerHTML = message;
                alertDiv.classList.remove('hidden');
                setTimeout(() => alertDiv.classList.add('hidden'), 3000);
            }}
            
            loadMenu();
        </script>
    </body>
    </html>
    """
    
    return html

# ==================== ENDPOINTS PARA EL PANEL ====================

@app.route('/api/tenant/<tenant_id>/menu', methods=['GET'])
def get_tenant_menu(tenant_id):
    """Obtiene el menú del tenant"""
    try:
        menu = schema_manager.get_menu(tenant_id)
        return jsonify(menu)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tenant/<tenant_id>/config', methods=['GET'])
def get_tenant_config(tenant_id):
    """Obtiene configuración del tenant"""
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant no encontrado'}), 404
    return jsonify({'usar_ia': tenant.get('usar_ia', False)})

@app.route('/api/tenant/<tenant_id>/config/ia', methods=['PUT'])
def update_tenant_ia(tenant_id):
    """Actualiza configuración de IA del tenant"""
    data = request.json
    usar_ia = data.get('usar_ia', False)
    tenant_repo.update_ia_config(tenant_id, usar_ia)
    return jsonify({'status': 'ok', 'usar_ia': usar_ia})

@app.route('/admin/add_product/<tenant_id>', methods=['POST'])
def add_product(tenant_id):
    """Agrega un producto al menú del tenant"""
    data = request.json
    try:
        product_id = schema_manager.add_product(
            tenant_id,
            data['nombre'],
            data['precio'],
            data.get('descripcion', ''),
            data.get('categoria', 'general')
        )
        return jsonify({'status': 'ok', 'product_id': product_id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/delete_product/<tenant_id>/<product_id>', methods=['DELETE'])
def delete_product(tenant_id, product_id):
    """Elimina un producto del menú"""
    try:
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {tenant_id}.productos WHERE id = %s", (product_id,))
            conn.commit()
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/tenants', methods=['GET'])
def list_tenants():
    """Lista todos los tenants (para administrador)"""
    tenants = tenant_repo.get_all()
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Administración de Tenants</title>
        <style>
            body { font-family: Arial; padding: 20px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
            th { background: #25D366; color: white; }
            a { color: #25D366; text-decoration: none; }
        </style>
    </head>
    <body>
        <h1>📋 Negocios Registrados</h1>
        <table>
            <tr><th>ID</th><th>Nombre</th><th>Phone ID</th><th>Fecha</th><th>Panel</th></tr>
    """
    for t in tenants:
        html += f"""
            <tr>
                <td>{t['id']}</td>
                <td>{t['nombre']}</td>
                <td>{t['phone_id']}</td>
                <td>{t['created_at']}</td>
                <td><a href="/admin/menu?tenant_id={t['id']}">🎛️ Gestionar Menú</a></td>
            </tr>
        """
    html += """
        </table>
    </body>
    </html>
    """
    return html

if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)