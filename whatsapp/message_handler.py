import json
import re
import uuid
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

    def _obtener_contexto_tenant(self, tenant_id: str) -> dict:
        """Obtiene el contexto personalizado del tenant desde la base de datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        SELECT menu_estructurado, instrucciones, horario, ubicacion, 
                               politicas, prompt_personalizado 
                        FROM public.tenant_context 
                        WHERE tenant_id = %s
                    ''', (tenant_id,))
                    row = cur.fetchone()
                    
                    if row:
                        menu_estructurado = row[0]
                        if isinstance(menu_estructurado, str):
                            try:
                                menu_estructurado = json.loads(menu_estructurado)
                            except:
                                menu_estructurado = []
                        elif menu_estructurado is None:
                            menu_estructurado = []
                        
                        return {
                            'menu_estructurado': menu_estructurado,
                            'instrucciones': row[1] or '',
                            'horario': row[2] or '',
                            'ubicacion': row[3] or '',
                            'politicas': row[4] or '',
                            'prompt_personalizado': row[5] or ''
                        }
                    return {}
        except Exception as e:
            logger.error(f'Error obteniendo contexto para {tenant_id}: {e}')
            return {}

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

    # ==================== MÉTODOS DEL CARRITO ====================

    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        """Guarda el carrito en la base de datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    # Eliminar carrito anterior
                    cur.execute("DELETE FROM public.carritos WHERE tenant_id = %s AND cliente_numero = %s", 
                            (tenant_id, cliente_numero))
                    # Insertar nuevo carrito - convertir items a JSON string
                    cur.execute("""
                        INSERT INTO public.carritos (tenant_id, cliente_numero, items, total)
                        VALUES (%s, %s, %s, %s)
                    """, (tenant_id, cliente_numero, json.dumps(items), total))
                conn.commit()
                logger.info(f"Carrito guardado para {cliente_numero}: {len(items)} items, total ${total}")
        except Exception as e:
            logger.error(f'Error guardando carrito: {e}')

    def _cargar_carrito(self, tenant_id: str, cliente_numero: str) -> dict:
        """Carga el carrito desde la base de datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT items, total FROM public.carritos 
                        WHERE tenant_id = %s AND cliente_numero = %s
                    """, (tenant_id, cliente_numero))
                    row = cur.fetchone()
                    if row:
                        # items puede ser string o dict, asegurarse de que sea lista
                        items = row[0]
                        if isinstance(items, str):
                            items = json.loads(items)
                        elif items is None:
                            items = []
                        return {'items': items, 'total': row[1]}
                    return {'items': [], 'total': 0}
        except Exception as e:
            logger.error(f'Error cargando carrito: {e}')
            return {'items': [], 'total': 0}
        
    def _agregar_al_carrito(self, tenant_id: str, cliente_numero: str, productos: list):
        """Agrega productos al carrito del cliente usando BD"""
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        
        for p in productos:
            encontrado = False
            for item in carrito['items']:
                if item['nombre'] == p['nombre']:
                    item['cantidad'] += p['cantidad']
                    encontrado = True
                    break
            if not encontrado:
                carrito['items'].append(p)
            carrito['total'] += p['precio'] * p['cantidad']
        
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
        
    
    # ==================== MÉTODOS DEL HISTORIAL ====================

    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 5) -> list:
        """Obtiene el historial de conversación con el cliente"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT mensaje, respuesta, created_at 
                        FROM public.conversaciones_ia 
                        WHERE tenant_id = %s AND cliente_numero = %s 
                        ORDER BY created_at DESC 
                        LIMIT %s
                    """, (tenant_id, cliente_numero, limit))
                    rows = cur.fetchall()
                    return list(reversed(rows))
        except Exception as e:
            logger.error(f'Error obteniendo historial: {e}')
            return []

    def _formatear_historial_para_prompt(self, historial: list) -> str:
        """Formatea el historial para incluirlo en el prompt de IA"""
        if not historial:
            return ""
        
        texto = "\n\nHISTORIAL DE LA CONVERSACIÓN:\n"
        for h in historial:
            texto += f"Cliente: {h[0]}\n"
            texto += f"Asistente: {h[1]}\n"
        return texto

    # ==================== DETECCIÓN DE PRODUCTOS ====================

    def _detectar_productos_en_texto(self, texto: str, menu: list) -> list:
        """Detecta productos y cantidades en el texto"""
        productos_encontrados = []
        texto_lower = texto.lower()
        
        for producto in menu:
            nombre = producto['nombre'].lower()
            if nombre in texto_lower:
                cantidad = 1
                patron = rf'(\d+)\s*{re.escape(nombre)}'
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
                logger.info(f"Producto detectado: {producto['nombre']} x{cantidad}")
        
        return productos_encontrados

    # ==================== RESPUESTAS DEL CARRITO ====================

    def _mostrar_carrito_confirmacion(self, tenant: dict, numero: str, carrito: dict) -> str:
        """Muestra el carrito y pregunta si quiere agregar más"""
        if not carrito.get('items'):
            return "No tienes productos en tu pedido aún. ¿Qué te gustaría ordenar?"
        
        items_texto = ""
        for item in carrito['items']:
            subtotal = item['precio'] * item['cantidad']
            items_texto += f"• {item['cantidad']}x {item['nombre']}: ${subtotal:,.0f}\n"
        
        total = carrito['total']
        
        return f"""📋 **Tu pedido:**

{items_texto}
**Total:** ${total:,.0f}

¿Algo más que deseas agregar o procedemos con el pedido?"""

    def _mostrar_carrito(self, tenant: dict, numero: str, carrito: dict) -> str:
        """Muestra el carrito actual"""
        if not carrito.get('items'):
            return "No tienes productos en tu pedido aún. ¿Qué te gustaría ordenar?"
        
        items_texto = ""
        for item in carrito['items']:
            subtotal = item['precio'] * item['cantidad']
            items_texto += f"• {item['cantidad']}x {item['nombre']}: ${subtotal:,.0f}\n"
        
        total = carrito['total']
        
        return f"""📋 **Tu pedido actual:**

{items_texto}
**Total:** ${total:,.0f}"""

    def _finalizar_pedido(self, tenant: dict, numero: str, carrito: dict) -> str:
            """Finaliza el pedido y genera link de pago"""
            if not carrito or not carrito.get('items'):
                return "No hay productos en tu pedido. ¿Qué te gustaría ordenar?"
            
            pedido_id = str(uuid.uuid4())
            items = carrito['items']
            total = carrito['total']
            
            # Obtener secuencial
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    # Asegurar que las columnas existen
                    try:
                        cur.execute(f"ALTER TABLE {tenant['id']}.pedidos ADD COLUMN IF NOT EXISTS numero_pedido TEXT")
                        cur.execute(f"ALTER TABLE {tenant['id']}.pedidos ADD COLUMN IF NOT EXISTS secuencial INTEGER")
                    except:
                        pass
                    
                    cur.execute(f"SELECT COALESCE(MAX(secuencial), 0) + 1 FROM {tenant['id']}.pedidos")
                    secuencial = cur.fetchone()[0]
            
            numero_pedido = db_manager.generar_numero_pedido(tenant['id'], secuencial)
            
            try:
                with db_manager.get_connection(tenant['id']) as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"""
                            INSERT INTO {tenant['id']}.pedidos (id, cliente_numero, items, total, estado, numero_pedido, secuencial)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (pedido_id, numero, json.dumps(items), total, "nuevo", numero_pedido, secuencial))
                    conn.commit()
                
                # Limpiar carrito
                self._guardar_carrito(tenant['id'], numero, [], 0)
                
                link_pago = generar_link_pago(total, pedido_id)
                
                items_texto = ""
                for item in items:
                    subtotal = item['precio'] * item['cantidad']
                    items_texto += f"• {item['cantidad']}x {item['nombre']}: ${subtotal:,.0f}\n"
                
                # Enviar email de confirmación
                from orders.repository import order_repo
                order_repo._enviar_email_confirmacion(tenant['id'], numero_pedido, items, total, numero)
                
                return f"""✅ **¡Pedido listo!**

        {items_texto}
        **Total a pagar:** ${total:,.0f}

        🔗 **Link de pago:** {link_pago}

        Cuando completes el pago, avísame para empezar a preparar tu pedido."""
                    
            except Exception as e:
                logger.error(f'Error creando pedido: {e}')
                return "❌ Hubo un error procesando tu pedido. Por favor intenta de nuevo."
            
        # ==================== RESPUESTA PRINCIPAL CON IA ====================

    def _responder_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, 
                            pedidos_pendientes: list, contexto: dict) -> str:
            """Usa DeepSeek con contexto personalizado y manejo de carrito"""
            
            if not ai_client.client:
                return self._respuesta_fallback(texto, tenant, menu, numero)
            
            texto_lower = texto.lower()
            
            # Cargar carrito desde BD
            carrito_actual = self._cargar_carrito(tenant['id'], numero)
            
            # 1. Detectar pagos
            if any(palabra in texto_lower for palabra in ['pague', 'pago', 'pagado', 'transferí', 'consigné', 'pagué', 'ya pague', 'listo el pago']):
                order_repo.marcar_pagado(tenant['id'], numero)
                return "✅ ¡Pago confirmado! En breve comenzamos a preparar tu pedido."
            
            # 2. Detectar confirmación de pedido
            if any(palabra in texto_lower for palabra in ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'esta bien', 'está bien', 'adelante', 'procesar']):
                if carrito_actual.get('items'):
                    return self._finalizar_pedido(tenant, numero, carrito_actual)
            
            # 3. Detectar cancelación
            if any(palabra in texto_lower for palabra in ['cancela', 'cancelar', 'no quiero', 'mejor no']):
                self._guardar_carrito(tenant['id'], numero, [], 0)
                return "❌ Pedido cancelado. Estaré aquí cuando necesites algo."
            
            # 4. Ver carrito
            if any(palabra in texto_lower for palabra in ['que pedí', 'que tengo', 'mi pedido', 'ver carrito']):
                return self._mostrar_carrito(tenant, numero, carrito_actual)
            
            # 5. Detectar productos
            productos_detectados = self._detectar_productos_en_texto(texto, menu)
            
            if productos_detectados:
                self._agregar_al_carrito(tenant['id'], numero, productos_detectados)
                nuevo_carrito = self._cargar_carrito(tenant['id'], numero)
                return self._mostrar_carrito_confirmacion(tenant, numero, nuevo_carrito)
            
            # 6. Respuesta con IA
            historial = self._get_historial_conversacion(tenant['id'], numero, 5)
            historial_texto = self._formatear_historial_para_prompt(historial)
            
            if contexto.get('prompt_personalizado'):
                system_prompt = contexto['prompt_personalizado'] + historial_texto
            else:
                system_prompt = self._construir_prompt_sistema(tenant, menu, pedidos_pendientes, contexto) + historial_texto
            
            carrito_info = self._get_carrito_info(numero)
            if carrito_info:
                system_prompt += f"\n\nProductos ya agregados: {carrito_info}"
            
            system_prompt += "\n\nIMPORTANTE: NO incluyas instrucciones como 'escribe X para hacer Y'. Solo responde naturalmente."
            
            user_message = f"Cliente dice: \"{texto}\"\nGenera una respuesta amable y natural."
            
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

    def _get_carrito_info(self, numero: str) -> str:
            """Obtiene información del carrito para el prompt"""
            carrito = self._cargar_carrito(tenant_repo.get_all()[0]['id'] if tenant_repo.get_all() else None, numero) if tenant_repo.get_all() else {'items': [], 'total': 0}
            if not carrito.get('items'):
                return ""
            
            items_texto = ""
            for item in carrito['items']:
                items_texto += f"- {item['cantidad']}x {item['nombre']}: ${item['precio'] * item['cantidad']:,.0f}\n"
            return f"Productos en carrito:\n{items_texto}Total: ${carrito.get('total', 0):,.0f}"

    def _construir_prompt_sistema(self, tenant: dict, menu: list, pedidos_pendientes: list, contexto: dict) -> str:
            """Construye prompt del sistema"""
            nombre_negocio = tenant.get('nombre', 'Mi negocio')
            return f"""Eres un asistente de ventas por WhatsApp para {nombre_negocio}. Ayuda al cliente a armar su pedido de forma natural."""

    def _respuesta_fallback(self, texto: str, tenant: dict, menu: list, numero: str) -> str:
            """Respuesta de fallback"""
            return f"Hola! Soy el asistente de {tenant['nombre']}. ¿Qué te gustaría ordenar?"

    # Instancia global
message_handler = MessageHandler()