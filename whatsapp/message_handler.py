import json
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
        
        # Obtener tenant
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'Tenant no encontrado para phone_id: {phone_id}')
            return
        
        logger.info(f'Tenant encontrado: {tenant["nombre"]} (ID: {tenant["id"]})')
        
        # Obtener menú y pedidos pendientes
        menu = schema_manager.get_menu(tenant['id'])
        pedidos_pendientes = order_repo.get_pendientes(tenant['id'], numero)
        
        # Obtener contexto personalizado del tenant
        contexto = self._obtener_contexto_tenant(tenant['id'])
        
        # Generar respuesta con IA (con contexto personalizado y memoria)
        respuesta = self._responder_con_ia(texto, tenant, menu, numero, pedidos_pendientes, contexto)
        
        # Enviar respuesta
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            
            # Guardar conversación en la base de datos (memoria)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)
    
    def _guardar_conversacion(self, tenant_id: str, cliente_numero: str, mensaje: str, respuesta: str):
        """Guarda la conversación en la base de datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO public.conversaciones_ia (tenant_id, cliente_numero, mensaje, respuesta, tipo)
                        VALUES (%s, %s, %s, %s, 'cliente')
                    """, (tenant_id, cliente_numero, mensaje, respuesta))
                conn.commit()
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
        
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 5) -> list:
        """Obtiene el historial de conversación con el cliente"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT mensaje, respuesta, created_at 
                        FROM public.conversaciones 
                        WHERE tenant_id = %s AND cliente_numero = %s 
                        ORDER BY created_at DESC 
                        LIMIT %s
                    """, (tenant_id, cliente_numero, limit))
                    rows = cur.fetchall()
                    # Retornar en orden cronológico
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
    
    def _responder_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, 
                          pedidos_pendientes: list, contexto: dict) -> str:
        """Usa DeepSeek con contexto personalizado y memoria conversacional"""
        
        if not ai_client.client:
            logger.warning("Cliente de IA no disponible, usando fallback")
            return self._respuesta_fallback(texto, tenant, menu, numero)
        
        # Obtener historial de conversación
        historial = self._get_historial_conversacion(tenant['id'], numero, 5)
        historial_texto = self._formatear_historial_para_prompt(historial)
        
        # Si hay prompt personalizado, usarlo
        if contexto.get('prompt_personalizado'):
            system_prompt = contexto['prompt_personalizado'] + historial_texto
        else:
            # Construir prompt del sistema con contexto disponible
            system_prompt = self._construir_prompt_sistema(tenant, menu, pedidos_pendientes, contexto) + historial_texto
        
        user_message = f"""Cliente dice: "{texto}"

Genera una respuesta amable y útil para este cliente. Mantén el contexto de la conversación anterior."""
        
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
            
            respuesta = response.choices[0].message.content
            
            # Post-procesamiento: detectar si la IA quiere crear un pedido
            respuesta, pedido_creado = self._detectar_y_crear_pedido(respuesta, texto, tenant, menu, numero)
            
            return respuesta
            
        except Exception as e:
            logger.error(f'Error llamando a DeepSeek: {e}')
            return self._respuesta_fallback(texto, tenant, menu, numero)
    
    def _construir_prompt_sistema(self, tenant: dict, menu: list, pedidos_pendientes: list, contexto: dict) -> str:
        """Construye el prompt del sistema con toda la información disponible"""
        nombre_negocio = tenant.get('nombre', 'Mi negocio')
      # negocio_info = f"""Eres un asistente de ventas por WhatsApp para {tenant['nombre']}, una {tenant.get('tipo_negocio', 'restaurante')}.
        negocio_info = f"""Eres un asistente de ventas por WhatsApp para {nombre_negocio}.

CONTEXTO DEL NEGOCIO:
- Nombre:{nombre_negocio}
- Tipo: {tenant.get('tipo_negocio', 'restaurante')}"""
        
        if contexto.get('horario'):
            negocio_info += f"\n- Horario: {contexto['horario']}"
        else:
            negocio_info += "\n- Horario: 12pm a 10pm (todos los días)"
        
        if contexto.get('ubicacion'):
            negocio_info += f"\n- Ubicación: {contexto['ubicacion']}"
        else:
            negocio_info += "\n- Ubicación: Cali, Colombia"
        
        if contexto.get('politicas'):
            negocio_info += f"\n\nPOLÍTICAS DEL NEGOCIO:\n{contexto['politicas']}"
        
        if contexto.get('instrucciones'):
            negocio_info += f"\n\nINSTRUCCIONES PERSONALIZADAS:\n{contexto['instrucciones']}"
        
        menu_contexto = self._formatear_menu_para_ia(menu)
        
        pedidos_contexto = ""
        if pedidos_pendientes:
            pedidos_contexto = "\nPEDIDOS PENDIENTES DEL CLIENTE:\n"
            for p in pedidos_pendientes:
                pedidos_contexto += f"- {p['items'][0]['nombre'] if p.get('items') else 'Producto'}: ${p['total']} (ID: {p['id']})\n"
        
        reglas = """

REGLAS IMPORTANTES:
1. PRESÉNTATE SIEMPRE con el nombre del negocio al iniciar la conversación.
   Ejemplo: "¡Hola! Soy el asistente de [NOMBRE_DEL_NEGOCIO]. ¿En qué puedo ayudarte?"

2. Eres un vendedor amable, conversacional y natural.
3. Mantén el contexto de la conversación. Si el cliente ya pidió algo antes, recuérdalo.
4. NO saludes cada vez. Solo saluda al inicio de la conversación.
5. Si el cliente confirma un pedido, procede a generar el link de pago.
6. Si el cliente pide el menú, preséntalo de forma atractiva.
7. Si el cliente pregunta por horario o ubicación, responde con la información proporcionada.
8. Para generar un link de pago, usa el formato: https://checkout.wompi.co/l/test_[ID_PEDIDO]_[TOTAL]
9. Si el cliente dice "ya pague" o similar, confirma el pago y despídete amablemente.
10. Responde SIEMPRE en español, de forma breve pero completa (2-4 oraciones).
11. Sé proactivo: si el cliente duda, recomienda los productos más populares.

INSTRUCCIÓN CRÍTICA: Tu respuesta debe ser SOLO el mensaje para el cliente, sin explicaciones adicionales."""

        return f"""{negocio_info}

MENÚ COMPLETO:
{menu_contexto}

{pedidos_contexto}
{reglas}"""
    
    def _formatear_menu_para_ia(self, menu: list) -> str:
        """Formatea el menú para incluirlo en el prompt de IA"""
        if not menu:
            return "No hay productos disponibles actualmente."
        
        categorias = {}
        for p in menu:
            cat = p.get('categoria')
            if cat is None or cat == '':
                cat = 'general'
            if cat not in categorias:
                categorias[cat] = []
            categorias[cat].append(p)
        
        resultado = ""
        for categoria, productos in categorias.items():
            resultado += f"\n{categoria.upper()}:\n"
            for p in productos:
                resultado += f"  - {p['nombre']}: ${p['precio']:,.0f}"
                if p.get('descripcion'):
                    resultado += f" - {p['descripcion'][:80]}"
                resultado += "\n"
        
        return resultado
    
    def _detectar_y_crear_pedido(self, respuesta_ia: str, texto_original: str, tenant: dict, menu: list, numero: str) -> tuple:
        """Detecta si la IA quiere crear un pedido y lo ejecuta"""
        
        lineas = respuesta_ia.lower().split('\n')
        
        for linea in lineas:
            if any(palabra in linea for palabra in ['pedido confirmado', 'producto agregado', 'link de pago', 'paga aquí']):
                for producto in menu:
                    if producto['nombre'].lower() in texto_original.lower():
                        pedido = order_repo.create(
                            tenant['id'],
                            numero,
                            producto['nombre'],
                            producto['precio']
                        )
                        link_pago = generar_link_pago(pedido['total'], pedido['id'])
                        
                        respuesta_nueva = f"""✅ ¡Pedido confirmado!

**Producto:** {producto['nombre']}
**Precio:** ${producto['precio']:,.0f}

🔗 **Link de pago:** {link_pago}

✍️ Escribe "ya pagué" cuando completes el pago."""
                        
                        return respuesta_nueva, True
        
        return respuesta_ia, False
    
    def _respuesta_fallback(self, texto: str, tenant: dict, menu: list, numero: str) -> str:
        """Respuesta de fallback si la IA no está disponible"""
        
        texto_lower = texto.lower()
        
        for producto in menu:
            if producto['nombre'].lower() in texto_lower:
                pedido = order_repo.create(tenant['id'], numero, producto['nombre'], producto['precio'])
                link_pago = generar_link_pago(pedido['total'], pedido['id'])
                return f"✅ Pedido: {producto['nombre']} - ${producto['precio']:,.0f}\n🔗 Paga aquí: {link_pago}"
        
        if 'menu' in texto_lower:
            respuesta = "📋 *MENÚ*\n\n"
            for p in menu:
                respuesta += f"• {p['nombre']}: ${p['precio']:,.0f}\n"
            return respuesta
        
        if 'horario' in texto_lower:
            return "🕒 Horario: 12pm a 10pm"
        
        if 'ubicacion' in texto_lower:
            return "📍 Ubicación: Cali, Colombia"
        
        return f"👋 Hola! Soy el asistente de {tenant['nombre']}. ¿Qué te gustaría ordenar?"

message_handler = MessageHandler()