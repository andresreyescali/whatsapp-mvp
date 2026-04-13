from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from orders.repository import order_repo
from orders.payment import generar_link_pago
from whatsapp.client import whatsapp_client
from core.logger import logger
import json

class MessageHandler:
    def process(self, phone_id: str, numero: str, texto: str):
        """Procesa mensaje entrante y envía respuesta"""
        logger.info(f'Procesando mensaje de {numero}: {texto}')
        
        # Obtener tenant
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'Tenant no encontrado para phone_id: {phone_id}')
            return
        
        logger.info(f'Tenant encontrado: {tenant["nombre"]} (ID: {tenant["id"]})')
        
        # Obtener menú
        menu = schema_manager.get_menu(tenant['id'])
        logger.info(f'Menú obtenido: {len(menu)} productos')
        
        # Generar respuesta según el mensaje
        respuesta = self._generar_respuesta(texto, tenant, menu, numero)
        
        # Enviar respuesta por WhatsApp
        if respuesta:
            logger.info(f'Enviando respuesta a {numero}: {respuesta[:100]}...')
            whatsapp_client.send_message(tenant, numero, respuesta)
        else:
            logger.warning(f'No se generó respuesta para {numero}')
    
    def _generar_respuesta(self, texto: str, tenant: dict, menu: list, numero: str) -> str:
        """Genera respuesta según el mensaje del cliente"""
        texto_lower = texto.lower().strip()
        
        # 1. Comando: menu
        if texto_lower == 'menu' or texto_lower == 'ver menu' or texto_lower == 'menú':
            return self._formatear_menu(menu)
        
        # 2. Comando: horario
        if 'horario' in texto_lower or 'hora' in texto_lower:
            return "🕒 *Horario de atención*\n\nLunes a Domingo\n12:00 pm - 10:00 pm"
        
        # 3. Comando: ubicacion
        if 'ubicacion' in texto_lower or 'ubicación' in texto_lower or 'donde' in texto_lower:
            return "📍 *Ubicación*\n\nCalle 123 #45-67, Cali, Colombia\n\n📱 Escríbenos para coordinar envío"
        
        # 4. Comando: pago
        if 'pague' in texto_lower or 'pago' in texto_lower or 'ya pague' in texto_lower or 'ya pagué' in texto_lower:
            order_repo.marcar_pagado(tenant['id'], numero)
            return "✅ *¡Pago confirmado!*\n\nTu pedido está siendo preparado y pronto estará en camino. 🚀"
        
        # 5. Detectar pedido de producto
        producto_encontrado = None
        for producto in menu:
            if producto['nombre'].lower() in texto_lower:
                producto_encontrado = producto
                break
        
        if producto_encontrado:
            # Crear pedido
            pedido = order_repo.create(
                tenant['id'], 
                numero, 
                producto_encontrado['nombre'], 
                producto_encontrado['precio']
            )
            link_pago = generar_link_pago(pedido['total'], pedido['id'])
            
            return f"""🍕 *¡Pedido confirmado!*

**Producto:** {producto_encontrado['nombre']}
**Precio:** ${producto_encontrado['precio']:,.0f}

📝 *Tu pedido ID:* `{pedido['id'][:8]}...`

🔗 *Paga aquí:*
{link_pago}

✍️ *Escribe "ya pague"* cuando completes el pago."""
        
        # 6. Saludo o mensaje no reconocido
        if any(saludo in texto_lower for saludo in ['hola', 'buenas', 'holi', 'que tal', 'saludos']):
            return f"""👋 *¡Hola! Bienvenido a {tenant['nombre']}*

🍕 Escribe *"menu"* para ver todos nuestros productos
📍 Escribe *"ubicacion"* para saber dónde estamos
🕒 Escribe *"horario"* para conocer nuestra atención

¿En qué podemos ayudarte hoy?"""
        
        # 7. Respuesta por defecto
        return f"""🤖 *Hola! Soy el asistente de {tenant['nombre']}*

Comandos disponibles:
• *menu* - Ver productos disponibles
• *horario* - Horario de atención  
• *ubicacion* - Dónde encontrarnos
• *[nombre del producto]* - Para hacer un pedido

¿Qué te gustaría ordenar?"""
    
    def _formatear_menu(self, menu: list) -> str:
        """Formatea el menú para mostrar al cliente"""
        if not menu:
            return "📋 *Menú*\n\nActualmente no hay productos disponibles. Por favor consulta más tarde."
        
        # Agrupar por categoría
        categorias = {}
        for p in menu:
            cat = p.get('categoria', 'general')
            if cat not in categorias:
                categorias[cat] = []
            categorias[cat].append(p)
        
        # Emojis por categoría
        emojis = {
            'pizzas': '🍕',
            'hamburguesas': '🍔',
            'bebidas': '🥤',
            'postres': '🍰',
            'acompañamientos': '🍟',
            'general': '📦'
        }
        
        respuesta = "📋 *MENÚ*\n\n"
        
        for categoria, productos in categorias.items():
            emoji = emojis.get(categoria, '📦')
            respuesta += f"*{emoji} {categoria.upper()}*\n"
            for p in productos:
                precio = f"${p['precio']:,.0f}"
                respuesta += f"• *{p['nombre']}* - {precio}\n"
                if p.get('descripcion'):
                    respuesta += f"  _{p['descripcion'][:50]}_\n"
            respuesta += "\n"
        
        respuesta += "✍️ *Para pedir:* Escribe el nombre del producto\n"
        respuesta += "💳 *Para pagar:* Recibirás un link de pago después de tu pedido"
        
        return respuesta

# Instancia global
message_handler = MessageHandler()