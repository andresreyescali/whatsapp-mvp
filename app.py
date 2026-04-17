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
            body { font-family: Arial; padding: 20px; background: #f5f5f5; }
            h1 { color: #25D366; }
            table { border-collapse: collapse; width: 100%; background: white; }
            th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
            th { background: #25D366; color: white; }
            tr:hover { background: #f5f5f5; }
            a { color: #25D366; text-decoration: none; font-weight: bold; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>📋 Negocios Registrados</h1>
        <p>Total: <strong>""" + str(len(tenants)) + """</strong> negocios</p>
        <table>
            <thead>
                <tr><th>ID</th><th>Nombre</th><th>Phone ID</th><th>Fecha</th><th>Panel</th></tr>
            </thead>
            <tbody>
    """
    for t in tenants:
        html += f"""
            <tr>
                <td><code>{t['id']}</code></td>
                <td><strong>{t['nombre']}</strong></td>
                <td>{t['phone_id']}</td>
                <td>{t['created_at']}</td>
                <td><a href="/admin/menu?tenant_id={t['id']}">🎛️ Gestionar Menú</a></td>
            </tr>
        """
    html += """
            </tbody>
        </table>
    </body>
    </html>
    """
    return html

@app.route('/registro')
def registro():
    """Muestra el formulario para registrar un nuevo negocio"""
    return render_template('registro.html')

@app.route('/registro_web', methods=['POST'])
def registro_web():
    from tenants.repository import tenant_repo
    from tenants.schema_manager import schema_manager
    
    nombre = request.form.get('nombre')
    phone_id = request.form.get('phone_id')
    token = request.form.get('token')
    
    # Crear tenant
    tenant = tenant_repo.create(nombre, phone_id, token)
    
    # Crear su esquema y tablas
    schema_manager.create_tenant_schema(tenant['id'], 'restaurante')
    
    return f"""
    ✅ Negocio {nombre} registrado exitosamente!<br>
    Tenant ID: {tenant['id']}<br>
    <a href="/admin/menu?tenant_id={tenant['id']}">Ir al panel de menú</a>
    """

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
        <meta name="viewport" content="width=   device-width, initial-scale=1.0">
        <title>Gestión de Menú - {tenant['nombre']}</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f0f0f0; padding: 20px; }}
            .container {{ max-width: 900px; margin: 0 auto; }}
            .header {{ background: #25D366; color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
            .header h1 {{ margin-bottom: 10px; }}
            .card {{ background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .card h2 {{ margin-bottom: 15px; color: #333; border-bottom: 2px solid #25D366; padding-bottom: 10px; }}
            .form-group {{ margin-bottom: 15px; }}
            label {{ display: block; margin-bottom: 5px; font-weight: bold; color: #555; }}
            input, textarea, select {{ width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-size: 14px; }}
            button {{ background: #25D366; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }}
            button:hover {{ background: #128C7E; }}
            .delete-btn {{ background: #e74c3c; padding: 5px 10px; font-size: 12px; margin-left: 10px; }}
            .delete-btn:hover {{ background: #c0392b; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #f5f5f5; font-weight: bold; }}
            .success {{ background: #d4edda; color: #155724; padding: 12px; border-radius: 5px; margin-bottom: 15px; border: 1px solid #c3e6cb; }}
            .error {{ background: #f8d7da; color: #721c24; padding: 12px; border-radius: 5px; margin-bottom: 15px; border: 1px solid #f5c6cb; }}
            .hidden {{ display: none; }}
            .loading {{ text-align: center; padding: 20px; color: #666; }}
            .empty {{ text-align: center; padding: 40px; color: #999; }}
            .stats {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin-bottom: 20px; }}
            .stat-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; }}
            .stat-card .number {{ font-size: 32px; font-weight: bold; }}
            .stat-card .label {{ font-size: 14px; opacity: 0.9; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🍕 {tenant['nombre']}</h1>
                <p>Gestiona el menú de tu negocio en WhatsApp</p>
                <p><small>ID: {tenant_id}</small></p>
            </div>
            
            <div id="alert" class="hidden"></div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="number" id="totalProductos">0</div>
                    <div class="label">Productos en Menú</div>
                </div>
                <div class="stat-card">
                    <div class="number" id="iaStatus">❌</div>
                    <div class="label">Inteligencia Artificial</div>
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
                            <option value="acompañamientos">🍟 Acompañamientos</option>
                            <option value="postres">🍰 Postres</option>
                        </select>
                    </div>
                    <button type="submit">Agregar Producto</button>
                </form>
            </div>
            
            <div class="card">
                <h2>📋 Mi Menú</h2>
                <div id="menuContainer" class="loading">Cargando menú...</div>
            </div>
            
            <div class="card">
                <h2>⚙️ Configuración</h2>
                <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                    <input type="checkbox" id="usarIA" {'checked' if tenant.get('usar_ia') else ''}>
                    <span>Activar respuestas con Inteligencia Artificial</span>
                </label>
                <p style="font-size: 12px; color: #666; margin-top: 10px;">
                    La IA permite respuestas más naturales y personalizadas para tus clientes.
                </p>
                <button id="saveConfigBtn" style="margin-top: 15px;">💾 Guardar Configuración</button>
            </div>
        </div>
        
        <script>
            const tenantId = '{tenant_id}';
            const API_BASE = window.location.origin;
            
            async function loadMenu() {{
                try {{
                    const response = await fetch(`${{API_BASE}}/api/tenant/${{tenantId}}/menu`);
                    if (!response.ok) throw new Error('Error al cargar menú');
                    const menu = await response.json();
                    
                    document.getElementById('totalProductos').innerText = menu.length;
                    
                    if (menu.length === 0) {{
                        document.getElementById('menuContainer').innerHTML = '<div class="empty">📭 No hay productos en el menú.<br>Agrega tu primer producto usando el formulario.</div>';
                        return;
                    }}
                    
                    let html = '<table><thead><tr><th>Producto</th><th>Descripción</th><th>Precio</th><th>Acciones</th></tr></thead><tbody>';
                    menu.forEach(item => {{
                        html += `
                            <tr>
                                <td><strong>${{escapeHtml(item.nombre)}}</strong></td>
                                <td>${{escapeHtml(item.descripcion || '-')}}</td>
                                <td>$$${{item.precio.toLocaleString()}}</td>
                                <td><button class="delete-btn" onclick="deleteProduct('${{item.id}}')">🗑️ Eliminar</button></td>
                            </tr>
                        `;
                    }});
                    html += '</tbody></table>';
                    document.getElementById('menuContainer').innerHTML = html;
                }} catch (error) {{
                    console.error('Error:', error);
                    document.getElementById('menuContainer').innerHTML = '<div class="error">❌ Error al cargar el menú. Verifica que el tenant existe.</div>';
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
                
                const submitBtn = e.target.querySelector('button');
                submitBtn.disabled = true;
                submitBtn.textContent = 'Agregando...';
                
                try {{
                    const response = await fetch(`${{API_BASE}}/admin/add_product/${{tenantId}}`, {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify(producto)
                    }});
                    
                    const result = await response.json();
                    
                    if (response.ok) {{
                        showAlert('success', '✅ Producto agregado correctamente');
                        document.getElementById('productForm').reset();
                        loadMenu();
                    }} else {{
                        showAlert('error', '❌ Error: ' + (result.error || result.details || 'No se pudo agregar el producto'));
                    }}
                }} catch (error) {{
                    console.error('Error:', error);
                    showAlert('error', '❌ Error de conexión: ' + error.message);
                }} finally {{
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Agregar Producto';
                }}
            }});
            
            document.getElementById('saveConfigBtn').addEventListener('click', async () => {{
                const usarIA = document.getElementById('usarIA').checked;
                const btn = document.getElementById('saveConfigBtn');
                btn.disabled = true;
                btn.textContent = 'Guardando...';
                
                try {{
                    const response = await fetch(`${{API_BASE}}/api/tenant/${{tenantId}}/config/ia`, {{
                        method: 'PUT',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{ usar_ia: usarIA }})
                    }});
                    
                    if (response.ok) {{
                        showAlert('success', '✅ Configuración guardada');
                        document.getElementById('iaStatus').innerHTML = usarIA ? '✅' : '❌';
                    }} else {{
                        showAlert('error', '❌ Error al guardar configuración');
                    }}
                }} catch (error) {{
                    showAlert('error', '❌ Error de conexión');
                }} finally {{
                    btn.disabled = false;
                    btn.textContent = '💾 Guardar Configuración';
                }}
            }});
            
            window.deleteProduct = async (productId) => {{
                if (!confirm('¿Eliminar este producto del menú?')) return;
                
                try {{
                    const response = await fetch(`${{API_BASE}}/admin/delete_product/${{tenantId}}/${{productId}}`, {{ 
                        method: 'DELETE' 
                    }});
                    
                    if (response.ok) {{
                        showAlert('success', '✅ Producto eliminado');
                        loadMenu();
                    }} else {{
                        showAlert('error', '❌ Error al eliminar producto');
                    }}
                }} catch (error) {{
                    showAlert('error', '❌ Error de conexión');
                }}
            }};
            
            function showAlert(type, message) {{
                const alertDiv = document.getElementById('alert');
                alertDiv.className = type === 'success' ? 'success' : 'error';
                alertDiv.innerHTML = message;
                alertDiv.classList.remove('hidden');
                setTimeout(() => alertDiv.classList.add('hidden'), 3000);
            }}
            
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


if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)