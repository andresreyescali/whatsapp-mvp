import json
import re
import uuid
from datetime import datetime
from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from orders.repository import order_repo
from orders.payment import generar_link_pago
from whatsapp.client import whatsapp_client
from ai.client import ai_client
from core.logger import logger
from core.database import db_manager

class MessageHandler:
    """Procesa mensajes de WhatsApp usando IA para entender lenguaje natural"""
    
    def __init__(self):
        """Inicializa el manejador de mensajes"""
        self._datos_cliente = {}
    
    def _get_schema_name(self, tenant_id: str) -> str:
        tenant = tenant_repo.find_by_id(tenant_id)
        if tenant and tenant.get('schema_name'):
            return tenant['schema_name']
        return f"tenant_{tenant_id.replace('-', '_')}"
    
    def process(self, phone_id: str, numero: str, texto: str):
        logger.info(f'🟢 [PROCESS] Iniciando - Cliente: {numero}, Mensaje: {texto[:100]}')
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'⚠️ [PROCESS] Tenant no encontrado para phone_id: {phone_id}')
            return
        
        schema_manager.ensure_schema(tenant['id'])
        menu = self._obtener_menu(tenant['id'])
        contexto = self._obtener_contexto_tenant(tenant['id'])
        
        respuesta = self._procesar_con_ia(texto, tenant, menu, numero, contexto)
        
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)
            logger.info(f'🟢 [PROCESS] Respuesta enviada a {numero}')
        else:
            logger.warning(f'⚠️ [PROCESS] No se generó respuesta para {numero}')

    def _obtener_menu(self, tenant_id: str) -> list:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible 
                        FROM "{schema_name}".productos 
                        ORDER BY categoria, nombre
                    """)
                    rows = cur.fetchall()
                    return [{
                        'id': str(row[0]),
                        'nombre': row[1],
                        'descripcion': row[2] or '',
                        'precio': row[3],
                        'categoria': row[4] or 'general',
                        'disponible': row[5]
                    } for row in rows]
        except Exception as e:
            logger.error(f'Error obteniendo menú: {e}')
            return []

    def _obtener_contexto_tenant(self, tenant_id: str) -> dict:
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        SELECT instrucciones, horario, ubicacion, politicas, prompt_personalizado 
                        FROM public.tenant_context WHERE tenant_id = %s
                    ''', (tenant_id,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'instrucciones': row[0] or '',
                            'horario': row[1] or '',
                            'ubicacion': row[2] or '',
                            'politicas': row[3] or '',
                            'prompt_personalizado': row[4] or ''
                        }
                    return {}
        except Exception as e:
            logger.error(f'Error obteniendo contexto: {e}')
            return {}
    
    def _guardar_conversacion(self, tenant_id: str, cliente_numero: str, mensaje: str, respuesta: str):
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO "{schema_name}".conversaciones (cliente_numero, mensaje, respuesta, tipo, created_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (cliente_numero, mensaje, respuesta, 'ia'))
                conn.commit()
                logger.info(f'💬 [CONVERSACION] Guardada - Cliente: {cliente_numero}')
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
    
    # ==================== MÉTODOS DEL CARRITO ====================

    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        logger.info(f'💾 [CARRITO] Guardando - Cliente: {cliente_numero}, Items: {len(items)}, Total: ${total:,.0f}')
        logger.info(f'💾 [CARRITO] Items: {json.dumps(items, indent=2)}')
        
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id FROM "{schema_name}".carritos WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    existing = cur.fetchone()
                    
                    if existing:
                        cur.execute(f"""
                            UPDATE "{schema_name}".carritos 
                            SET items = %s, total = %s, updated_at = NOW()
                            WHERE cliente_numero = %s
                        """, (json.dumps(items), total, cliente_numero))
                        logger.info(f'💾 [CARRITO] Actualizado existente para {cliente_numero}')
                    else:
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".carritos (cliente_numero, items, total, created_at, updated_at)
                            VALUES (%s, %s, %s, NOW(), NOW())
                        """, (cliente_numero, json.dumps(items), total))
                        logger.info(f'💾 [CARRITO] Creado nuevo carrito para {cliente_numero}')
                    conn.commit()
                    
                    cur.execute(f"SELECT items, total FROM \"{schema_name}\".carritos WHERE cliente_numero = %s", (cliente_numero,))
                    verif = cur.fetchone()
                    logger.info(f'💾 [CARRITO] Verificación post-guardado - Items: {verif[0]}, Total: {verif[1]}')
        except Exception as e:
            logger.error(f'Error guardando carrito: {e}')
            raise

    def _cargar_carrito(self, tenant_id: str, cliente_numero: str) -> dict:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT items, total FROM "{schema_name}".carritos WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    row = cur.fetchone()
                    if row:
                        items = row[0] if isinstance(row[0], list) else json.loads(row[0]) if row[0] else []
                        total = row[1] or 0
                        logger.info(f'📖 [CARRITO] Cargado - Cliente: {cliente_numero}, Items: {len(items)}, Total: ${total:,.0f}')
                        if items:
                            logger.info(f'📖 [CARRITO] Items: {json.dumps(items, indent=2)}')
                        return {'items': items, 'total': total}
                    logger.info(f'📖 [CARRITO] Carrito vacío para {cliente_numero}')
                    return {'items': [], 'total': 0}
        except Exception as e:
            logger.error(f'Error cargando carrito: {e}')
            return {'items': [], 'total': 0}
        
    def _agregar_al_carrito(self, tenant_id: str, cliente_numero: str, productos: list):
        logger.info(f'🛒 [AGREGAR] Productos a agregar: {json.dumps(productos, indent=2)}')
        
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        logger.info(f'🛒 [AGREGAR] Carrito antes: {json.dumps(carrito, indent=2)}')
        
        for p in productos:
            encontrado = False
            for item in carrito['items']:
                if item.get('nombre') == p.get('nombre'):
                    vieja_cantidad = item['cantidad']
                    item['cantidad'] = item.get('cantidad', 1) + p.get('cantidad', 1)
                    logger.info(f'🛒 [AGREGAR] Actualizado: {p.get("nombre")} - cantidad: {vieja_cantidad} → {item["cantidad"]}')
                    encontrado = True
                    break
            if not encontrado:
                carrito['items'].append({
                    'nombre': p.get('nombre'),
                    'precio': p.get('precio', 0),
                    'cantidad': p.get('cantidad', 1)
                })
                logger.info(f'🛒 [AGREGAR] Nuevo producto: {p.get("nombre")} x{p.get("cantidad", 1)}')
            carrito['total'] += p.get('precio', 0) * p.get('cantidad', 1)
        
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
        self._log_carrito(tenant_id, cliente_numero, "DESPUÉS DE AGREGAR")
    
    def _log_carrito(self, tenant_id: str, cliente_numero: str, accion: str):
        try:
            carrito = self._cargar_carrito(tenant_id, cliente_numero)
            logger.info(f"📊 [CARRITO] {accion} - Cliente: {cliente_numero}")
            logger.info(f"📊 [CARRITO] Items: {json.dumps(carrito.get('items', []), indent=2)}")
            logger.info(f"📊 [CARRITO] Total: ${carrito.get('total', 0):,.0f}")
            logger.info(f"📊 [CARRITO] Cantidad de items: {len(carrito.get('items', []))}")
        except Exception as e:
            logger.error(f"Error logging carrito: {e}")

    def _log_pedido(self, tenant_id: str, pedido: dict, accion: str):
        try:
            logger.info(f"📦 [PEDIDO] {accion}")
            logger.info(f"📦 [PEDIDO] ID: {pedido.get('id')}")
            logger.info(f"📦 [PEDIDO] Número: {pedido.get('numero_pedido')}")
            logger.info(f"📦 [PEDIDO] Cliente: {pedido.get('cliente_numero')}")
            logger.info(f"📦 [PEDIDO] Items: {json.dumps(pedido.get('items', []), indent=2)}")
            logger.info(f"📦 [PEDIDO] Total: ${pedido.get('total', 0):,.0f}")
            logger.info(f"📦 [PEDIDO] Estado: {pedido.get('estado')}")
        except Exception as e:
            logger.error(f"Error logging pedido: {e}")
    
    # ==================== MÉTODOS DEL CLIENTE ====================
    
    def _obtener_cliente(self, tenant_id: str, cliente_numero: str) -> dict:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT nombre, cc, email, direccion, numero_telefono
                        FROM "{schema_name}".clientes WHERE numero_telefono = %s
                    """, (cliente_numero,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'nombre': row[0],
                            'cc': row[1],
                            'email': row[2],
                            'direccion': row[3],
                            'telefono': row[4]
                        }
                    return {}
        except Exception as e:
            logger.error(f'Error obteniendo cliente: {e}')
            return {}
    
    def _guardar_datos_cliente_en_bd(self, tenant_id: str, numero: str):
        if numero not in self._datos_cliente:
            return
        datos = self._datos_cliente[numero]
        if not any(datos.values()):
            return
        
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT id FROM "{schema_name}".clientes WHERE numero_telefono = %s', (numero,))
                    row = cur.fetchone()
                    
                    if row:
                        updates = []
                        params = []
                        if datos.get('nombre'):
                            updates.append("nombre = %s")
                            params.append(datos['nombre'])
                        if datos.get('cc'):
                            updates.append("cc = %s")
                            params.append(datos['cc'])
                        if datos.get('email'):
                            updates.append("email = %s")
                            params.append(datos['email'])
                        if datos.get('direccion'):
                            updates.append("direccion = %s")
                            params.append(datos['direccion'])
                        if updates:
                            params.append(row[0])
                            cur.execute(f'UPDATE "{schema_name}".clientes SET {", ".join(updates)}, updated_at = NOW() WHERE id = %s', params)
                            logger.info(f'👤 [CLIENTE] Actualizado: {numero}')
                    else:
                        cliente_id = str(uuid.uuid4())
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".clientes (id, numero_telefono, nombre, cc, email, direccion)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (cliente_id, numero, datos.get('nombre'), datos.get('cc'), datos.get('email'), datos.get('direccion')))
                        logger.info(f'👤 [CLIENTE] Creado nuevo: {numero}')
                    conn.commit()
        except Exception as e:
            logger.error(f'Error guardando cliente en BD: {e}')
    
    def _get_resumen_cliente(self, tenant_id: str, cliente_numero: str) -> str:
        cliente = self._obtener_cliente(tenant_id, cliente_numero)
        if cliente and any(cliente.values()):
            return f"""📋 DATOS DEL CLIENTE:
- Nombre: {cliente.get('nombre', 'N/A')}
- Cédula: {cliente.get('cc', 'N/A')}
- Teléfono: {cliente.get('telefono', 'N/A')}
- Email: {cliente.get('email', 'N/A')}
- Dirección: {cliente.get('direccion', 'N/A')}"""
        return "📋 DATOS DEL CLIENTE: No hay datos previos"
    
    def _get_carrito_info_para_prompt(self, tenant_id: str, cliente_numero: str) -> str:
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        if not carrito.get('items'):
            return "Carrito vacío"
        items_texto = "\n".join([f"- {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}" for item in carrito['items']])
        return f"📦 CARRITO ACTUAL:\n{items_texto}\n💰 Total: ${carrito.get('total', 0):,.0f}"
    
    def _formatear_datos_cliente(self, datos: dict) -> str:
        if not datos:
            return ""
        texto = ""
        if datos.get('nombre'):
            texto += f"\n📝 **Nombre:** {datos['nombre']}"
        if datos.get('cc'):
            texto += f"\n🆔 **Cédula:** {datos['cc']}"
        if datos.get('telefono'):
            texto += f"\n📞 **Teléfono:** {datos['telefono']}"
        if datos.get('email'):
            texto += f"\n📧 **Email:** {datos['email']}"
        if datos.get('direccion'):
            texto += f"\n📍 **Dirección:** {datos['direccion']}"
        if datos.get('fecha_entrega'):
            texto += f"\n📅 **Fecha:** {datos['fecha_entrega']}"
        if datos.get('hora_entrega'):
            texto += f"\n⏰ **Hora:** {datos['hora_entrega']}"
        if datos.get('recojo_en_tienda'):
            texto += f"\n🏪 **Recojo en tienda**"
        if datos.get('pago_contraentrega'):
            texto += f"\n💰 **Pago:** Contraentrega"
        return texto
    
    def _finalizar_pedido(self, tenant: dict, numero: str, carrito: dict) -> str:
        logger.info(f"🎯 [FINALIZAR] Iniciando finalización para cliente {numero}")
        logger.info(f"🎯 [FINALIZAR] Carrito: {json.dumps(carrito, indent=2)}")
        
        if not carrito or not carrito.get('items'):
            logger.warning(f"🎯 [FINALIZAR] Carrito vacío para {numero}")
            return "No hay productos en tu carrito. ¿Qué te gustaría ordenar?"
        
        datos_cliente = self._datos_cliente.get(numero, {})
        schema_name = self._get_schema_name(tenant['id'])
        
        contexto = self._obtener_contexto_tenant(tenant['id'])
        direccion_entrega = datos_cliente.get('direccion', '')
        if datos_cliente.get('recojo_en_tienda'):
            direccion_entrega = f"Recojo en tienda - {tenant.get('nombre')} - {contexto.get('ubicacion', '')}"
        
        cliente_id = self._obtener_o_crear_cliente(tenant['id'], numero, datos_cliente)
        if not cliente_id:
            logger.error(f"🎯 [FINALIZAR] Error creando cliente {numero}")
            return "❌ Hubo un error con tus datos. Por favor intenta de nuevo."
        
        pedido_id = str(uuid.uuid4())
        items = carrito['items']
        total = carrito['total']
        
        with db_manager.get_connection(tenant['id']) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COALESCE(MAX(secuencial), 0) + 1 FROM "{schema_name}".pedidos')
                secuencial = cur.fetchone()[0] or 1
        
        fecha_str = datetime.now().strftime('%Y%m%d%H%M%S')
        numero_pedido = f"{tenant['nombre'][:3].upper()}-{fecha_str}-{str(uuid.uuid4())[:4].upper()}"
        
        logger.info(f"🎯 [FINALIZAR] Generando pedido ID: {pedido_id}, Número: {numero_pedido}, Total: ${total:,.0f}")
        
        try:
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        DO $$ 
                        BEGIN
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                        WHERE table_schema = '{schema_name}' AND table_name = 'pedidos' AND column_name = 'cliente_numero') THEN
                                ALTER TABLE "{schema_name}".pedidos ADD COLUMN cliente_numero TEXT;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                        WHERE table_schema = '{schema_name}' AND table_name = 'pedidos' AND column_name = 'secuencial') THEN
                                ALTER TABLE "{schema_name}".pedidos ADD COLUMN secuencial INTEGER;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                        WHERE table_schema = '{schema_name}' AND table_name = 'pedidos' AND column_name = 'numero_pedido') THEN
                                ALTER TABLE "{schema_name}".pedidos ADD COLUMN numero_pedido TEXT;
                            END IF;
                        END $$;
                    """)
                    conn.commit()
                    
                    cur.execute(f'INSERT INTO "{schema_name}".pedidos (id, cliente_id, cliente_numero, numero_pedido, secuencial, items, total, estado, direccion_entrega, notas) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)', (pedido_id, cliente_id, numero, numero_pedido, secuencial, json.dumps(items), total, 'nuevo', direccion_entrega, f"Fecha: {datos_cliente.get('fecha_entrega', '')} Hora: {datos_cliente.get('hora_entrega', '')}".strip()))
                conn.commit()
                
                cur.execute(f'SELECT * FROM "{schema_name}".pedidos WHERE id = %s', (pedido_id,))
                pedido_guardado = cur.fetchone()
                if pedido_guardado:
                    logger.info(f"🎯 [FINALIZAR] Pedido guardado exitosamente en BD")
                else:
                    logger.error(f"🎯 [FINALIZAR] ERROR: Pedido no encontrado después de insertar")
            
            self._guardar_carrito(tenant['id'], numero, [], 0)
            if numero in self._datos_cliente:
                del self._datos_cliente[numero]
            
            items_texto = "\n".join([f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}" for item in items])
            datos_texto = self._formatear_datos_cliente(datos_cliente)
            
            logger.info(f"🎯 [FINALIZAR] Éxito! Pedido {numero_pedido} creado para {numero}")
            
            return f"""✅ **¡PEDIDO CONFIRMADO!**

📌 **Número de pedido:** *{numero_pedido}*
📝 *Guarda este número para hacer seguimiento*
{datos_texto}

📋 **Productos:**
{items_texto}
💰 **Total:** ${total:,.0f}

📦 **Entrega:** {direccion_entrega}

📌 *Cuando completes el pago, avísame para empezar a preparar tu pedido.*
📞 *Para consultar tu pedido, envía "estado {numero_pedido}"*"""
        except Exception as e:
            logger.error(f'Error creando pedido: {e}')
            import traceback
            traceback.print_exc()
            return "❌ Hubo un error procesando tu solicitud. Por favor intenta de nuevo."
    
    def _obtener_o_crear_cliente(self, tenant_id: str, numero: str, datos_cliente: dict = None) -> str:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT id, nombre, cc, email, direccion FROM "{schema_name}".clientes WHERE numero_telefono = %s', (numero,))
                    row = cur.fetchone()
                    
                    if row:
                        cliente_id = row[0]
                        if datos_cliente:
                            updates, params = [], []
                            if datos_cliente.get('nombre') and not row[1]:
                                updates.append("nombre = %s")
                                params.append(datos_cliente['nombre'])
                            if datos_cliente.get('cc') and not row[2]:
                                updates.append("cc = %s")
                                params.append(datos_cliente['cc'])
                            if datos_cliente.get('email') and not row[3]:
                                updates.append("email = %s")
                                params.append(datos_cliente['email'])
                            if datos_cliente.get('direccion') and not row[4]:
                                updates.append("direccion = %s")
                                params.append(datos_cliente['direccion'])
                            if updates:
                                params.append(cliente_id)
                                cur.execute(f'UPDATE "{schema_name}".clientes SET {", ".join(updates)}, updated_at = NOW() WHERE id = %s', params)
                                conn.commit()
                        return cliente_id
                    else:
                        cliente_id = str(uuid.uuid4())
                        cur.execute(f'INSERT INTO "{schema_name}".clientes (id, numero_telefono, nombre, cc, email, direccion) VALUES (%s, %s, %s, %s, %s, %s)', (cliente_id, numero, datos_cliente.get('nombre') if datos_cliente else None, datos_cliente.get('cc') if datos_cliente else None, datos_cliente.get('email') if datos_cliente else None, datos_cliente.get('direccion') if datos_cliente else None))
                        conn.commit()
                        return cliente_id
        except Exception as e:
            logger.error(f'Error gestionando cliente: {e}')
            return None
    
    # ==================== HISTORIAL ====================
    
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 10) -> list:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT mensaje, respuesta FROM "{schema_name}".conversaciones 
                        WHERE cliente_numero = %s ORDER BY created_at ASC LIMIT %s
                    """, (cliente_numero, limit))
                    rows = cur.fetchall()
                    logger.info(f'📜 [HISTORIAL] Obtenido {len(rows)} mensajes para {cliente_numero}')
                    return rows
        except Exception as e:
            logger.error(f'Error obteniendo historial: {e}')
            return []
    
    def _formatear_historial_para_prompt(self, historial: list) -> str:
        if not historial:
            return ""
        texto = "\n📜 HISTORIAL DE LA CONVERSACIÓN:\n"
        for h in historial:
            texto += f"Cliente: {h[0]}\nAsistente: {h[1]}\n"
        return texto
    
    # ==================== DETECCIÓN DE PRODUCTOS CON IA ====================
    
    def _extraer_productos_con_ia(self, texto: str, menu: list) -> list:
        """Usa IA para extraer productos del mensaje del cliente"""
        if not ai_client.client or not menu:
            return []
        
        prompt = f"""
        Extrae los productos que el cliente quiere comprar del siguiente mensaje.
        
        MENSAJE: "{texto}"
        
        CATÁLOGO DE PRODUCTOS:
        {json.dumps([{'nombre': p['nombre'], 'precio': p['precio']} for p in menu], indent=2, ensure_ascii=False)}
        
        IMPORTANTE:
        - El cliente puede escribir en lenguaje natural
        - Relaciona lo que pide con el nombre más cercano del catálogo
        - Extrae la cantidad (si no se especifica, es 1)
        
        Devuelve SOLO un JSON válido:
        {{"productos": [{{"nombre": "nombre exacto del catálogo", "cantidad": 1}}]}}
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300
            )
            contenido = response.choices[0].message.content
            contenido = contenido.replace('```json', '').replace('```', '').strip()
            resultado = json.loads(contenido)
            
            productos = []
            for p in resultado.get('productos', []):
                nombre = p.get('nombre', '')
                cantidad = p.get('cantidad', 1)
                for producto in menu:
                    if producto['nombre'].lower() == nombre.lower():
                        productos.append({
                            'nombre': producto['nombre'],
                            'precio': producto.get('precio', 0),
                            'cantidad': cantidad
                        })
                        break
            if productos:
                logger.info(f"🤖 [IA] Productos detectados: {productos}")
            return productos
        except Exception as e:
            logger.error(f"Error IA extrayendo productos: {e}")
            return []

    def _extraer_productos_del_historial_con_ia(self, historial: list, menu: list) -> list:
        """Usa IA para extraer productos de toda la conversación"""
        if not ai_client.client or not menu or not historial:
            return []
        
        texto_historial = "\n".join([f"Cliente: {h[0]}" for h in historial[-15:]])
        
        prompt = f"""
        Analiza la siguiente conversación y extrae los productos que el cliente quiere comprar.
        
        CONVERSACIÓN:
        {texto_historial}
        
        CATÁLOGO DE PRODUCTOS:
        {json.dumps([{'nombre': p['nombre'], 'precio': p['precio']} for p in menu], indent=2, ensure_ascii=False)}
        
        IMPORTANTE:
        - El cliente acaba de confirmar el pedido (dijo "confirmo" o "si")
        - Busca en la conversación qué productos pidió anteriormente
        - Relaciona con el nombre más cercano del catálogo
        - Extrae la cantidad
        
        Devuelve SOLO un JSON:
        {{"productos": [{{"nombre": "nombre exacto del catálogo", "cantidad": 1}}]}}
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=500
            )
            contenido = response.choices[0].message.content
            contenido = contenido.replace('```json', '').replace('```', '').strip()
            resultado = json.loads(contenido)
            
            productos = []
            for p in resultado.get('productos', []):
                nombre = p.get('nombre', '')
                cantidad = p.get('cantidad', 1)
                for producto in menu:
                    if producto['nombre'].lower() == nombre.lower():
                        productos.append({
                            'nombre': producto['nombre'],
                            'precio': producto.get('precio', 0),
                            'cantidad': cantidad
                        })
                        break
            if productos:
                logger.info(f"🤖 [IA] Productos encontrados en historial: {productos}")
            return productos
        except Exception as e:
            logger.error(f"Error IA extrayendo productos del historial: {e}")
            return []
    
    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _extraer_y_guardar_datos(self, texto: str, numero: str):
        if not ai_client.client:
            return
        
        prompt = f"""Extrae información del cliente del siguiente mensaje.
MENSAJE: "{texto}"
Devuelve SOLO un JSON: {{"nombre": "", "cc": "", "telefono": "", "email": "", "direccion": "", "fecha_entrega": "", "hora_entrega": "", "recojo_en_tienda": false, "pago_contraentrega": false}}"""
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300
            )
            contenido = response.choices[0].message.content
            contenido = contenido.replace('```json', '').replace('```', '').strip()
            datos = json.loads(contenido)
            
            if datos and any(datos.values()):
                if numero not in self._datos_cliente:
                    self._datos_cliente[numero] = {}
                for key, value in datos.items():
                    if value:
                        self._datos_cliente[numero][key] = value
                logger.info(f"📝 [DATOS] Extraídos: {datos}")
        except Exception as e:
            logger.error(f'Error extrayendo datos: {e}')
    
    def _cliente_confirmo(self, texto: str) -> bool:
        confirmaciones = ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'confirmar', 'proceder', 'adelante', 'esta bien', 'está bien', 'confirmo pedido']
        palabras_pago = ['pague', 'pago', 'pagado', 'transferí', 'consigné', 'pagué', 'ya pague', 'listo el pago']
        texto_lower = texto.lower().strip()
        es_confirmacion = texto_lower in confirmaciones or any(c in texto_lower for c in confirmaciones if len(c) > 2) or any(p in texto_lower for p in palabras_pago)
        if es_confirmacion:
            logger.info(f"✅ [CONFIRMACION] Detectada: {texto}")
        return es_confirmacion
    
    def _mostrar_resumen_carrito(self, tenant: dict, numero: str, carrito: dict) -> str:
        if not carrito.get('items'):
            return "No tienes productos en tu carrito. ¿Qué te gustaría ordenar?"
        items_texto = "\n".join([f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}" for item in carrito['items']])
        logger.info(f"📋 [RESUMEN] Mostrando carrito para {numero} - Total: ${carrito.get('total', 0):,.0f}")
        return f"""📋 **Tu pedido actual:**
{items_texto}
**Total:** ${carrito.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido? (responde "confirmo")"""
    
    def _procesar_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, contexto: dict) -> str:
        """Procesa el mensaje usando IA para lenguaje natural"""
        
        logger.info(f"🤖 [IA] Procesando mensaje: {texto[:100]}...")
        
        if not ai_client.client:
            logger.warning("⚠️ [IA] Cliente no disponible, usando fallback")
            return self._respuesta_fallback(tenant, menu)
        
        carrito_actual = self._cargar_carrito(tenant['id'], numero)
        logger.info(f"🤖 [IA] Carrito actual: {len(carrito_actual.get('items', []))} items, Total: ${carrito_actual.get('total', 0):,.0f}")
        
        resumen_cliente = self._get_resumen_cliente(tenant['id'], numero)
        historial = self._get_historial_conversacion(tenant['id'], numero, 15)
        historial_texto = self._formatear_historial_para_prompt(historial)
        
        self._extraer_y_guardar_datos(texto, numero)
        if numero in self._datos_cliente and self._datos_cliente[numero].get('nombre'):
            self._guardar_datos_cliente_en_bd(tenant['id'], numero)
        
        texto_lower = texto.lower()
        
        # 1. Verificar pago
        if any(p in texto_lower for p in ['pague', 'pago', 'pagado', 'transferí', 'consigné', 'pagué', 'ya pague', 'listo el pago']):
            logger.info("💰 [PAGO] Detectado mensaje de pago")
            try:
                resultado = order_repo.marcar_pagado(tenant['id'], numero)
                if resultado > 0:
                    return "✅ ¡Pago confirmado! En breve comenzamos a preparar tu pedido."
                else:
                    schema_name = self._get_schema_name(tenant['id'])
                    with db_manager.get_connection(tenant['id']) as conn:
                        with conn.cursor() as cur:
                            cur.execute(f'UPDATE "{schema_name}".pedidos SET estado = "pagado", pagado_at = NOW() WHERE cliente_numero = %s AND estado = "nuevo" ORDER BY created_at DESC LIMIT 1', (numero,))
                            if cur.rowcount > 0:
                                return "✅ ¡Pago confirmado! En breve comenzamos a preparar tu pedido."
                    return "✅ ¡Gracias por confirmar el pago! Procesaremos tu pedido."
            except Exception as e:
                logger.error(f"Error procesando pago: {e}")
                return "✅ Gracias por confirmar. Procesaremos tu pedido."
        
        # 2. Verificar confirmación - USANDO IA
        if self._cliente_confirmo(texto):
            logger.info(f"✅ [CONFIRMACION] Cliente confirmó: {texto}")
            if carrito_actual.get('items'):
                logger.info(f"✅ [CONFIRMACION] Carrito tiene items, finalizando pedido")
                self._guardar_datos_cliente_en_bd(tenant['id'], numero)
                return self._finalizar_pedido(tenant, numero, carrito_actual)
            else:
                logger.info(f"✅ [CONFIRMACION] Carrito vacío, usando IA para buscar productos en historial")
                productos_encontrados = self._extraer_productos_del_historial_con_ia(historial, menu)
                logger.info(f"🤖 [IA] Productos encontrados en historial: {productos_encontrados}")
                if productos_encontrados:
                    self._agregar_al_carrito(tenant['id'], numero, productos_encontrados)
                    carrito_actual = self._cargar_carrito(tenant['id'], numero)
                    if carrito_actual.get('items'):
                        return self._finalizar_pedido(tenant, numero, carrito_actual)
                return "❌ No pude identificar los productos que deseas. Por favor, escríbelos nuevamente.\n\nEjemplo: 'quiero 25 empanadas hawaianas'"
        
        # 3. Verificar consulta de carrito
        if any(p in texto_lower for p in ['qué pedí', 'mi pedido', 'ver carrito', 'que tengo']):
            logger.info(f"📋 [CONSULTA] Cliente consultó carrito")
            return self._mostrar_resumen_carrito(tenant, numero, carrito_actual)
        
        # 4. Detectar productos en el mensaje actual - USANDO IA
        productos_detectados = self._extraer_productos_con_ia(texto, menu)
        
        # 5. Si hay productos, agregar al carrito
        if productos_detectados:
            logger.info(f"🛒 [PRODUCTOS] Detectados por IA: {productos_detectados}")
            self._agregar_al_carrito(tenant['id'], numero, productos_detectados)
            nuevo_carrito = self._cargar_carrito(tenant['id'], numero)
            items_texto = "\n".join([f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}" for item in nuevo_carrito['items']])
            return f"""✅ **Agregado a tu pedido:**

{items_texto}
**Total:** ${nuevo_carrito.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido? (responde "confirmo" para finalizar)"""
        
        # 6. Si hay carrito, mostrar resumen
        if carrito_actual.get('items'):
            logger.info(f"📋 [CARRITO] Mostrando resumen, carrito no vacío")
            return self._mostrar_resumen_carrito(tenant, numero, carrito_actual)
        
        # 7. Si no hay carrito, usar IA para responder
        logger.info(f"🤖 [IA] Usando IA para respuesta general")
        menu_simplificado = [{'nombre': p.get('nombre'), 'precio': p.get('precio')} for p in menu[:30]]
        
        system_prompt = f"""Eres un asistente de ventas conversacional para {tenant.get('nombre', 'Mi negocio')}.

🏪 INFORMACIÓN:
- Horario: {contexto.get('horario', 'No especificado')}
- Ubicación: {contexto.get('ubicacion', 'No especificada')}

📋 PRODUCTOS:
{json.dumps(menu_simplificado, indent=2, ensure_ascii=False)}

{resumen_cliente}
{historial_texto}

INSTRUCCIONES IMPORTANTES:
1. Responde de forma natural, cálida y conversacional en español.
2. Cuando el cliente pida un producto, confirma los detalles.
3. Luego pregunta "¿Confirmas este pedido?".
4. NO generes números de pedido ni confirmes reservas.
5. Para finalizar, el cliente debe decir "confirmo".
6. Sé breve y cálido.

RESPONDE en español."""
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Cliente: {texto}\n\nAsistente:"}
                ],
                temperature=0.7,
                max_tokens=500
            )
            logger.info(f"🤖 [IA] Respuesta generada: {response.choices[0].message.content[:100]}...")
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f'Error en IA: {e}')
            return self._respuesta_fallback(tenant, menu)
    
    def _respuesta_fallback(self, tenant: dict, menu: list) -> str:
        if menu:
            primeros = menu[:3]
            sugerencias = ", ".join([p['nombre'] for p in primeros])
            return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿Te gustaría ordenar {sugerencias}? Escríbeme lo que deseas."
        return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿En qué puedo ayudarte?"


# Instancia global
message_handler = MessageHandler()