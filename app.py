import json
from flask import Flask, jsonify, request
from core.config import config
from core.database import db_manager
from core.logger import setup_logging, logger
from whatsapp.webhook import register_webhook_routes
from tenants.onboarding import register_new_tenant
from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from flask import render_template
from ai.training import trainer
from ai.client import ai_client

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
        
        from tenants.repository import tenant_repo
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
                    # Obtener nombres de columnas
                    columns = [desc[0] for desc in cur.description]
                    result = dict(zip(columns, row))
                    # Convertir JSONB a dict si es necesario
                    if result.get('menu_estructurado') and isinstance(result['menu_estructurado'], str):
                        result['menu_estructurado'] = json.loads(result['menu_estructurado'])
                    return jsonify(result)
                return jsonify({})
    except Exception as e:
        logger.error(f'Error obteniendo contexto: {e}')
        return jsonify({}), 500


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
    from tenants.repository import tenant_repo
    
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

if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)