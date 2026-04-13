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
    """Panel de administración de menú - Versión sin templates"""
    from tenants.repository import tenant_repo
    tenant_id = request.args.get('tenant_id')
    
    if not tenant_id:
        return "<h1>Error</h1><p>Se requiere tenant_id</p>", 400
    
    # Verificar que el tenant existe
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return "<h1>Error</h1><p>Tenant no encontrado</p>", 404
    
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
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .header {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .header h1 {{ color: #333; margin-bottom: 10px; }}
            .card {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .card h2 {{ color: #333; margin-bottom: 15px; border-bottom: 2px solid #667eea; padding-bottom: 10px; }}
            .form-group {{ margin-bottom: 15px; }}
            label {{ display: block; margin-bottom: 5px; color: #333; font-weight: 500; }}
            input, textarea, select {{ width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }}
            button {{ background: #667eea; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; }}
            button:hover {{ background: #5a67d8; }}
            .delete-btn {{ background: #e53e3e; padding: 5px 10px; font-size: 12px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #f7f7f7; }}
            .alert {{ padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            .alert-success {{ background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
            .alert-error {{ background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
            .hidden {{ display: none; }}
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
            .stat-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; }}
            .stat-card .number {{ font-size: 32px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🍕 {tenant['nombre']}</h1>
                <p>Gestiona tu menú y configura tu asistente de ventas</p>
                <p><strong>Tenant ID:</strong> {tenant_id}</p>
            </div>
            
            <div id="alert" class="hidden"></div>
            
            <div class="stats">
                <div class="stat-card">
                    <h3>Productos en Menú</h3>
                    <div class="number" id="totalProductos">0</div>
                </div>
                <div class="stat-card">
                    <h3>IA Activada</h3>
                    <div class="number" id="iaStatus">❌</div>
                </div>
            </div>
            
            <div class="card">
                <h2>➕ Agregar Producto</h2>
                <form id="productForm">
                    <div class="form-group">
                        <label>Nombre del producto *</label>
                        <input type="text" id="nombre" required placeholder="Ej: Pizza Margarita">
                    </div>
                    <div class="form-group">
                        <label>Descripción</label>
                        <textarea id="descripcion" rows="3" placeholder="Describe el producto..."></textarea>
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
                            <option value="acompañamientos">🍟 Acompañamientos</option>
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
                    <input type="checkbox" id="usarIA">
                    Activar respuestas con Inteligencia Artificial
                </label>
                <button id="saveConfigBtn" style="margin-top: 15px;">Guardar Configuración</button>
            </div>
        </div>
        
        <script>
            const tenantId = '{tenant_id}';
            const API_BASE = window.location.origin;
            
            async function loadMenu() {{
                try {{
                    const response = await fetch(`${{API_BASE}}/api/tenant/${{tenantId}}/menu`);
                    const menu = await response.json();
                    document.getElementById('totalProductos').innerText = menu.length;
                    
                    if (menu.length === 0) {{
                        document.getElementById('menuContainer').innerHTML = '<p>No hay productos en el menú. Agrega tu primer producto.</p>';
                        return;
                    }}
                    
                    let html = '<table><thead><tr><th>Producto</th><th>Descripción</th><th>Precio</th><th>Categoría</th><th>Acciones</th></tr></thead><tbody>';
                    menu.forEach(item => {{
                        html += `
                            <tr>
                                <td><strong>${{escapeHtml(item.nombre)}}</strong></td>
                                <td>${{escapeHtml(item.descripcion || '-')}}</td>
                                <td>$${{item.precio.toLocaleString()}}</td>
                                <td>${{item.categoria || 'general'}}</td>
                                <td><button class="delete-btn" onclick="deleteProduct('${{item.id}}')">Eliminar</button></td>
                            </tr>
                        `;
                    }});
                    html += '</tbody></table>';
                    document.getElementById('menuContainer').innerHTML = html;
                }} catch (error) {{
                    document.getElementById('menuContainer').innerHTML = '<p style="color:red">Error al cargar menú</p>';
                }}
            }}
            
            async function loadConfig() {{
                try {{
                    const response = await fetch(`${{API_BASE}}/api/tenant/${{tenantId}}/config`);
                    if (response.ok) {{
                        const config = await response.json();
                        document.getElementById('usarIA').checked = config.usar_ia || false;
                        document.getElementById('iaStatus').innerHTML = config.usar_ia ? '✅' : '❌';
                    }}
                }} catch (error) {{
                    console.error('Error loading config:', error);
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
                        alert('Producto agregado');
                        document.getElementById('productForm').reset();
                        loadMenu();
                    }} else {{
                        alert('Error al agregar producto');
                    }}
                }} catch (error) {{
                    alert('Error de conexión');
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
                        alert('Configuración guardada');
                        document.getElementById('iaStatus').innerHTML = usarIA ? '✅' : '❌';
                    }}
                }} catch (error) {{
                    alert('Error al guardar');
                }}
            }});
            
            window.deleteProduct = async (productId) => {{
                if (!confirm('¿Eliminar este producto?')) return;
                try {{
                    await fetch(`${{API_BASE}}/admin/delete_product/${{tenantId}}/${{productId}}`, {{ method: 'DELETE' }});
                    loadMenu();
                }} catch (error) {{
                    alert('Error al eliminar');
                }}
            }};
            
            function escapeHtml(text) {{
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }}
            
            loadMenu();
            loadConfig();
        </script>
    </body>
    </html>
    """
    
    return html

@app.route('/api/tenant/<tenant_id>/config', methods=['GET'])
def get_tenant_config(tenant_id):
    from tenants.repository import tenant_repo
    tenant = tenant_repo.find_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant no encontrado'}), 404
    return jsonify({'usar_ia': tenant.get('usar_ia', False)})

@app.route('/admin/add_product/<tenant_id>', methods=['POST'])
def add_product(tenant_id):
    from tenants.schema_manager import schema_manager
    data = request.json
    try:
        schema_manager.add_product(
            tenant_id,
            data['nombre'],
            data['precio'],
            data.get('descripcion', ''),
            data.get('categoria', 'general')
        )
        return jsonify({'status': 'ok'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/admin/delete_product/<tenant_id>/<product_id>', methods=['DELETE'])
def delete_product(tenant_id, product_id):
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