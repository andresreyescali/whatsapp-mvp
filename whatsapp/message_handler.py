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
        self._conversacion_activa = {}  # {numero: {estado, producto_temp, respuestas}}
    
    def _get_schema_name(self, tenant_id: str) -> str:
        tenant = tenant_repo.find_by_id(tenant_id)
        if tenant and tenant.get('schema_name'):
            return tenant['schema_name']
        return f"tenant_{tenant_id.replace('-', '_')}"
    
    def process(self, phone_id: str, numero: str, texto: str):
        logger.info(f'🟢 [PROCESS] Iniciando - Cliente: {numero}, Mensaje: {texto[:100]}')
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'⚠️ Tenant no encontrado para phone_id: {phone_id}')
            return
        
        logger.info(f"🏪 [TENANT] Encontrado: {tenant.get('nombre')} (ID: {tenant['id']})")
        
        schema_manager.ensure_schema(tenant['id'])
        
        # Obtener contexto de IA entrenado
        contexto = self._obtener_contexto_tenant(tenant['id'])
        menu = self._obtener_menu(tenant['id'])
        
        # Verificar si hay conversación activa de confirmación
        conv_activa = self._conversacion_activa.get(numero)
        
        if conv_activa and conv_activa.get('estado') == 'confirmando_pedido':
            logger.info(f"📌 [ESTADO] Confirmando pedido para {numero}")
            respuesta = self._procesar_confirmacion(texto, tenant, numero, conv_activa)
        else:
            respuesta = self._procesar_con_ia(tenant, menu, numero, texto, contexto)
        
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)
            logger.info(f"✅ [RESPUESTA] Enviada a {numero}")
        else:
            logger.warning(f"⚠️ [RESPUESTA] Vacía para {numero}")
    
    def _obtener_menu(self, tenant_id: str) -> list:
        """Obtiene el menú de productos (productos base con precios)"""
        logger.info(f"📋 [MENU] Obteniendo menú para tenant {tenant_id}")
        try:
            schema_name = self._get_schema_name(tenant_id)
            logger.info(f"📋 [MENU] Schema: {schema_name}")
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible,
                               imagen_url, tiempo_preparacion, destacado, es_base, metadata
                        FROM "{schema_name}".productos 
                        WHERE disponible = true AND es_base = true
                        ORDER BY categoria, nombre
                        LIMIT 100
                    """)
                    rows = cur.fetchall()
                    logger.info(f"📋 [MENU] Productos encontrados: {len(rows)}")
                    
                    productos = []
                    for row in rows:
                        productos.append({
                            'id': str(row[0]),
                            'nombre': row[1],
                            'descripcion': row[2] or '',
                            'precio': row[3],
                            'categoria': row[4] or 'general',
                            'disponible': row[5],
                        })
                    return productos
        except Exception as e:
            logger.error(f'❌ [MENU] Error: {e}')
            import traceback
            traceback.print_exc()
            return []
    
    def _obtener_contexto_tenant(self, tenant_id: str) -> dict:
        """Obtiene el contexto entrenado para el tenant"""
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
                logger.info(f"💾 [HISTORIAL] Guardado mensaje para {cliente_numero}")
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
    
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 10) -> list:
        """Obtiene el historial de conversación del cliente"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT mensaje, respuesta 
                        FROM "{schema_name}".conversaciones 
                        WHERE cliente_numero = %s 
                        ORDER BY created_at DESC 
                        LIMIT %s
                    """, (cliente_numero, limit))
                    rows = cur.fetchall()
                    return list(reversed(rows))
        except Exception as e:
            logger.error(f'Error obteniendo historial: {e}')
            return []
    
    def _cargar_carrito(self, tenant_id: str, cliente_numero: str) -> dict:
        """Carga el carrito actual del cliente"""
        logger.info(f"🛒 [CARGAR] Cargando carrito para {cliente_numero}")
        try:
            schema_name = self._get_schema_name(tenant_id)
            logger.info(f"🛒 [CARGAR] Schema: {schema_name}")
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT items, total FROM "{schema_name}".carritos WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    row = cur.fetchone()
                    
                    if row:
                        items = row[0] if isinstance(row[0], list) else json.loads(row[0]) if row[0] else []
                        total = row[1] or 0
                        logger.info(f"🛒 [CARGAR] Carrito encontrado: {len(items)} items, total ${total:,.0f}")
                        logger.info(f"🛒 [CARGAR] Items: {json.dumps(items, indent=2)}")
                        return {'items': items, 'total': total}
                    else:
                        logger.info(f"🛒 [CARGAR] No hay carrito para {cliente_numero}, creando nuevo")
                        return {'items': [], 'total': 0}
        except Exception as e:
            logger.error(f'❌ [CARGAR] Error: {e}')
            import traceback
            traceback.print_exc()
            return {'items': [], 'total': 0}
    
    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        """Guarda el carrito en la base de datos"""
        logger.info(f"💾 [GUARDAR] Guardando carrito para {cliente_numero}: {len(items)} items, total ${total:,.0f}")
        logger.info(f"💾 [GUARDAR] Items: {json.dumps(items, indent=2)}")
        
        try:
            schema_name = self._get_schema_name(tenant_id)
            logger.info(f"💾 [GUARDAR] Schema: {schema_name}")
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Verificar si ya existe
                    cur.execute(f"""
                        SELECT id FROM "{schema_name}".carritos WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    existing = cur.fetchone()
                    
                    items_json = json.dumps(items)
                    
                    if existing:
                        logger.info(f"💾 [GUARDAR] Actualizando carrito existente (ID: {existing[0]})")
                        cur.execute(f"""
                            UPDATE "{schema_name}".carritos 
                            SET items = %s, total = %s, updated_at = NOW()
                            WHERE cliente_numero = %s
                        """, (items_json, total, cliente_numero))
                    else:
                        logger.info(f"💾 [GUARDAR] Creando nuevo carrito")
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".carritos (cliente_numero, items, total, created_at, updated_at)
                            VALUES (%s, %s, %s, NOW(), NOW())
                        """, (cliente_numero, items_json, total))
                    
                    conn.commit()
                    logger.info(f"✅ [GUARDAR] Carrito guardado exitosamente")
                    
                    # Verificar post-guardado
                    cur.execute(f"""
                        SELECT items, total FROM "{schema_name}".carritos WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    verif = cur.fetchone()
                    if verif:
                        logger.info(f"✅ [VERIFICACION] Post-guardado: {len(verif[0]) if verif[0] else 0} items, total ${verif[1]:,.0f}")
                    
        except Exception as e:
            logger.error(f'❌ [GUARDAR] Error: {e}')
            import traceback
            traceback.print_exc()
    
    def _agregar_producto_al_carrito(self, tenant_id: str, cliente_numero: str, nombre: str, precio: int, cantidad: int = 1):
        """Agrega un producto al carrito directamente"""
        logger.info(f"🛒 [AGREGAR] ===== INICIO =====")
        logger.info(f"🛒 [AGREGAR] Producto: {nombre}")
        logger.info(f"🛒 [AGREGAR] Precio: ${precio:,}")
        logger.info(f"🛒 [AGREGAR] Cantidad: {cantidad}")
        logger.info(f"🛒 [AGREGAR] Cliente: {cliente_numero}")
        logger.info(f"🛒 [AGREGAR] Tenant: {tenant_id}")
        
        try:
            # Cargar carrito actual
            carrito = self._cargar_carrito(tenant_id, cliente_numero)
            logger.info(f"🛒 [AGREGAR] Carrito actual: {len(carrito['items'])} items, total ${carrito['total']:,.0f}")
            
            # Buscar si ya existe el mismo producto
            encontrado = False
            for i, item in enumerate(carrito['items']):
                if item.get('nombre') == nombre:
                    vieja_cantidad = item.get('cantidad', 1)
                    item['cantidad'] = vieja_cantidad + cantidad
                    carrito['total'] += precio * cantidad
                    logger.info(f"🛒 [AGREGAR] Producto existente encontrado en índice {i}")
                    logger.info(f"🛒 [AGREGAR] Cantidad anterior: {vieja_cantidad}, nueva: {item['cantidad']}")
                    encontrado = True
                    break
            
            if not encontrado:
                nuevo_item = {
                    'nombre': nombre,
                    'precio': precio,
                    'cantidad': cantidad
                }
                carrito['items'].append(nuevo_item)
                carrito['total'] += precio * cantidad
                logger.info(f"🛒 [AGREGAR] Nuevo producto agregado: {nuevo_item}")
            
            # Guardar carrito actualizado
            logger.info(f"🛒 [AGREGAR] Guardando carrito con {len(carrito['items'])} items, total ${carrito['total']:,.0f}")
            self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
            
            # Verificación final
            verificacion = self._cargar_carrito(tenant_id, cliente_numero)
            logger.info(f"🛒 [AGREGAR] Verificación final: {len(verificacion['items'])} items, total ${verificacion['total']:,.0f}")
            logger.info(f"🛒 [AGREGAR] ===== FIN OK =====")
            
            return True
            
        except Exception as e:
            logger.error(f'❌ [AGREGAR] Error: {e}')
            import traceback
            traceback.print_exc()
            return False
    
    def _limpiar_carrito(self, tenant_id: str, cliente_numero: str):
        """Limpia el carrito del cliente"""
        logger.info(f"🧹 [LIMPIAR] Limpiando carrito para {cliente_numero}")
        self._guardar_carrito(tenant_id, cliente_numero, [], 0)
        logger.info(f"✅ [LIMPIAR] Carrito limpiado")
    
    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _procesar_con_ia(self, tenant: dict, menu: list, numero: str, texto: str, contexto: dict) -> str:
        """Procesa el mensaje usando IA con Function Calling"""
        
        logger.info(f"🤖 [IA] ===== INICIO PROCESAMIENTO =====")
        logger.info(f"🤖 [IA] Cliente: {numero}")
        logger.info(f"🤖 [IA] Mensaje: {texto}")
        logger.info(f"🤖 [IA] Menú disponible: {len(menu)} productos")
        
        if not ai_client.client:
            logger.warning("⚠️ [IA] Cliente no disponible")
            return self._respuesta_fallback(tenant, menu)
        
        # Obtener historial y carrito
        historial = self._get_historial_conversacion(tenant['id'], numero, 10)
        carrito_actual = self._cargar_carrito(tenant['id'], numero)
        
        logger.info(f"🤖 [IA] Carrito actual: {len(carrito_actual.get('items', []))} items, total ${carrito_actual.get('total', 0):,.0f}")
        
        # Formatear menú para el prompt
        menu_texto = "\n".join([f"- {p['nombre']}: ${p['precio']:,}" for p in menu[:50]])
        
        # Preparar tools/function calling
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "agregar_producto_carrito",
                    "description": "Agrega un producto al carrito del cliente. Usa esta función cuando el cliente pida un producto específico.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nombre_producto": {
                                "type": "string",
                                "description": "El nombre exacto del producto según el menú"
                            },
                            "precio": {
                                "type": "integer",
                                "description": "El precio del producto"
                            },
                            "cantidad": {
                                "type": "integer",
                                "description": "La cantidad de productos (default: 1)",
                                "default": 1
                            }
                        },
                        "required": ["nombre_producto", "precio"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "ver_carrito",
                    "description": "Muestra el contenido actual del carrito",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "confirmar_pedido",
                    "description": "Confirma el pedido y procede a finalizarlo. Usa cuando el cliente dice 'si', 'confirmo' o similar.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }
        ]
        
        system_prompt = f"""
Eres un asistente de ventas para {tenant.get('nombre', 'el negocio')}.

INFORMACIÓN:
- Horario: {contexto.get('horario', 'No especificado')}
- Ubicación: {contexto.get('ubicacion', 'No especificada')}
- Políticas: {contexto.get('politicas', 'No especificadas')}

{contexto.get('instrucciones', '')}

MENÚ DE PRODUCTOS:
{menu_texto}

CARRITO ACTUAL:
{json.dumps(carrito_actual.get('items', []), indent=2, ensure_ascii=False)}
Total actual: ${carrito_actual.get('total', 0):,.0f}

INSTRUCCIONES:
1. Cuando el cliente pida un producto, usa la función 'agregar_producto_carrito'
2. Cuando el cliente quiera ver su pedido, usa 'ver_carrito'
3. Cuando el cliente confirme (diga "si", "confirmo"), usa 'confirmar_pedido'
4. Responde de forma natural y amable en español
"""
        
        try:
            logger.info("🤖 [IA] Enviando request a DeepSeek...")
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Cliente: {texto}"}
                ],
                temperature=0.7,
                max_tokens=500,
                tools=tools,
                tool_choice="auto"
            )
            
            message = response.choices[0].message
            logger.info(f"🤖 [IA] Respuesta recibida - Contenido: {message.content if message.content else 'None'}")
            logger.info(f"🤖 [IA] Tool calls: {len(message.tool_calls) if message.tool_calls else 0}")
            
            # Procesar tool calls
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    logger.info(f"🔧 [TOOL] Función llamada: {function_name}")
                    logger.info(f"🔧 [TOOL] Argumentos: {arguments}")
                    
                    if function_name == "agregar_producto_carrito":
                        nombre = arguments.get("nombre_producto")
                        precio = arguments.get("precio")
                        cantidad = arguments.get("cantidad", 1)
                        
                        logger.info(f"🔧 [TOOL] Agregando producto: '{nombre}', ${precio}, x{cantidad}")
                        
                        # Buscar precio real en el menú si es necesario
                        producto_real = None
                        for p in menu:
                            if p['nombre'].lower() == nombre.lower():
                                producto_real = p
                                break
                        
                        if producto_real:
                            logger.info(f"🔧 [TOOL] Producto encontrado en menú: {producto_real['nombre']} - ${producto_real['precio']}")
                            exito = self._agregar_producto_al_carrito(tenant['id'], numero, producto_real['nombre'], producto_real['precio'], cantidad)
                            
                            if exito:
                                logger.info(f"✅ [TOOL] Producto agregado exitosamente al carrito")
                                # Recargar carrito para mostrar
                                carrito_actualizado = self._cargar_carrito(tenant['id'], numero)
                                return f"""✅ *Agregado a tu pedido:*
• {cantidad}x {producto_real['nombre']}: ${producto_real['precio'] * cantidad:,.0f}

💰 *Total actual:* ${carrito_actualizado['total']:,.0f}

¿Algo más o confirmamos el pedido?"""
                            else:
                                logger.error(f"❌ [TOOL] Error al agregar producto al carrito")
                                return "❌ Hubo un error al agregar el producto. Por favor intenta de nuevo."
                        else:
                            logger.warning(f"⚠️ [TOOL] Producto '{nombre}' no encontrado en menú")
                            return f"❌ No encontré '{nombre}' en nuestro menú. ¿Puedes verificar el nombre?"
                    
                    elif function_name == "ver_carrito":
                        logger.info(f"🔧 [TOOL] Mostrando carrito")
                        carrito = self._cargar_carrito(tenant['id'], numero)
                        if not carrito['items']:
                            return "🛒 *Tu carrito está vacío.* ¿Qué te gustaría ordenar?"
                        
                        items_texto = ""
                        for item in carrito['items']:
                            items_texto += f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}\n"
                        
                        return f"""📋 *Tu pedido actual:*
{items_texto}
💰 *Total:* ${carrito['total']:,.0f}

¿Algo más o confirmamos el pedido?"""
                    
                    elif function_name == "confirmar_pedido":
                        logger.info(f"🔧 [TOOL] Confirmando pedido")
                        carrito_final = self._cargar_carrito(tenant['id'], numero)
                        if carrito_final and carrito_final.get('items'):
                            self._conversacion_activa[numero] = {
                                'estado': 'confirmando_pedido',
                                'productos': carrito_final['items'],
                                'total': carrito_final['total']
                            }
                            return self._mostrar_resumen_pedido(carrito_final['items'], carrito_final['total'])
                        else:
                            return "No hay productos en tu carrito para confirmar. ¿Qué te gustaría ordenar?"
            
            # Si no hay tool calls, devolver la respuesta normal
            logger.info(f"🤖 [IA] Respuesta sin tool calls: {message.content}")
            return message.content or self._respuesta_fallback(tenant, menu)
            
        except Exception as e:
            logger.error(f'❌ [IA] Error: {e}')
            import traceback
            traceback.print_exc()
            return self._respuesta_fallback(tenant, menu)
    
    def _mostrar_resumen_pedido(self, productos: list, total: int) -> str:
        """Muestra el resumen del pedido para confirmación"""
        items_texto = ""
        for p in productos:
            items_texto += f"• {p.get('cantidad', 1)}x {p.get('nombre')}: ${p.get('precio', 0) * p.get('cantidad', 1):,.0f}\n"
        
        return f"""📋 *Resumen de tu pedido:*

{items_texto}
💰 *Total:* ${total:,.0f}

¿Confirmas este pedido? (responde "sí" o "confirmo")"""
    
    def _procesar_confirmacion(self, texto: str, tenant: dict, numero: str, conv: dict) -> str:
        """Procesa la confirmación final del pedido"""
        confirmaciones = ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'confirmar', 
                          'proceder', 'adelante', 'esta bien', 'está bien']
        texto_lower = texto.lower().strip()
        es_confirmacion = texto_lower in confirmaciones or any(c in texto_lower for c in confirmaciones if len(c) > 2)
        
        logger.info(f"📌 [CONFIRMAR] Procesando confirmación: '{texto}' -> es_confirmacion={es_confirmacion}")
        
        if es_confirmacion:
            productos = conv.get('productos', [])
            total = conv.get('total', 0)
            
            logger.info(f"✅ [FINAL] Confirmando pedido para {numero}: {len(productos)} items, total ${total:,.0f}")
            logger.info(f"📦 [FINAL] Productos: {json.dumps(productos, indent=2)}")
            
            # Crear pedido
            pedido_id = str(uuid.uuid4())
            schema_name = self._get_schema_name(tenant['id'])
            
            logger.info(f"📦 [PEDIDO] Schema: {schema_name}")
            
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT COALESCE(MAX(secuencial), 0) + 1 FROM "{schema_name}".pedidos')
                    secuencial = cur.fetchone()[0] or 1
            
            fecha_str = datetime.now().strftime('%Y%m%d%H%M%S')
            numero_pedido = f"{tenant['nombre'][:3].upper()}-{fecha_str}-{str(uuid.uuid4())[:4].upper()}"
            logger.info(f"📦 [PEDIDO] Número generado: {numero_pedido}")
            
            try:
                with db_manager.get_connection(tenant['id']) as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".pedidos 
                            (id, cliente_numero, numero_pedido, secuencial, items, total, estado, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        """, (pedido_id, numero, numero_pedido, secuencial, json.dumps(productos), total, 'nuevo'))
                    conn.commit()
                
                logger.info(f"✅ [PEDIDO] Pedido creado: {pedido_id}")
                
                # Limpiar carrito después de crear pedido
                self._limpiar_carrito(tenant['id'], numero)
                self._conversacion_activa.pop(numero, None)
                
                items_texto = ""
                for p in productos:
                    items_texto += f"• {p.get('cantidad', 1)}x {p.get('nombre')}: ${p.get('precio', 0) * p.get('cantidad', 1):,.0f}\n"
                
                return f"""✅ *¡PEDIDO CONFIRMADO!*

📌 *Número de pedido:* {numero_pedido}

📋 *Productos:*
{items_texto}
💰 *Total:* ${total:,.0f}

📌 *Cuando completes el pago, avísame para empezar a preparar tu pedido.*"""
                
            except Exception as e:
                logger.error(f'❌ [PEDIDO] Error creando pedido: {e}')
                import traceback
                traceback.print_exc()
                return "❌ Hubo un error procesando tu pedido. Por favor intenta de nuevo."
        else:
            return "¿Confirmas el pedido? Responde 'sí' para finalizar o dime qué más quieres agregar."
    
    def _respuesta_fallback(self, tenant: dict, menu: list) -> str:
        """Respuesta por si la IA no está disponible"""
        if menu:
            return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿Qué te gustaría ordenar? Por ejemplo, 'quiero una torta negra de libra'."
        return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿En qué puedo ayudarte?"


# Instancia global
message_handler = MessageHandler()