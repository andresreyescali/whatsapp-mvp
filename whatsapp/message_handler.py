import json
import re
import uuid
import os
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
    
    def _get_schema_name(self, tenant_id: str) -> str:
        tenant = tenant_repo.find_by_id(tenant_id)
        if tenant and tenant.get('schema_name'):
            return tenant['schema_name']
        return f"tenant_{tenant_id.replace('-', '_')}"
    
    def process(self, phone_id: str, numero: str, texto: str):
        logger.info(f"🟢 [PROCESS] Cliente: {numero}, Mensaje: {texto[:100]}")
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'⚠️ Tenant no encontrado para phone_id: {phone_id}')
            return
        
        schema_manager.ensure_schema(tenant['id'])
        
        contexto = self._obtener_contexto_tenant(tenant['id'])
        menu = self._obtener_menu(tenant['id'])
        
        # Si el pedido ya fue confirmado
        if self._pedido_confirmado.get(numero):
            respuesta = "Tu pedido ya está confirmado y en proceso. ¿Necesitas ayuda con algo más?"
            whatsapp_client.send_message(tenant, numero, respuesta)
            return
        
        conv_activa = self._conversacion_activa.get(numero)
        
        if conv_activa and conv_activa.get('estado') == 'confirmando_pedido':
            respuesta = self._procesar_confirmacion(texto, tenant, numero, conv_activa)
        else:
            respuesta = self._procesar_con_ia(tenant, menu, numero, texto, contexto)
        
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)
    
    def _obtener_menu(self, tenant_id: str) -> list:
        try:
            schema_name = self._get_schema_name(tenant_id)
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
                    return [{
                        'id': str(row[0]),
                        'nombre': row[1],
                        'descripcion': row[2] or '',
                        'precio': row[3],
                        'categoria': row[4] or 'general',
                        'disponible': row[5],
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
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
    
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 15) -> list:
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
            return []
    
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
                        return {'items': items, 'total': row[1] or 0}
                    return {'items': [], 'total': 0}
        except Exception as e:
            return {'items': [], 'total': 0}
    
    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id FROM "{schema_name}".carritos WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    existing = cur.fetchone()
                    items_json = json.dumps(items)
                    if existing:
                        cur.execute(f"""
                            UPDATE "{schema_name}".carritos 
                            SET items = %s, total = %s, updated_at = NOW()
                            WHERE cliente_numero = %s
                        """, (items_json, total, cliente_numero))
                    else:
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".carritos (cliente_numero, items, total, created_at, updated_at)
                            VALUES (%s, %s, %s, NOW(), NOW())
                        """, (cliente_numero, items_json, total))
                    conn.commit()
        except Exception as e:
            logger.error(f'Error guardando carrito: {e}')
    
    def _limpiar_carrito(self, tenant_id: str, cliente_numero: str):
        self._guardar_carrito(tenant_id, cliente_numero, [], 0)
    
    # ==================== FUNCIONES QUE LA IA LLAMA ====================
    
    def _agregar_producto_al_carrito(self, tenant_id: str, cliente_numero: str, nombre: str, precio: int, cantidad: int = 1):
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        
        encontrado = False
        for item in carrito['items']:
            if item.get('nombre') == nombre and not item.get('personalizado'):
                item['cantidad'] += cantidad
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
        return True
    
    def _agregar_producto_personalizado_al_carrito(self, tenant_id: str, cliente_numero: str, 
                                                    nombre: str, precio: int, 
                                                    detalles: dict = None, cantidad: int = 1):
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        
        carrito['items'].append({
            'nombre': nombre,
            'precio': precio,
            'cantidad': cantidad,
            'personalizado': True,
            'detalles': detalles or {}
        })
        carrito['total'] += precio * cantidad
        
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
        return True
    
    def _enviar_imagen(self, tenant: dict, numero: str, url_imagen: str, caption: str = None):
        """Envía una imagen por WhatsApp"""
        try:
            # Si la URL es relativa, construir URL completa
            if not url_imagen.startswith('http'):
                base_url = os.environ.get('BASE_URL', 'https://whatsapp-mvp-docker.onrender.com')
                url_completa = f"{base_url}{url_imagen}"
            else:
                url_completa = url_imagen
            
            logger.info(f"Enviando imagen a {numero}: {url_completa}")
            return whatsapp_client.send_image(tenant, numero, url_completa, caption)
        except Exception as e:
            logger.error(f'Error en _enviar_imagen: {e}')
            return False
    
    def _enviar_recurso_visual(self, tenant: dict, numero: str, recurso_nombre: str) -> str:
        """Envía un recurso visual (genérico) basado en el nombre"""
        try:
            # Obtener todos los recursos del tenant
            recursos = schema_manager.get_recursos_visuales(tenant['id'])
            
            if not recursos:
                logger.warning(f"No hay recursos visuales para tenant {tenant['id']}")
                return None
            
            # Buscar el recurso por nombre (coincidencia parcial o exacta)
            recurso_encontrado = None
            recurso_nombre_lower = recurso_nombre.lower()
            
            for r in recursos:
                nombre_recurso = r.get('nombre', '').lower()
                # Buscar coincidencia exacta o que el nombre esté contenido
                if (recurso_nombre_lower == nombre_recurso or 
                    recurso_nombre_lower in nombre_recurso or 
                    nombre_recurso in recurso_nombre_lower):
                    recurso_encontrado = r
                    break
            
            if not recurso_encontrado:
                logger.warning(f"Recurso no encontrado: {recurso_nombre}")
                return None
            
            logger.info(f"Enviando recurso: {recurso_encontrado['nombre']} (tipo: {recurso_encontrado.get('tipo')})")
            
            # Enviar según el tipo
            if recurso_encontrado.get('tipo') == 'imagen' and recurso_encontrado.get('url'):
                caption = f"📷 *{recurso_encontrado['nombre']}*"
                if recurso_encontrado.get('descripcion'):
                    caption += f"\n\n{recurso_encontrado['descripcion']}"
                
                self._enviar_imagen(tenant, numero, recurso_encontrado['url'], caption)
                return f"✅ Te envié {recurso_encontrado['nombre']}"
            
            elif recurso_encontrado.get('tipo') == 'multiple' and recurso_encontrado.get('archivos'):
                for archivo in recurso_encontrado['archivos']:
                    self._enviar_imagen(tenant, numero, archivo, recurso_encontrado.get('descripcion'))
                return f"✅ Te envié {recurso_encontrado['nombre']}"
            
            else:
                logger.warning(f"Tipo de recurso no soportado: {recurso_encontrado.get('tipo')}")
                return None
                
        except Exception as e:
            logger.error(f'Error enviando recurso visual: {e}')
            return None
            
    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _procesar_con_ia(self, tenant: dict, menu: list, numero: str, texto: str, contexto: dict) -> str:
        logger.info(f"🤖 [IA] Procesando: {texto[:100]}...")
        
        if not ai_client.client:
            return self._respuesta_fallback(tenant, menu)
        
        # Verificar confirmación
        if self._es_confirmacion(texto):
            carrito = self._cargar_carrito(tenant['id'], numero)
            if carrito and carrito.get('items'):
                self._conversacion_activa[numero] = {
                    'estado': 'confirmando_pedido',
                    'productos': carrito['items'],
                    'total': carrito['total']
                }
                return self._mostrar_resumen_pedido(carrito['items'], carrito['total'])
            else:
                return "No hay productos en tu carrito. ¿Qué te gustaría ordenar?"
        
        # Verificar si quiere ver el carrito
        if any(p in texto.lower() for p in ['ver carrito', 'mi pedido', 'qué pedí']):
            carrito = self._cargar_carrito(tenant['id'], numero)
            if carrito.get('items'):
                return self._mostrar_resumen_pedido(carrito['items'], carrito['total'])
            else:
                return "🛒 Tu carrito está vacío. ¿Qué te gustaría ordenar?"
        
        # Obtener historial y carrito
        historial = self._get_historial_conversacion(tenant['id'], numero, 15)
        carrito = self._cargar_carrito(tenant['id'], numero)
        
        # Obtener recursos visuales disponibles
        recursos = schema_manager.get_recursos_visuales(tenant['id'])
        recursos_texto = "\n📁 RECURSOS VISUALES DISPONIBLES:\n"
        for r in recursos:
            recursos_texto += f"- {r['nombre']}: {r.get('descripcion', 'Sin descripción')}\n"
        
        # Construir prompt
        menu_texto = "\n".join([f"- {p['nombre']}: ${p['precio']:,}" for p in menu[:100]])
        
        historial_texto = ""
        if historial:
            historial_texto = "\n📜 HISTORIAL:\n"
            for h in historial[-10:]:
                historial_texto += f"Cliente: {h[0]}\nAsistente: {h[1]}\n"
        
        carrito_texto = ""
        if carrito.get('items'):
            carrito_texto = "\n🛒 CARRITO ACTUAL:\n"
            for item in carrito['items']:
                carrito_texto += f"- {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}\n"
            carrito_texto += f"💰 Total: ${carrito.get('total', 0):,.0f}\n"
        
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "agregar_producto_carrito",
                    "description": "Agrega un producto estándar al carrito.",
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
                    "description": "Agrega un producto personalizado al carrito.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nombre_base": {"type": "string"},
                            "precio": {"type": "integer"},
                            "detalles": {"type": "object"},
                            "cantidad": {"type": "integer", "default": 1}
                        },
                        "required": ["nombre_base", "precio"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "enviar_recurso_visual",
                    "description": "Envía un recurso visual (catálogo, menú, ejemplos) al cliente.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recurso_nombre": {
                                "type": "string",
                                "description": "Nombre del recurso a enviar"
                            }
                        },
                        "required": ["recurso_nombre"]
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
                    "description": "Confirma el pedido.",
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

{recursos_texto}

{carrito_texto}

{historial_texto}

REGLAS:
1. Cuando el cliente pida un producto, usa 'agregar_producto_carrito' o 'agregar_producto_personalizado'
2. Cuando el cliente quiera ver catálogo/menú/ejemplos, usa 'enviar_recurso_visual'
3. Cuando el cliente confirme, usa 'confirmar_pedido'
4. Cuando el cliente quiera ver su pedido, usa 'ver_carrito'
5. Responde en español, de forma natural y amable

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
            
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    logger.info(f"🔧 [TOOL] {function_name}: {args}")
                    
                    if function_name == "agregar_producto_carrito":
                        self._agregar_producto_al_carrito(
                            tenant['id'], numero,
                            args.get("nombre_producto"),
                            args.get("precio"),
                            args.get("cantidad", 1)
                        )
                        carrito_act = self._cargar_carrito(tenant['id'], numero)
                        return f"""✅ *Agregado a tu pedido:*
• {args.get('cantidad', 1)}x {args.get('nombre_producto')}: ${args.get('precio') * args.get('cantidad', 1):,.0f}

💰 *Total actual:* ${carrito_act.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido?"""
                    
                    elif function_name == "agregar_producto_personalizado":
                        self._agregar_producto_personalizado_al_carrito(
                            tenant['id'], numero,
                            args.get("nombre_base"),
                            args.get("precio"),
                            args.get("detalles", {}),
                            args.get("cantidad", 1)
                        )
                        carrito_act = self._cargar_carrito(tenant['id'], numero)
                        return f"""✅ *Agregado a tu pedido:*
• {args.get('cantidad', 1)}x {args.get('nombre_base')}: ${args.get('precio') * args.get('cantidad', 1):,.0f}

💰 *Total actual:* ${carrito_act.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido?"""
                    
                    elif function_name == "enviar_recurso_visual":
                        recurso_nombre = args.get("recurso_nombre")
                        resultado = self._enviar_recurso_visual(tenant, numero, recurso_nombre)
                        if resultado:
                            return resultado
                        else:
                            return f"Lo siento, no tengo '{recurso_nombre}' disponible para enviar. ¿Te gustaría que te describa nuestras opciones?"
                    
                    elif function_name == "ver_carrito":
                        carrito_act = self._cargar_carrito(tenant['id'], numero)
                        if not carrito_act.get('items'):
                            return "🛒 Tu carrito está vacío. ¿Qué te gustaría ordenar?"
                        return self._mostrar_resumen_pedido(carrito_act['items'], carrito_act['total'])
                    
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
                            return "No hay productos en tu carrito para confirmar."
            
            return message.content or self._respuesta_fallback(tenant, menu)
            
        except Exception as e:
            logger.error(f'Error en IA: {e}')
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
        
        return f"""📋 *Resumen de tu pedido:*

{items_texto}
💰 *Total:* ${total:,.0f}

¿Confirmas este pedido? (responde "sí" o "confirmo")"""
    
    def _procesar_confirmacion(self, texto: str, tenant: dict, numero: str, conv: dict) -> str:
        if self._es_confirmacion(texto):
            productos = conv.get('productos', [])
            total = conv.get('total', 0)
            
            pedido_id = str(uuid.uuid4())
            schema_name = self._get_schema_name(tenant['id'])
            
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT COALESCE(MAX(secuencial), 0) + 1 FROM "{schema_name}".pedidos')
                    secuencial = cur.fetchone()[0] or 1
            
            numero_pedido = f"{tenant['nombre'][:3].upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:4].upper()}"
            
            try:
                with db_manager.get_connection(tenant['id']) as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".pedidos 
                            (id, cliente_numero, numero_pedido, secuencial, items, total, estado, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        """, (pedido_id, numero, numero_pedido, secuencial, json.dumps(productos), total, 'nuevo'))
                    conn.commit()
                
                self._pedido_confirmado[numero] = True
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

📌 *Gracias por tu compra. Te notificaremos cuando tu pedido esté listo.*"""
                
            except Exception as e:
                logger.error(f'Error creando pedido: {e}')
                return "❌ Hubo un error procesando tu pedido."
        else:
            return "¿Confirmas el pedido? Responde 'sí' para finalizar."
    
    def _respuesta_fallback(self, tenant: dict, menu: list) -> str:
        return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿En qué puedo ayudarte?"


message_handler = MessageHandler()