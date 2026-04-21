from flask import request
from core.logger import logger
from tenants.repository import tenant_repo
from whatsapp.message_handler import message_handler

def register_webhook_routes(app):
    
    @app.route('/webhook', methods=['GET', 'POST'])
    def webhook():
        # Verificación GET
        if request.method == 'GET':
            mode = request.args.get('hub.mode')
            token = request.args.get('hub.verify_token')
            challenge = request.args.get('hub.challenge')
            
            verify_token = "EAAUn9pg7tjIBRAIeJcCwfuS8npQDT4bZCTFZCQjLz9ge6ZAcQPHCZAZCaPWkglZBf7FgvRCYVlgZCjJCpdNZBZAA23l95ABJhE1mnq8eFjy7jBC6kDZCSR7VzC2mZB7x5ZBe8pzpjg3wQGkji4flEjZBuAxnSdUs3r1yNhcZA0ZBJXx0DyWtbmxNP47X5mzTZBP0bXZCjDevZAoyPO9BwheuhbPVZC0jlspVpWafQ6mVcZBM06quFtv6"
            
            if mode == 'subscribe' and token == verify_token:
                logger.info("✅ Webhook verificado")
                return challenge, 200
            return "Verification failed", 403
        
        # Procesar mensajes POST
        try:
            data = request.get_json(force=True)
            logger.info(f"📨 POST recibido")
            
            # Extraer información del mensaje
            entry = data.get('entry', [])
            if not entry:
                return "ok", 200
            
            changes = entry[0].get('changes', [])
            if not changes:
                return "ok", 200
            
            value = changes[0].get('value', {})
            
            # Verificar si hay mensajes
            if 'messages' not in value:
                logger.info("Evento sin mensaje")
                return "ok", 200
            
            message = value['messages'][0]
            if 'text' not in message:
                logger.info("Mensaje sin texto")
                return "ok", 200
            
            # Extraer datos
            phone_id = value['metadata']['phone_number_id']
            from_number = message['from']
            text = message['text']['body']
            
            logger.info(f"📱 Mensaje de {from_number}: {text}")
            
            # Buscar el tenant
            tenant = tenant_repo.find_by_phone_id(phone_id)
            if not tenant:
                logger.warning(f"No se encontró tenant para phone_id: {phone_id}")
                return "ok", 200
            
            logger.info(f"Tenant encontrado: {tenant['nombre']}")
            
            # 🔥 PROCESAR EL MENSAJE Y ENVIAR RESPUESTA
            message_handler.process(phone_id, from_number, text)
            
            return "ok", 200
            
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return "error", 500