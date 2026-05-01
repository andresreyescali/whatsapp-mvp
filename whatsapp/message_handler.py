import json
import re
from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from orders.repository import order_repo
from orders.payment import generar_link_pago
from whatsapp.client import whatsapp_client
from ai.client import ai_client
from core.logger import logger
from core.database import db_manager

class MessageHandler:
    """Procesa mensajes de WhatsApp usando IA con contexto personalizado y memoria"""
    
    # Carrito temporal por cliente (en memoria, podrías usar Redis en producción)
    _carritos = {}
    
    def process(self, phone_id: str, numero: str, texto: str):
        """Procesa mensaje entrante y envía respuesta"""
        logger.info(f'Procesando mensaje de {numero}: {texto}')
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'Tenant no encontrado para phone_id: {phone_id}')
            return
        
        menu = schema_manager.get_menu(tenant['id'])
        pedidos_pendientes = order_repo.get_pendientes(tenant['id'], numero)
        contexto = self._obtener_contexto_tenant(tenant['id'])
        
        respuesta = self._responder_con_ia(texto, tenant, menu, numero, pedidos_pendientes, contexto)
        
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)
    
    def _responder_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, 
                          pedidos_pendientes: list, contexto: dict) -> str:
        """Usa DeepSeek con contexto personalizado y manejo de carrito"""
        
        if not ai_client.client:
            return self._respuesta_fallback(texto, tenant, menu, numero)
        
        # Verificar si hay un pedido pendiente sin pagar
        pedido_pendiente = self._get_pedido_pendiente_confirmado(tenant['id'], numero)
        
        # Procesar el mensaje según la intención
        texto_lower = texto.lower()
        
        # 1. Confirmación de pedido
        if any(palabra in texto_lower for palabra in ['si eso es todo', 'confirmo', 'haz el pedido', 'procesar pedido', 'está bien']):
            if self._carritos.get(numero, {}).get('items'):
                return self._finalizar_pedido(tenant, numero, menu)
            elif pedido_pendiente:
                return self._finalizar_pedido_existente(tenant, pedido_pendiente)
        
        # 2. Cancelar pedido
        if any(palabra in texto_lower for palabra in ['cancelar pedido', 'no quiero nada']):
            return self._cancelar_pedido(tenant, numero)
        
        # 3. Ver carrito actual
        if any(palabra in texto_lower for palabra in ['ver carrito', 'qué tengo', 'mi pedido']):
            return self._mostrar_carrito(tenant, numero)
        
        # 4. Detectar productos para agregar al carrito
        productos_detectados = self._detectar_productos_en_texto(texto, menu)
        
        if productos_detectados:
            self._agregar_al_carrito(numero, productos_detectados)
            carrito = self._carritos.get(numero, {})
            return self._mostrar_carrito_confirmacion(tenant, numero, carrito)
        
        # 5. Si no hay productos detectados, usar IA para respuesta general
        historial = self._get_historial_conversacion(tenant['id'], numero, 5)
        historial_texto = self._formatear_historial_para_prompt(historial)
        
        if contexto.get('prompt_personalizado'):
            system_prompt = contexto['prompt_personalizado'] + historial_texto
        else:
            system_prompt = self._construir_prompt_sistema(tenant, menu, pedidos_pendientes, contexto) + historial_texto
        
        # Agregar información del carrito al prompt
        carrito_info = self._get_carrito_info(numero)
        if carrito_info:
            system_prompt += f"\n\nCARRITO ACTUAL DEL CLIENTE:\n{carrito_info}\nPregunta si quiere agregar más productos o confirmar el pedido."
        
        user_message = f"""Cliente dice: "{texto}"\n\nGenera una respuesta amable y útil."""
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=500
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f'Error llamando a DeepSeek: {e}')
            return self._respuesta_fallback(texto, tenant, menu, numero)
    
    def _detectar_productos_en_texto(self, texto: str, menu: list) -> list:
        """Detecta productos y cantidades en el texto"""
        productos_encontrados = []
        texto_lower = texto.lower()
        
        for producto in menu:
            nombre = producto['nombre'].lower()
            if nombre in texto_lower:
                # Detectar cantidad
                cantidad = 1
                patron = rf'(\d+)\s*(unidades?)?\s*{re.escape(nombre)}'
                match = re.search(patron, texto_lower)
                if match:
                    try:
                        cantidad = int(match.group(1))
                    except:
                        cantidad = 1
                
                productos_encontrados.append({
                    'nombre': producto['nombre'],
                    'precio': producto['precio'],
                    'cantidad': cantidad
                })
        
        return productos_encontrados
    
    def _agregar_al_carrito(self, numero: str, productos: list):
        """Agrega productos al carrito del cliente"""
        if numero not in self._carritos:
            self._carritos[numero] = {'items': [], 'total': 0}
        
        for p in productos:
            # Buscar si el producto ya está en el carrito
            encontrado = False
            for item in self._carritos[numero]['items']:
                if item['nombre'] == p['nombre']:
                    item['cantidad'] += p['cantidad']
                    encontrado = True
                    break
            if not encontrado:
                self._carritos[numero]['items'].append(p)
            
            self._carritos[numero]['total'] += p['precio'] * p['cantidad']
    
    def _mostrar_carrito_confirmacion(self, tenant: dict, numero: str, carrito: dict) -> str:
        """Muestra el carrito y pide confirmación"""
        if not carrito.get('items'):
            return "🛒 No tienes productos en tu pedido aún."
        
        items_texto = ""
        for item in carrito['items']:
            subtotal = item['precio'] * item['cantidad']
            items_texto += f"• {item['cantidad']}x {item['nombre']} - ${subtotal:,.0f}\n"
        
        return f"""🛒 **Tu pedido actual:**

{items_texto}
**Total:** ${carrito['total']:,.0f}

✅ Responde **"sí, eso es todo"** para confirmar y generar el link de pago.
✏️ Puedes seguir agregando productos.
❌ Responde **"cancelar pedido"** si quieres empezar de nuevo."""
    
    def _mostrar_carrito(self, tenant: dict, numero: str) -> str:
        """Muestra el carrito actual"""
        carrito = self._carritos.get(numero, {})
        if not carrito.get('items'):
            return "🛒 No tienes productos en tu pedido aún. ¿Qué te gustaría ordenar?"
        
        items_texto = ""
        for item in carrito['items']:
            subtotal = item['precio'] * item['cantidad']
            items_texto += f"• {item['cantidad']}x {item['nombre']} - ${subtotal:,.0f}\n"
        
        return f"""🛒 **Tu pedido actual:**

{items_texto}
**Total:** ${carrito['total']:,.0f}

✅ Responde **"sí, eso es todo"** para confirmar y pagar.
✏️ Puedes seguir agregando productos."""
    
    def _finalizar_pedido(self, tenant: dict, numero: str, menu: list) -> str:
        """Finaliza el pedido y genera link de pago"""
        carrito = self._carritos.pop(numero, None)
        if not carrito or not carrito.get('items'):
            return "No hay productos en tu pedido. ¿Qué te gustaría ordenar?"
        
        # Crear pedido con múltiples items
        pedido_id = str(uuid.uuid4())
        items = carrito['items']
        total = carrito['total']
        
        try:
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO {tenant['id']}.pedidos (id, cliente_numero, items, total, estado)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (pedido_id, numero, json.dumps(items), total, "pendiente_pago"))
                conn.commit()
            
            link_pago = generar_link_pago(total, pedido_id)
            
            items_texto = ""
            for item in items:
                subtotal = item['precio'] * item['cantidad']
                items_texto += f"• {item['cantidad']}x {item['nombre']} - ${subtotal:,.0f}\n"
            
            return f"""✅ **¡Pedido confirmado!**

{items_texto}
**Total:** ${total:,.0f}

🔗 **Link de pago:** {link_pago}

✍️ Escribe **"ya pagué"** cuando completes el pago."""
            
        except Exception as e:
            logger.error(f'Error creando pedido: {e}')
            return "❌ Hubo un error procesando tu pedido. Por favor intenta de nuevo."
    
    def _finalizar_pedido_existente(self, tenant: dict, pedido: dict) -> str:
        """Finaliza un pedido ya existente en la BD"""
        link_pago = generar_link_pago(pedido['total'], pedido['id'])
        
        items = pedido.get('items', [])
        items_texto = ""
        for item in items:
            subtotal = item['precio'] * item.get('cantidad', 1)
            items_texto += f"• {item.get('cantidad', 1)}x {item['nombre']} - ${subtotal:,.0f}\n"
        
        return f"""✅ **¡Pedido confirmado!**

{items_texto}
**Total:** ${pedido['total']:,.0f}

🔗 **Link de pago:** {link_pago}

✍️ Escribe **"ya pagué"** cuando completes el pago."""
    
    def _cancelar_pedido(self, tenant: dict, numero: str) -> str:
        """Cancela el pedido actual"""
        if numero in self._carritos:
            del self._carritos[numero]
        return "❌ Pedido cancelado. Puedes empezar de nuevo cuando quieras."
    
    def _get_carrito_info(self, numero: str) -> str:
        """Obtiene información del carrito para el prompt"""
        carrito = self._carritos.get(numero, {})
        if not carrito.get('items'):
            return ""
        
        items_texto = ""
        for item in carrito['items']:
            items_texto += f"- {item['cantidad']}x {item['nombre']}: ${item['precio'] * item['cantidad']:,.0f}\n"
        return f"Productos en carrito:\n{items_texto}Total: ${carrito.get('total', 0):,.0f}"
    
    def _get_pedido_pendiente_confirmado(self, tenant_id: str, cliente_numero: str):
        """Obtiene pedido pendiente (pendiente_pago) de la BD"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT * FROM {tenant_id}.pedidos
                        WHERE cliente_numero = %s AND estado = 'pendiente_pago'
                        ORDER BY created_at DESC LIMIT 1
                    """, (cliente_numero,))
                    row = cur.fetchone()
                    if row:
                        columns = [desc[0] for desc in cur.description]
                        pedido = dict(zip(columns, row))
                        if pedido.get('items') and isinstance(pedido['items'], str):
                            pedido['items'] = json.loads(pedido['items'])
                        return pedido
                    return None
        except Exception as e:
            logger.error(f'Error obteniendo pedido pendiente: {e}')
            return None
    
    def _guardar_conversacion(self, tenant_id: str, cliente_numero: str, mensaje: str, respuesta: str):
        """Guarda la conversación en la base de datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO public.conversaciones_ia (tenant_id, cliente_numero, mensaje, respuesta)
                        VALUES (%s, %s, %s, %s)
                    """, (tenant_id, cliente_numero, mensaje, respuesta))
                conn.commit()
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
    
    def _obtener_contexto_tenant(self, tenant_id: str) -> dict:
        # ... (mantener el mismo código que tenías)
        pass
    
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 5) -> list:
        # ... (mantener el mismo código que tenías)
        pass
    
    def _formatear_historial_para_prompt(self, historial: list) -> str:
        # ... (mantener el mismo código que tenías)
        pass
    
    def _construir_prompt_sistema(self, tenant: dict, menu: list, pedidos_pendientes: list, contexto: dict) -> str:
        # ... (mantener el mismo código que tenías)
        pass
    
    def _formatear_menu_para_ia(self, menu: list) -> str:
        # ... (mantener el mismo código que tenías)
        pass
    
    def _respuesta_fallback(self, texto: str, tenant: dict, menu: list, numero: str) -> str:
        # ... (mantener el mismo código que tenías)
        pass

message_handler = MessageHandler()