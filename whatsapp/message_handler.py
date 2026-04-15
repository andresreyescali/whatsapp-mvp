from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from orders.repository import order_repo
from orders.payment import generar_link_pago
from whatsapp.client import whatsapp_client
from ai.client import ai_client
from core.logger import logger
import json

class MessageHandler:
    def process(self, phone_id: str, numero: str, texto: str):
        """Procesa mensaje entrante usando SOLO IA"""
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
        
        # Generar respuesta con IA
        respuesta = self._responder_con_ia(texto, tenant, menu, numero, pedidos_pendientes)
        
        # Enviar respuesta
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
    
    def _responder_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, pedidos_pendientes: list) -> str:
        """Usa DeepSeek para generar todas las respuestas"""
        
        # Si no hay cliente de IA, usar fallback
        if not ai_client.client:
            logger.warning("Cliente de IA no disponible, usando fallback")
            return self._respuesta_fallback(texto, tenant, menu, numero)
        
        # Construir contexto del menú
        menu_contexto = self._formatear_menu_para_ia(menu)
        
        # Construir contexto de pedidos pendientes
        pedidos_contexto = ""
        if pedidos_pendientes:
            pedidos_contexto = "\nPEDIDOS PENDIENTES DEL CLIENTE:\n"
            for p in pedidos_pendientes:
                pedidos_contexto += f"- {p['items'][0]['nombre'] if p.get('items') else 'Producto'}: ${p['total']} (ID: {p['id']})\n"
        
        # Prompt del sistema
        system_prompt = f"""Eres un asistente de ventas por WhatsApp para {tenant['nombre']}, una {tenant.get('tipo_negocio', 'restaurante')}.

CONTEXTO DEL NEGOCIO:
- Nombre: {tenant['nombre']}
- Horario: 12pm a 10pm (todos los días)
- Ubicación: Cali, Colombia
- Tipo de negocio: {tenant.get('tipo_negocio', 'restaurante')}

MENÚ COMPLETO:
{menu_contexto}

{pedidos_contexto}

REGLAS IMPORTANTES:
1. Eres un vendedor amable, conversacional y natural.
2. Tu objetivo es ayudar al cliente a hacer un pedido.
3. Si el cliente pide el menú, preséntalo de forma atractiva.
4. Si el cliente pregunta por horario o ubicación, responde con la información.
5. Si el cliente quiere comprar algo, confirma el producto, el precio y genera un link de pago.
6. Para generar un link de pago, usa el formato: https://checkout.wompi.co/l/test_[ID_PEDIDO]_[TOTAL]
7. Si el cliente dice "ya pague" o similar, confirma el pago y despídete amablemente.
8. Responde SIEMPRE en español, de forma breve pero completa (2-4 oraciones).
9. Sé proactivo: si el cliente duda, recomienda los productos más populares.
10. Si el cliente pide algo que no está en el menú, ofrécele alternativas similares.

INSTRUCCIÓN CRÍTICA: Tu respuesta debe ser SOLO el mensaje para el cliente, sin explicaciones adicionales."""
        
        # Mensaje del usuario
        user_message = f"""Cliente dice: "{texto}"

Genera una respuesta amable y útil para este cliente."""
        
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
    
    def _detectar_y_crear_pedido(self, respuesta_ia: str, texto_original: str, tenant: dict, menu: list, numero: str) -> tuple:
        """Detecta si la IA quiere crear un pedido y lo ejecuta"""
        
        # Buscar si la respuesta contiene indicación de pedido
        lineas = respuesta_ia.lower().split('\n')
        
        for linea in lineas:
            # Buscar patrones de confirmación de pedido
            if any(palabra in linea for palabra in ['pedido confirmado', 'producto agregado', 'link de pago', 'paga aquí']):
                # Intentar extraer el producto del texto original
                for producto in menu:
                    if producto['nombre'].lower() in texto_original.lower():
                        # Crear pedido
                        pedido = order_repo.create(
                            tenant['id'],
                            numero,
                            producto['nombre'],
                            producto['precio']
                        )
                        link_pago = generar_link_pago(pedido['total'], pedido['id'])
                        
                        # Reemplazar la respuesta con el formato correcto
                        respuesta_nueva = f"""✅ ¡Pedido confirmado!

**Producto:** {producto['nombre']}
**Precio:** ${producto['precio']:,.0f}

🔗 **Link de pago:** {link_pago}

✍️ Escribe "ya pagué" cuando completes el pago."""
                        
                        return respuesta_nueva, True
        
        return respuesta_ia, False
    
    def _formatear_menu_para_ia(self, menu: list) -> str:
        """Formatea el menú para incluirlo en el prompt de IA"""
        if not menu:
            return "No hay productos disponibles actualmente."
        
        # Agrupar por categoría
        categorias = {}
        for p in menu:
            cat = p.get('categoria', 'general')
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
    
    def _respuesta_fallback(self, texto: str, tenant: dict, menu: list, numero: str) -> str:
        """Respuesta de fallback si la IA no está disponible"""
        
        texto_lower = texto.lower()
        
        # Detectar pedido básico
        for producto in menu:
            if producto['nombre'].lower() in texto_lower:
                pedido = order_repo.create(tenant['id'], numero, producto['nombre'], producto['precio'])
                link_pago = generar_link_pago(pedido['total'], pedido['id'])
                return f"✅ Pedido: {producto['nombre']} - ${producto['precio']:,.0f}\n🔗 Paga aquí: {link_pago}"
        
        # Comandos básicos
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

# Instancia global
message_handler = MessageHandler()