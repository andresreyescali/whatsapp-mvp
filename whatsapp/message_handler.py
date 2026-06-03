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
        self._pedido_confirmado = {}    # {numero: True/False}
        self._ultima_respuesta_ia = {}  # Para debugging
    
    def _get_schema_name(self, tenant_id: str) -> str:
        tenant = tenant_repo.find_by_id(tenant_id)
        if tenant and tenant.get('schema_name'):
            return tenant['schema_name']
        return f"tenant_{tenant_id.replace('-', '_')}"
    
    def process(self, phone_id: str, numero: str, texto: str):
        logger.info(f"🟢 [PROCESS] ==== INICIO ====")
        logger.info(f"🟢 [PROCESS] Cliente: {numero}")
        logger.info(f"🟢 [PROCESS] Mensaje: {texto}")
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'⚠️ Tenant no encontrado para phone_id: {phone_id}')
            return
        
        logger.info(f"🏪 [TENANT] Encontrado: {tenant.get('nombre')} (ID: {tenant['id']})")
        
        schema_manager.ensure_schema(tenant['id'])
        
        contexto = self._obtener_contexto_tenant(tenant['id'])
        menu = self._obtener_menu(tenant['id'])
        
        logger.info(f"📋 [MENU] Total productos en menú: {len(menu)}")
        
        # Si el pedido ya fue confirmado
        if self._pedido_confirmado.get(numero):
            logger.info(f"📌 [POST-PEDIDO] Cliente {numero} ya confirmó pedido")
            respuesta = "Tu pedido ya está confirmado y en proceso de preparación. ¿Necesitas ayuda con algo más?"
            whatsapp_client.send_message(tenant, numero, respuesta)
            return
        
        conv_activa = self._conversacion_activa.get(numero)
        
        if conv_activa and conv_activa.get('estado') == 'confirmando_pedido':
            logger.info(f"📌 [ESTADO] Confirmando pedido para {numero}")
            respuesta = self._procesar_confirmacion(texto, tenant, numero, conv_activa)
        else:
            respuesta = self._procesar_con_ia(tenant, menu, numero, texto, contexto)
        
        if respuesta:
            logger.info(f"📤 [RESPUESTA] Enviando a {numero}: {respuesta[:200]}...")
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)
        else:
            logger.warning(f"⚠️ [RESPUESTA] Vacía para {numero}")
        
        logger.info(f"🟢 [PROCESS] ==== FIN ====")
    
    def _obtener_menu(self, tenant_id: str) -> list:
        logger.info(f"📋 [MENU] Obteniendo menú para tenant {tenant_id}")
        try:
            schema_name = self._get_schema_name(tenant_id)
            logger.info(f"📋 [MENU] Schema: {schema_name}")
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
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
        logger.info(f"🛒 [CARGAR] ==== INICIO ====")
        logger.info(f"🛒 [CARGAR] Cliente: {cliente_numero}")
        logger.info(f"🛒 [CARGAR] Tenant: {tenant_id}")
        
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
                        logger.info(f"🛒 [CARGAR] Carrito ENCONTRADO: {len(items)} items, total ${total:,.0f}")
                        logger.info(f"🛒 [CARGAR] Items: {json.dumps(items, indent=2)}")
                        return {'items': items, 'total': total}
                    else:
                        logger.info(f"🛒 [CARGAR] Carrito NO encontrado, creando nuevo")
                        return {'items': [], 'total': 0}
        except Exception as e:
            logger.error(f'❌ [CARGAR] Error: {e}')
            import traceback
            traceback.print_exc()
            return {'items': [], 'total': 0}
    
    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        logger.info(f"💾 [GUARDAR] ==== INICIO ====")
        logger.info(f"💾 [GUARDAR] Cliente: {cliente_numero}")
        logger.info(f"💾 [GUARDAR] Items a guardar: {len(items)}")
        logger.info(f"💾 [GUARDAR] Total: ${total:,.0f}")
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
                        logger.info(f"💾 [GUARDAR] Creando NUEVO carrito")
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".carritos (cliente_numero, items, total, created_at, updated_at)
                            VALUES (%s, %s, %s, NOW(), NOW())
                        """, (cliente_numero, items_json, total))
                    
                    conn.commit()
                    logger.info(f"✅ [GUARDAR] Carrito guardado EXITOSAMENTE")
                    
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
    
    def _limpiar_carrito(self, tenant_id: str, cliente_numero: str):
        logger.info(f"🧹 [LIMPIAR] Limpiando carrito para {cliente_numero}")
        self._guardar_carrito(tenant_id, cliente_numero, [], 0)
        logger.info(f"✅ [LIMPIAR] Carrito limpiado")
    
    # ==================== FUNCIONES QUE LA IA LLAMA ====================
    
    def _agregar_producto_al_carrito(self, tenant_id: str, cliente_numero: str, nombre: str, precio: int, cantidad: int = 1):
        """Agrega un producto al carrito (llamado por IA)"""
        logger.info(f"🛒 [AGREGAR-STD] ==== INICIO ====")
        logger.info(f"🛒 [AGREGAR-STD] Producto: {nombre}")
        logger.info(f"🛒 [AGREGAR-STD] Precio: ${precio:,}")
        logger.info(f"🛒 [AGREGAR-STD] Cantidad: {cantidad}")
        logger.info(f"🛒 [AGREGAR-STD] Cliente: {cliente_numero}")
        
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        logger.info(f"🛒 [AGREGAR-STD] Carrito antes: {len(carrito['items'])} items, total ${carrito['total']:,.0f}")
        
        encontrado = False
        for item in carrito['items']:
            if item.get('nombre') == nombre and not item.get('personalizado'):
                item['cantidad'] += cantidad
                carrito['total'] += precio * cantidad
                encontrado = True
                logger.info(f"🛒 [AGREGAR-STD] Producto existente ACTUALIZADO")
                break
        
        if not encontrado:
            carrito['items'].append({
                'nombre': nombre,
                'precio': precio,
                'cantidad': cantidad,
                'personalizado': False
            })
            carrito['total'] += precio * cantidad
            logger.info(f"🛒 [AGREGAR-STD] Nuevo producto AGREGADO")
        
        logger.info(f"🛒 [AGREGAR-STD] Carrito después: {len(carrito['items'])} items, total ${carrito['total']:,.0f}")
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
        logger.info(f"✅ [AGREGAR-STD] ==== FIN OK ====")
        return True
    
    def _agregar_producto_personalizado_al_carrito(self, tenant_id: str, cliente_numero: str, 
                                                    nombre: str, precio: int, 
                                                    sabor: str = None, tamanio: str = None,
                                                    decoraciones: list = None,
                                                    cantidad: int = 1):
        """Agrega un producto personalizado al carrito (llamado por IA)"""
        logger.info(f"🛒 [AGREGAR-PERS] ==== INICIO ====")
        logger.info(f"🛒 [AGREGAR-PERS] Nombre: {nombre}")
        logger.info(f"🛒 [AGREGAR-PERS] Precio: ${precio:,}")
        logger.info(f"🛒 [AGREGAR-PERS] Cantidad: {cantidad}")
        logger.info(f"🛒 [AGREGAR-PERS] Sabor: {sabor}")
        logger.info(f"🛒 [AGREGAR-PERS] Tamaño: {tamanio}")
        logger.info(f"🛒 [AGREGAR-PERS] Decoraciones: {decoraciones}")
        logger.info(f"🛒 [AGREGAR-PERS] Cliente: {cliente_numero}")
        
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        logger.info(f"🛒 [AGREGAR-PERS] Carrito antes: {len(carrito['items'])} items, total ${carrito['total']:,.0f}")
        
        encontrado = False
        for item in carrito['items']:
            if (item.get('personalizado') and 
                item.get('nombre_base') == nombre and
                item.get('sabor') == sabor and 
                item.get('tamanio') == tamanio):
                item['precio'] = precio
                item['cantidad'] += cantidad
                carrito['total'] += precio * cantidad
                encontrado = True
                logger.info(f"🛒 [AGREGAR-PERS] Producto personalizado existente ACTUALIZADO")
                break
        
        if not encontrado:
            carrito['items'].append({
                'nombre': nombre,
                'nombre_base': nombre,
                'precio': precio,
                'cantidad': cantidad,
                'personalizado': True,
                'sabor': sabor,
                'tamanio': tamanio,
                'decoraciones': decoraciones or []
            })
            carrito['total'] += precio * cantidad
            logger.info(f"🛒 [AGREGAR-PERS] Nuevo producto personalizado AGREGADO")
        
        logger.info(f"🛒 [AGREGAR-PERS] Carrito después: {len(carrito['items'])} items, total ${carrito['total']:,.0f}")
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
        logger.info(f"✅ [AGREGAR-PERS] ==== FIN OK ====")
        return True
    
    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _procesar_con_ia(self, tenant: dict, menu: list, numero: str, texto: str, contexto: dict) -> str:
        logger.info(f"🤖 [IA] ==== INICIO PROCESAMIENTO ====")
        logger.info(f"🤖 [IA] Mensaje cliente: {texto}")
        logger.info(f"🤖 [IA] Menú disponible: {len(menu)} productos")
        
        if not ai_client.client:
            logger.warning("⚠️ [IA] Cliente no disponible")
            return self._respuesta_fallback(tenant, menu)
        
        # Verificar confirmación
        if self._es_confirmacion(texto):
            logger.info(f"✅ [CONFIRMACION] Detectada en mensaje: {texto}")
            carrito = self._cargar_carrito(tenant['id'], numero)
            logger.info(f"🛒 [CONFIRMACION] Carrito actual: {len(carrito.get('items', []))} items, total ${carrito.get('total', 0):,.0f}")
            
            if carrito and carrito.get('items'):
                self._conversacion_activa[numero] = {
                    'estado': 'confirmando_pedido',
                    'productos': carrito['items'],
                    'total': carrito['total']
                }
                return self._mostrar_resumen_pedido(carrito['items'], carrito['total'])
            else:
                logger.warning(f"⚠️ [CONFIRMACION] Carrito VACÍO")
                return "No hay productos en tu carrito. ¿Qué te gustaría ordenar?"
        
        # Verificar si quiere ver el carrito
        if any(p in texto.lower() for p in ['ver carrito', 'mi pedido', 'qué pedí']):
            logger.info(f"🔍 [VER-CARRITO] Cliente quiere ver su carrito")
            carrito = self._cargar_carrito(tenant['id'], numero)
            if carrito.get('items'):
                return self._mostrar_resumen_pedido(carrito['items'], carrito['total'])
            else:
                return "🛒 Tu carrito está vacío. ¿Qué te gustaría ordenar?"
        
        # Obtener historial y carrito
        historial = self._get_historial_conversacion(tenant['id'], numero, 15)
        carrito = self._cargar_carrito(tenant['id'], numero)
        
        logger.info(f"🛒 [IA] Carrito actual al inicio: {len(carrito.get('items', []))} items, total ${carrito.get('total', 0):,.0f}")
        
        # Construir el prompt con el menú y el carrito actual
        menu_texto = "\n".join([f"- {p['nombre']}: ${p['precio']:,}" for p in menu[:100]])
        
        historial_texto = ""
        if historial:
            historial_texto = "\n📜 HISTORIAL DE CONVERSACIÓN:\n"
            for h in historial[-10:]:
                historial_texto += f"Cliente: {h[0]}\nAsistente: {h[1]}\n"
        
        carrito_texto = ""
        if carrito.get('items'):
            carrito_texto = "\n🛒 CARRITO ACTUAL (lo que el cliente ya tiene):\n"
            for item in carrito['items']:
                carrito_texto += f"- {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}\n"
            carrito_texto += f"💰 Total actual: ${carrito.get('total', 0):,.0f}\n"
        else:
            carrito_texto = "\n🛒 CARRITO ACTUAL: Vacío\n"
        
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "agregar_producto_carrito",
                    "description": "Agrega un producto estándar al carrito. Úsalo cuando el cliente pida un producto sin personalización.",
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
                    "description": "Agrega un producto personalizado al carrito. Úsalo cuando el cliente elija sabor, tamaño o decoraciones.",
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
                    "description": "Muestra el contenido actual del carrito.",
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
Eres un asistente de ventas para {tenant.get('nombre', 'el negocio')}.

INFORMACIÓN:
- Horario: {contexto.get('horario', 'No especificado')}
- Ubicación: {contexto.get('ubicacion', 'No especificada')}
- Políticas: {contexto.get('politicas', 'No especificadas')}

{contexto.get('instrucciones', '')}

MENÚ DE PRODUCTOS:
{menu_texto}

{carrito_texto}

{historial_texto}

⚠️ REGLAS OBLIGATORIAS ⚠️:

1. Cuando el cliente pida o personalice un producto, DEBES llamar a la función 'agregar_producto_personalizado' o 'agregar_producto_carrito'.
2. NUNCA respondas con un resumen de precios sin antes haber llamado a la función correspondiente.
3. Cuando el cliente confirme (diga "si", "confirmo"), llama a 'confirmar_pedido'.
4. Cuando el cliente quiera ver su pedido, llama a 'ver_carrito'.

Responde en español, de forma natural y amable.
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
            logger.info(f"🤖 [IA] Respuesta recibida - Contenido: {message.content[:200] if message.content else 'None'}...")
            logger.info(f"🤖 [IA] Tool calls: {len(message.tool_calls) if message.tool_calls else 0}")
            
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    logger.info(f"🔧 [TOOL] ===== LLAMADA RECIBIDA =====")
                    logger.info(f"🔧 [TOOL] Función: {function_name}")
                    logger.info(f"🔧 [TOOL] Argumentos: {json.dumps(args, indent=2)}")
                    
                    if function_name == "agregar_producto_carrito":
                        self._agregar_producto_al_carrito(
                            tenant['id'], numero,
                            args.get("nombre_producto"),
                            args.get("precio"),
                            args.get("cantidad", 1)
                        )
                        carrito_act = self._cargar_carrito(tenant['id'], numero)
                        logger.info(f"🔧 [TOOL] Carrito después de agregar: {len(carrito_act.get('items', []))} items, total ${carrito_act.get('total', 0):,.0f}")
                        return f"""✅ *Agregado a tu pedido:*
• {args.get('cantidad', 1)}x {args.get('nombre_producto')}: ${args.get('precio') * args.get('cantidad', 1):,.0f}

💰 *Total actual:* ${carrito_act.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido?"""
                    
                    elif function_name == "agregar_producto_personalizado":
                        self._agregar_producto_personalizado_al_carrito(
                            tenant['id'], numero,
                            args.get("nombre_base"),
                            args.get("precio"),
                            args.get("sabor"),
                            args.get("tamanio"),
                            args.get("decoraciones", []),
                            args.get("cantidad", 1)
                        )
                        carrito_act = self._cargar_carrito(tenant['id'], numero)
                        logger.info(f"🔧 [TOOL] Carrito después de agregar personalizado: {len(carrito_act.get('items', []))} items, total ${carrito_act.get('total', 0):,.0f}")
                        return f"""✅ *Agregado a tu pedido (Personalizado):*
• {args.get('cantidad', 1)}x {args.get('nombre_base')}: ${args.get('precio') * args.get('cantidad', 1):,.0f}

💰 *Total actual:* ${carrito_act.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido?"""
                    
                    elif function_name == "ver_carrito":
                        logger.info(f"🔧 [TOOL] Mostrando carrito")
                        carrito_act = self._cargar_carrito(tenant['id'], numero)
                        if not carrito_act.get('items'):
                            return "🛒 Tu carrito está vacío. ¿Qué te gustaría ordenar?"
                        return self._mostrar_resumen_pedido(carrito_act['items'], carrito_act['total'])
                    
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
                            return "No hay productos en tu carrito para confirmar."
            
            logger.info(f"🤖 [IA] Respuesta sin tool calls: {message.content[:200] if message.content else 'None'}...")
            return message.content or self._respuesta_fallback(tenant, menu)
            
        except Exception as e:
            logger.error(f'❌ [IA] Error: {e}')
            import traceback
            traceback.print_exc()
            return self._respuesta_fallback(tenant, menu)
    
    def _es_confirmacion(self, texto: str) -> bool:
        confirmaciones = ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'confirmar', 
                          'proceder', 'adelante', 'esta bien', 'está bien']
        return texto.lower().strip() in confirmaciones
    
    def _mostrar_resumen_pedido(self, productos: list, total: int) -> str:
        if not productos:
            return "No hay productos en tu pedido."
        
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
        logger.info(f"📌 [CONFIRMACION-FINAL] Procesando: {texto}")
        
        if self._es_confirmacion(texto):
            productos = conv.get('productos', [])
            total = conv.get('total', 0)
            
            logger.info(f"✅ [FINAL] Confirmando pedido: {len(productos)} items, total ${total:,.0f}")
            logger.info(f"📦 [FINAL] Productos: {json.dumps(productos, indent=2)}")
            
            pedido_id = str(uuid.uuid4())
            schema_name = self._get_schema_name(tenant['id'])
            
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT COALESCE(MAX(secuencial), 0) + 1 FROM "{schema_name}".pedidos')
                    secuencial = cur.fetchone()[0] or 1
            
            numero_pedido = f"{tenant['nombre'][:3].upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:4].upper()}"
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
                
                logger.info(f"✅ [PEDIDO] Pedido creado EXITOSAMENTE: {pedido_id}")
                
                self._pedido_confirmado[numero] = True
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
                logger.error(f'❌ [PEDIDO] Error creando pedido: {e}')
                import traceback
                traceback.print_exc()
                return "❌ Hubo un error procesando tu pedido."
        else:
            return "¿Confirmas el pedido? Responde 'sí' para finalizar."
    
    def _respuesta_fallback(self, tenant: dict, menu: list) -> str:
        return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿Qué te gustaría ordenar?"


message_handler = MessageHandler()