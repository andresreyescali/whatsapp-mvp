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
        logger.info(f'🟢 [PROCESS] Cliente: {numero}, Mensaje: {texto[:100]}')
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'⚠️ Tenant no encontrado para phone_id: {phone_id}')
            return
        
        schema_manager.ensure_schema(tenant['id'])
        
        # Obtener contexto de IA entrenado
        contexto = self._obtener_contexto_tenant(tenant['id'])
        menu = self._obtener_menu(tenant['id'])
        
        # Verificar si hay conversación activa de confirmación
        conv_activa = self._conversacion_activa.get(numero)
        
        if conv_activa and conv_activa.get('estado') == 'confirmando_pedido':
            respuesta = self._procesar_confirmacion(texto, tenant, numero, conv_activa)
        else:
            respuesta = self._procesar_con_ia(texto, tenant, menu, numero, contexto)
        
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)
    
    def _obtener_menu(self, tenant_id: str) -> list:
        """Obtiene el menú de productos (productos base con precios)"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible,
                               imagen_url, tiempo_preparacion, destacado, es_base, metadata
                        FROM "{schema_name}".productos 
                        WHERE disponible = true AND es_base = true
                        ORDER BY categoria, nombre
                    """)
                    rows = cur.fetchall()
                    productos = []
                    for row in rows:
                        metadata = row[10] if len(row) > 10 and row[10] else {}
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except:
                                metadata = {}
                        
                        productos.append({
                            'id': str(row[0]),
                            'nombre': row[1],
                            'descripcion': row[2] or '',
                            'precio': row[3],
                            'categoria': row[4] or 'general',
                            'disponible': row[5],
                            'imagen_url': row[6],
                            'tiempo_preparacion': row[7],
                            'destacado': row[8] if row[8] else False,
                            'es_base': row[9] if row[9] is not None else True,
                            'personalizaciones': metadata.get('personalizaciones', []),
                            'adicionales': metadata.get('adicionales', [])
                        })
                    return productos
        except Exception as e:
            logger.error(f'Error obteniendo menú: {e}')
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
    
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 15) -> list:
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
            logger.error(f'Error cargando carrito: {e}')
            return {'items': [], 'total': 0}
    
    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        """Guarda el carrito en la base de datos"""
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
                    else:
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".carritos (cliente_numero, items, total, created_at, updated_at)
                            VALUES (%s, %s, %s, NOW(), NOW())
                        """, (cliente_numero, json.dumps(items), total))
                    conn.commit()
                    logger.info(f"💾 [CARRITO] Guardado para {cliente_numero}: {len(items)} items, ${total:,.0f}")
        except Exception as e:
            logger.error(f'Error guardando carrito: {e}')
    
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
        texto += f"💰 Total actual en carrito: ${carrito.get('total', 0):,.0f}\n"
        return texto
    
    def _formatear_menu_para_prompt(self, menu: list) -> str:
        """Formatea el menú para el prompt de la IA"""
        if not menu:
            return "No hay productos disponibles"
        
        categorias = {}
        for p in menu:
            cat = p.get('categoria', 'general')
            if cat not in categorias:
                categorias[cat] = []
            categorias[cat].append(p)
        
        texto = ""
        for cat, productos in categorias.items():
            texto += f"\n📁 {cat.upper()}:\n"
            for p in productos[:30]:
                texto += f"  - {p['nombre']}: ${p['precio']:,}\n"
        
        return texto
    
    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _procesar_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, contexto: dict) -> str:
        """Procesa el mensaje usando IA para entender lenguaje natural"""
        
        logger.info(f"🤖 [IA] Procesando: {texto[:100]}...")
        
        if not ai_client.client:
            return self._respuesta_fallback(tenant, menu)
        
        # Obtener historial y carrito
        historial = self._get_historial_conversacion(tenant['id'], numero, 15)
        historial_texto = self._formatear_historial_para_prompt(historial)
        carrito_actual = self._cargar_carrito(tenant['id'], numero)
        carrito_texto = self._formatear_carrito_para_prompt(carrito_actual)
        menu_texto = self._formatear_menu_para_prompt(menu)
        
        system_prompt = f"""
Eres un asistente de ventas conversacional para {tenant.get('nombre', 'el negocio')}.

🏪 INFORMACIÓN:
- Horario: {contexto.get('horario', 'No especificado')}
- Ubicación: {contexto.get('ubicacion', 'No especificada')}
- Políticas: {contexto.get('politicas', 'No especificadas')}

{contexto.get('prompt_personalizado', '')}
{contexto.get('instrucciones', '')}

📋 PRODUCTOS:
{menu_texto}

{carrito_texto}

{historial_texto}

REGLAS IMPORTANTES:
1. Responde de forma NATURAL y CONVERSACIONAL. NO uses listas numeradas.
2. RECUERDA lo que el cliente ya ha dicho. NO repitas preguntas.
3. Usa el CARRITO ACTUAL para calcular el total si el cliente ya tiene productos.
4. Cuando el cliente confirme ("si", "confirmo"), DEBES usar el carrito actual.
5. Presenta el resumen con el TOTAL calculado del carrito.
6. Sé breve, cálido y útil.

RESPONDE en español.
"""
        
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
            
            respuesta = response.choices[0].message.content
            
            # DETECTAR CONFIRMACIÓN - CRÍTICO: usar el carrito actual
            if self._es_confirmacion(texto):
                logger.info(f"✅ [CONFIRMACION] Detectada para {numero}")
                
                # Recargar carrito para asegurar datos actualizados
                carrito_final = self._cargar_carrito(tenant['id'], numero)
                
                if carrito_final and carrito_final.get('items'):
                    logger.info(f"🛒 [CARRITO] Usando carrito con {len(carrito_final['items'])} items, total ${carrito_final['total']:,.0f}")
                    
                    # Guardar en conversación activa para confirmación
                    self._conversacion_activa[numero] = {
                        'estado': 'confirmando_pedido',
                        'productos': carrito_final['items'],
                        'total': carrito_final['total']
                    }
                    
                    # Mostrar resumen del carrito
                    return self._mostrar_resumen_pedido(carrito_final['items'], carrito_final['total'])
                else:
                    logger.warning(f"⚠️ [CONFIRMACION] Carrito vacío para {numero}")
                    return "No tengo productos en tu carrito. ¿Qué te gustaría ordenar?"
            
            return respuesta
            
        except Exception as e:
            logger.error(f'Error en IA: {e}')
            return self._respuesta_fallback(tenant, menu)
    
    def _es_confirmacion(self, texto: str) -> bool:
        """Detecta si el cliente quiere confirmar el pedido"""
        confirmaciones = ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'confirmar', 
                          'proceder', 'adelante', 'esta bien', 'está bien', 'confirmo pedido']
        texto_lower = texto.lower().strip()
        return texto_lower in confirmaciones or any(c in texto_lower for c in confirmaciones if len(c) > 2)
    
    def _mostrar_resumen_pedido(self, productos: list, total: int) -> str:
        """Muestra el resumen del pedido"""
        if not productos:
            return "No tengo productos en tu pedido. ¿Qué te gustaría ordenar?"
        
        items_texto = ""
        for p in productos:
            items_texto += f"• {p.get('cantidad', 1)}x {p.get('nombre')}: ${p.get('precio', 0) * p.get('cantidad', 1):,.0f}\n"
        
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
            
            # Limpiar conversación activa y carrito
            self._conversacion_activa.pop(numero, None)
            self._guardar_carrito(tenant['id'], numero, [], 0)
            
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
                logger.error(f'Error creando pedido: {e}')
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