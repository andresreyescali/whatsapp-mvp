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
        
        # Verificar si hay conversación activa
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
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
    
    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _procesar_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, contexto: dict) -> str:
        """Procesa el mensaje usando IA para entender lenguaje natural y extraer productos"""
        
        logger.info(f"🤖 [IA] Procesando: {texto[:100]}...")
        
        if not ai_client.client:
            return self._respuesta_fallback(tenant, menu)
        
        # Construir prompt con el menú y contexto
        menu_texto = self._formatear_menu_para_prompt(menu)
        
        system_prompt = f"""
Eres un asistente de ventas conversacional para {tenant.get('nombre', 'el negocio')}.

🏪 INFORMACIÓN DEL NEGOCIO:
- Horario: {contexto.get('horario', 'No especificado')}
- Ubicación: {contexto.get('ubicacion', 'No especificada')}
- Políticas: {contexto.get('politicas', 'No especificadas')}

{contexto.get('prompt_personalizado', '')}
{contexto.get('instrucciones', '')}

📋 PRODUCTOS DISPONIBLES (con precios base):
{menu_texto}

REGLAS IMPORTANTES:
1. ESCUCHA al cliente en lenguaje NATURAL. NO uses menús numéricos.
2. Cuando el cliente pida un producto, busca el nombre en la lista de productos.
3. PREGUNTA por las características que falten (tamaño, sabor, etc.)
4. Si el cliente pide algo con características específicas, CALCULA el precio final sumando precios base.
5. Al final, presenta un RESUMEN del pedido con el TOTAL calculado.
6. PREGUNTA "¿Confirmas este pedido?" para finalizar.
7. Responde de forma CÁLIDA, NATURAL y CONVERSACIONAL en español.
8. NO uses listas numeradas para opciones, usa descripciones naturales.

Ejemplo de respuesta correcta:
"Perfecto, te ayudo con una Torta Negra de libra. ¿Quieres agregar algún mensaje especial? El costo total sería $XX.XXX"

Sé breve, cálido y útil.
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
            
            # Verificar si el cliente quiere confirmar
            if self._es_confirmacion(texto):
                # Extraer productos del historial de la conversación
                productos = self._extraer_productos_de_respuesta(respuesta, menu)
                if productos:
                    self._conversacion_activa[numero] = {
                        'estado': 'confirmando_pedido',
                        'productos': productos,
                        'total': self._calcular_total(productos)
                    }
                    return self._mostrar_resumen_pedido(productos, self._calcular_total(productos))
            
            return respuesta
            
        except Exception as e:
            logger.error(f'Error en IA: {e}')
            return self._respuesta_fallback(tenant, menu)
    
    def _formatear_menu_para_prompt(self, menu: list) -> str:
        """Formatea el menú para el prompt de la IA"""
        if not menu:
            return "No hay productos disponibles"
        
        # Agrupar por categoría
        categorias = {}
        for p in menu:
            cat = p.get('categoria', 'general')
            if cat not in categorias:
                categorias[cat] = []
            categorias[cat].append(p)
        
        texto = ""
        for cat, productos in categorias.items():
            texto += f"\n*{cat.upper()}:*\n"
            for p in productos[:15]:
                texto += f"- {p['nombre']}: ${p['precio']:,}\n"
                if p.get('descripcion'):
                    texto += f"  {p['descripcion'][:80]}...\n"
        
        return texto
    
    def _es_confirmacion(self, texto: str) -> bool:
        """Detecta si el cliente quiere confirmar el pedido"""
        confirmaciones = ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'confirmar', 
                          'proceder', 'adelante', 'esta bien', 'está bien', 'confirmo pedido']
        texto_lower = texto.lower().strip()
        return texto_lower in confirmaciones or any(c in texto_lower for c in confirmaciones if len(c) > 2)
    
    def _extraer_productos_de_respuesta(self, respuesta: str, menu: list) -> list:
        """Extrae productos de la respuesta de la IA (simplificado)"""
        # Por ahora, retornar lista vacía - se puede mejorar
        return []
    
    def _calcular_total(self, productos: list) -> int:
        """Calcula el total de los productos"""
        total = 0
        for p in productos:
            total += p.get('precio', 0) * p.get('cantidad', 1)
        return total
    
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
        """Procesa la confirmación del pedido"""
        if self._es_confirmacion(texto):
            # Finalizar pedido
            productos = conv.get('productos', [])
            total = conv.get('total', 0)
            
            # Limpiar conversación activa
            self._conversacion_activa.pop(numero, None)
            
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
            # No confirmó, volver a preguntar
            return "¿Confirmas el pedido? Responde 'sí' para finalizar o dime qué más quieres agregar."
    
    def _respuesta_fallback(self, tenant: dict, menu: list) -> str:
        """Respuesta por si la IA no está disponible"""
        if menu:
            return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿Qué te gustaría ordenar? Por ejemplo, 'quiero una torta negra de libra'."
        return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿En qué puedo ayudarte?"


# Instancia global
message_handler = MessageHandler()