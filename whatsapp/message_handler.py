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
        """Obtiene el menú completo de productos (sin filtrar por es_base)"""
        logger.info(f"📋 [MENU] Obteniendo menú para tenant {tenant_id}")
        try:
            schema_name = self._get_schema_name(tenant_id)
            logger.info(f"📋 [MENU] Schema: {schema_name}")
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Mostrar TODOS los productos disponibles
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible
                        FROM "{schema_name}".productos 
                        WHERE disponible = true
                        ORDER BY categoria, nombre
                        LIMIT 200
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
        """Obtiene el contexto entrenado para the tenant"""
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
    
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 20) -> list:
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
                    
        except Exception as e:
            logger.error(f'❌ [GUARDAR] Error: {e}')
            import traceback
            traceback.print_exc()
    
    def _agregar_producto_al_carrito(self, tenant_id: str, cliente_numero: str, nombre: str, precio: int, cantidad: int = 1):
        """Agrega un producto estándar al carrito"""
        logger.info(f"🛒 [AGREGAR] Producto estándar: {nombre} - ${precio:,} x{cantidad}")
        
        try:
            carrito = self._cargar_carrito(tenant_id, cliente_numero)
            
            # Buscar si ya existe el mismo producto (sin personalización)
            encontrado = False
            for item in carrito['items']:
                if item.get('nombre') == nombre and not item.get('personalizado'):
                    item['cantidad'] = item.get('cantidad', 1) + cantidad
                    carrito['total'] += precio * cantidad
                    encontrado = True
                    break
            
            if not encontrado:
                carrito['items'].append({
                    'nombre': nombre,
                    'precio': precio,
                    'cantidad': cantidad,
                    'personalizado': False
                })
                carrito['total'] += precio * cantidad
            
            self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
            logger.info(f"✅ [AGREGAR] Producto agregado. Total: ${carrito['total']:,.0f}")
            
            return True
            
        except Exception as e:
            logger.error(f'❌ [AGREGAR] Error: {e}')
            return False
    
    def _limpiar_carrito(self, tenant_id: str, cliente_numero: str):
        """Limpia el carrito del cliente"""
        logger.info(f"🧹 [LIMPIAR] Limpiando carrito para {cliente_numero}")
        self._guardar_carrito(tenant_id, cliente_numero, [], 0)
        logger.info(f"✅ [LIMPIAR] Carrito limpiado")
    
    # ==================== FUNCIONES AUXILIARES PARA PROMPT ====================
    
    def _formatear_historial_para_prompt(self, historial: list) -> str:
        """Formatea el historial de la conversación para el prompt de IA"""
        if not historial:
            return ""
        
        texto = "\n📜 HISTORIAL DE LA CONVERSACIÓN (mensajes recientes):\n"
        for h in historial[-15:]:
            texto += f"Cliente: {h[0]}\nAsistente: {h[1]}\n"
        
        texto += "\n⚠️ IMPORTANTE: Usa esta información para NO repetir preguntas ya respondidas.\n"
        return texto
    
    def _formatear_carrito_para_prompt(self, carrito: dict) -> str:
        """Formatea el carrito actual para el prompt"""
        if not carrito or not carrito.get('items'):
            return ""
        
        texto = "\n🛒 PRODUCTOS ACTUALES EN EL CARRITO:\n"
        for item in carrito['items']:
            texto += f"- {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}\n"
            if item.get('sabor'):
                texto += f"     └─ Sabor: {item.get('sabor')}\n"
            if item.get('tamanio'):
                texto += f"     └─ Tamaño: {item.get('tamanio')}\n"
            if item.get('decoraciones'):
                texto += f"     └─ Decoraciones: {', '.join(item.get('decoraciones'))}\n"
        texto += f"💰 Total actual en carrito: ${carrito.get('total', 0):,.0f}\n"
        return texto
    
    def _formatear_menu_para_prompt(self, menu: list) -> str:
        """Formatea el menú completo para el prompt de IA"""
        if not menu:
            return "No hay productos disponibles"
        
        texto = "\n📋 CATÁLOGO DE PRODUCTOS:\n"
        for p in menu[:100]:
            texto += f"- {p['nombre']}: ${p['precio']:,}\n"
        
        texto += "\n📌 El cliente puede pedir cualquier producto de esta lista.\n"
        return texto
    
    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _procesar_con_ia(self, tenant: dict, menu: list, numero: str, texto: str, contexto: dict) -> str:
        """Procesa el mensaje usando IA con Function Calling"""
        
        logger.info(f"🤖 [IA] Procesando: {texto[:100]}...")
        
        if not ai_client.client:
            return self._respuesta_fallback(tenant, menu)
        
        # ========== VERIFICAR CONFIRMACIÓN PRIMERO ==========
        if self._es_confirmacion(texto):
            logger.info(f"✅ [CONFIRMACION] Detectada para {numero}")
            carrito_final = self._cargar_carrito(tenant['id'], numero)
            
            if carrito_final and carrito_final.get('items'):
                logger.info(f"🛒 [CARRITO] Carrito con {len(carrito_final['items'])} items, total ${carrito_final['total']:,.0f}")
                self._conversacion_activa[numero] = {
                    'estado': 'confirmando_pedido',
                    'productos': carrito_final['items'],
                    'total': carrito_final['total']
                }
                return self._mostrar_resumen_pedido(carrito_final['items'], carrito_final['total'])
            else:
                logger.warning(f"⚠️ [CONFIRMACION] Carrito vacío para {numero}")
                return "No hay productos en tu carrito. ¿Qué te gustaría ordenar? Por favor, primero dime qué producto deseas."
        
        # ========== VERIFICAR SI QUIERE VER EL CARRITO ==========
        if any(p in texto.lower() for p in ['ver carrito', 'mi pedido', 'qué pedí', 'que tengo', 'resumen']):
            carrito = self._cargar_carrito(tenant['id'], numero)
            if carrito.get('items'):
                return self._mostrar_resumen_pedido(carrito['items'], carrito['total'])
            else:
                return "🛒 Tu carrito está vacío. ¿Qué te gustaría ordenar?"
        
        # ========== VERIFICAR SI ES UN MENSAJE POST-PEDIDO ==========
        # Si el cliente ya confirmó y ahora habla de pago, no mostrar "carrito vacío"
        if any(p in texto.lower() for p in ['pago', 'contraentrega', 'transferencia', 'efectivo', 'pagué', 'consigné']):
            return "Perfecto, el pago se realizará contra entrega. Tu pedido ya está confirmado y en proceso de preparación. ¿Necesitas algo más?"
        
        # ========== OBTENER HISTORIAL Y CARRITO ==========
        historial = self._get_historial_conversacion(tenant['id'], numero, 15)
        historial_texto = self._formatear_historial_para_prompt(historial)
        carrito_actual = self._cargar_carrito(tenant['id'], numero)
        carrito_texto = self._formatear_carrito_para_prompt(carrito_actual)
        
        # Formatear menú completo
        menu_texto = self._formatear_menu_para_prompt(menu)
        
        # Tools para Function Calling
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "agregar_producto_carrito",
                    "description": "Agrega un producto estándar al carrito del cliente.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nombre_producto": {"type": "string"},
                            "precio": {"type": "integer"},
                            "cantidad": {"type": "integer", "default": 1}
                        },
                        "required": ["nombre_producto", "precio"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "agregar_producto_personalizado",
                    "description": "Agrega un producto personalizado al carrito (con sabor, tamaño, decoraciones).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nombre_base": {"type": "string"},
                            "precio": {"type": "integer"},
                            "sabor": {"type": "string"},
                            "tamanio": {"type": "string"},
                            "decoraciones": {"type": "array", "items": {"type": "string"}},
                            "cantidad": {"type": "integer", "default": 1}
                        },
                        "required": ["nombre_base", "precio"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "ver_carrito",
                    "description": "Muestra el contenido actual del carrito",
                    "parameters": {"type": "object", "properties": {}, "required": []}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "confirmar_pedido",
                    "description": "Confirma el pedido. Usa cuando el cliente dice 'si', 'confirmo'.",
                    "parameters": {"type": "object", "properties": {}, "required": []}
                }
            }
        ]
        
        system_prompt = f"""
Eres un asistente de ventas conversacional para {tenant.get('nombre', 'el negocio')}.

🏪 INFORMACIÓN:
- Horario: {contexto.get('horario', 'No especificado')}
- Ubicación: {contexto.get('ubicacion', 'No especificada')}
- Políticas: {contexto.get('politicas', 'No especificadas')}

{contexto.get('instrucciones', '')}

{menu_texto}

{carrito_texto}

{historial_texto}

INSTRUCCIONES IMPORTANTES:
1. Cuando el cliente pida un producto del menú, usa 'agregar_producto_carrito'
2. Cuando el cliente personalice un producto, usa 'agregar_producto_personalizado'
3. Cuando el cliente confirme, usa 'confirmar_pedido'
4. NUNCA agregues el mismo producto personalizado dos veces. Si el cliente corrige el precio, actualiza el existente.
5. Si el cliente habla de pago después de confirmar, responde amablemente sin mostrar "carrito vacío"
6. Responde de forma natural en español

RESPONDE en español.
"""
        
        try:
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
            logger.info(f"🤖 [IA] Tool calls: {len(message.tool_calls) if message.tool_calls else 0}")
            
            # Procesar tool calls
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    logger.info(f"🔧 [TOOL] {function_name}: {arguments}")
                    
                    if function_name == "agregar_producto_carrito":
                        nombre = arguments.get("nombre_producto")
                        precio = arguments.get("precio")
                        cantidad = arguments.get("cantidad", 1)
                        
                        producto_real = None
                        for p in menu:
                            if p['nombre'].lower() == nombre.lower():
                                producto_real = p
                                break
                        
                        if producto_real:
                            self._agregar_producto_al_carrito(tenant['id'], numero, producto_real['nombre'], producto_real['precio'], cantidad)
                            carrito_actualizado = self._cargar_carrito(tenant['id'], numero)
                            return f"""✅ *Agregado a tu pedido:*
• {cantidad}x {producto_real['nombre']}: ${producto_real['precio'] * cantidad:,.0f}

💰 *Total actual:* ${carrito_actualizado['total']:,.0f}

¿Algo más o confirmamos el pedido? (responde "confirmo")"""
                        else:
                            return f"❌ No encontré '{nombre}' en nuestro catálogo. ¿Puedes verificar el nombre?"
                    
                    elif function_name == "agregar_producto_personalizado":
                        nombre_base = arguments.get("nombre_base", "Producto")
                        precio = arguments.get("precio")
                        sabor = arguments.get("sabor")
                        tamanio = arguments.get("tamanio")
                        decoraciones = arguments.get("decoraciones", [])
                        cantidad = arguments.get("cantidad", 1)
                        
                        nombre_mostrar = nombre_base
                        if sabor:
                            nombre_mostrar = f"{sabor} {nombre_base}"
                        if tamanio:
                            nombre_mostrar = f"{nombre_mostrar} ({tamanio})"
                        
                        # Verificar si ya existe el mismo producto personalizado
                        carrito_actual = self._cargar_carrito(tenant['id'], numero)
                        encontrado = False
                        for item in carrito_actual['items']:
                            if (item.get('personalizado') and 
                                item.get('nombre_base') == nombre_base and
                                item.get('sabor') == sabor and 
                                item.get('tamanio') == tamanio):
                                # Actualizar precio
                                item['precio'] = precio
                                item['cantidad'] = item.get('cantidad', 1) + cantidad
                                # Recalcular total
                                carrito_actual['total'] = sum(i.get('precio', 0) * i.get('cantidad', 1) for i in carrito_actual['items'])
                                self._guardar_carrito(tenant['id'], numero, carrito_actual['items'], carrito_actual['total'])
                                encontrado = True
                                logger.info(f"🛒 [PERSONALIZADO] Producto existente actualizado")
                                break
                        
                        if not encontrado:
                            self._agregar_producto_personalizado_al_carrito(
                                tenant['id'], numero, nombre_mostrar, precio, 
                                sabor, tamanio, decoraciones, cantidad
                            )
                        
                        carrito_actualizado = self._cargar_carrito(tenant['id'], numero)
                        
                        detalle = ""
                        if sabor:
                            detalle += f"\n   └─ Sabor: {sabor}"
                        if tamanio:
                            detalle += f"\n   └─ Tamaño: {tamanio}"
                        if decoraciones:
                            detalle += f"\n   └─ Decoraciones: {', '.join(decoraciones)}"
                        
                        return f"""✅ *Agregado a tu pedido (Personalizado):*
• {cantidad}x {nombre_mostrar}: ${precio * cantidad:,.0f}{detalle}

💰 *Total actual:* ${carrito_actualizado['total']:,.0f}

¿Algo más o confirmamos el pedido? (responde "confirmo")"""
                    
                    elif function_name == "ver_carrito":
                        carrito = self._cargar_carrito(tenant['id'], numero)
                        if not carrito['items']:
                            return "🛒 *Tu carrito está vacío.* ¿Qué te gustaría ordenar?"
                        
                        items_texto = ""
                        for item in carrito['items']:
                            items_texto += f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}\n"
                            if item.get('sabor'):
                                items_texto += f"     └─ Sabor: {item.get('sabor')}\n"
                            if item.get('tamanio'):
                                items_texto += f"     └─ Tamaño: {item.get('tamanio')}\n"
                            if item.get('decoraciones'):
                                items_texto += f"     └─ Decoraciones: {', '.join(item.get('decoraciones'))}\n"
                        
                        return f"""📋 *Tu pedido actual:*
{items_texto}
💰 *Total:* ${carrito['total']:,.0f}

¿Algo más o confirmamos el pedido?"""
                    
                    elif function_name == "confirmar_pedido":
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
            
            # Si no hay tool calls, guardar y devolver respuesta
            if message.content:
                self._guardar_conversacion(tenant['id'], numero, texto, message.content)
            return message.content or self._respuesta_fallback(tenant, menu)
            
        except Exception as e:
            logger.error(f'Error en IA: {e}')
            import traceback
            traceback.print_exc()
            return self._respuesta_fallback(tenant, menu)
    
    def _es_confirmacion(self, texto: str) -> bool:
        """Detecta si el cliente quiere confirmar el pedido"""
        confirmaciones = ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'confirmar', 
                          'proceder', 'adelante', 'esta bien', 'está bien', 'confirmo pedido']
        texto_lower = texto.lower().strip()
        return texto_lower in confirmaciones or any(c in texto_lower for c in confirmaciones if len(c) > 2)
    
    def _mostrar_resumen_pedido(self, productos: list, total: int) -> str:
        """Muestra el resumen del pedido para confirmación"""
        if not productos:
            return "No tengo productos en tu pedido. ¿Qué te gustaría ordenar?"
        
        items_texto = ""
        for p in productos:
            items_texto += f"• {p.get('cantidad', 1)}x {p.get('nombre')}: ${p.get('precio', 0) * p.get('cantidad', 1):,.0f}\n"
            if p.get('sabor'):
                items_texto += f"     └─ Sabor: {p.get('sabor')}\n"
            if p.get('tamanio'):
                items_texto += f"     └─ Tamaño: {p.get('tamanio')}\n"
            if p.get('decoraciones'):
                items_texto += f"     └─ Decoraciones: {', '.join(p.get('decoraciones'))}\n"
        
        return f"""📋 *Resumen de tu pedido:*

{items_texto}
💰 *Total:* ${total:,.0f}

¿Confirmas este pedido? (responde "sí" o "confirmo")"""
    
    def _procesar_confirmacion(self, texto: str, tenant: dict, numero: str, conv: dict) -> str:
        """Procesa la confirmación final del pedido"""
        if self._es_confirmacion(texto):
            productos = conv.get('productos', [])
            total = conv.get('total', 0)
            
            logger.info(f"✅ [FINAL] Confirmando pedido para {numero}: {len(productos)} items, total ${total:,.0f}")
            logger.info(f"📦 [FINAL] Productos: {json.dumps(productos, indent=2)}")
            
            # Crear pedido
            pedido_id = str(uuid.uuid4())
            schema_name = self._get_schema_name(tenant['id'])
            
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT COALESCE(MAX(secuencial), 0) + 1 FROM "{schema_name}".pedidos')
                    secuencial = cur.fetchone()[0] or 1
            
            fecha_str = datetime.now().strftime('%Y%m%d%H%M%S')
            numero_pedido = f"{tenant['nombre'][:3].upper()}-{fecha_str}-{str(uuid.uuid4())[:4].upper()}"
            
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
                    if p.get('sabor'):
                        items_texto += f"     └─ Sabor: {p.get('sabor')}\n"
                    if p.get('tamanio'):
                        items_texto += f"     └─ Tamaño: {p.get('tamanio')}\n"
                    if p.get('decoraciones'):
                        items_texto += f"     └─ Decoraciones: {', '.join(p.get('decoraciones'))}\n"
                
                return f"""✅ *¡PEDIDO CONFIRMADO!*

📌 *Número de pedido:* {numero_pedido}

📋 *Productos:*
{items_texto}
💰 *Total:* ${total:,.0f}

📌 *El pago se realizará contra entrega. ¡Gracias por tu compra!*"""
                
            except Exception as e:
                logger.error(f'Error creando pedido: {e}')
                return "❌ Hubo un error procesando tu pedido. Por favor intenta de nuevo."
        else:
            return "¿Confirmas el pedido? Responde 'sí' para finalizar o dime qué más quieres agregar."
    
    def _respuesta_fallback(self, tenant: dict, menu: list) -> str:
        """Respuesta por si la IA no está disponible"""
        if menu:
            primeros = menu[:3]
            sugerencias = ", ".join([p['nombre'] for p in primeros])
            return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿Te gustaría ordenar {sugerencias}? Escríbeme lo que deseas."
        return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿En qué puedo ayudarte?"

    def _agregar_producto_personalizado_al_carrito(self, tenant_id: str, cliente_numero: str, 
                                                    nombre: str, precio: int, 
                                                    sabor: str = None, tamanio: str = None,
                                                    decoraciones: list = None,
                                                    cantidad: int = 1):
        """Agrega un producto personalizado al carrito con todos sus detalles"""
        logger.info(f"🛒 [PERSONALIZADO] ==== INICIO ====")
        logger.info(f"🛒 [PERSONALIZADO] Nombre: {nombre}")
        logger.info(f"🛒 [PERSONALIZADO] Precio: ${precio:,}")
        logger.info(f"🛒 [PERSONALIZADO] Sabor: {sabor}")
        logger.info(f"🛒 [PERSONALIZADO] Tamaño: {tamanio}")
        logger.info(f"🛒 [PERSONALIZADO] Decoraciones: {decoraciones}")
        logger.info(f"🛒 [PERSONALIZADO] Cliente: {cliente_numero}")
        
        try:
            carrito = self._cargar_carrito(tenant_id, cliente_numero)
            
            # Crear item con detalles de personalización
            nuevo_item = {
                'nombre': nombre,
                'nombre_base': nombre,
                'precio': precio,
                'cantidad': cantidad,
                'personalizado': True,
                'sabor': sabor,
                'tamanio': tamanio,
                'decoraciones': decoraciones or []
            }
            
            carrito['items'].append(nuevo_item)
            carrito['total'] += precio * cantidad
            
            self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
            logger.info(f"✅ [PERSONALIZADO] Producto agregado. Total items: {len(carrito['items'])}, Total: ${carrito['total']:,.0f}")
            
            return True
            
        except Exception as e:
            logger.error(f'❌ [PERSONALIZADO] Error: {e}')
            import traceback
            traceback.print_exc()
            return False


# Instancia global
message_handler = MessageHandler()