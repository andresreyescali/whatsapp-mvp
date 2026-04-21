from flask import request
from core.logger import logger

def register_webhook_routes(app):
    
    @app.route('/webhook', methods=['GET', 'POST'])
    def webhook():
        # LOG para cualquier petición
        logger.info(f"Webhook llamado - Método: {request.method}")
        
        # VERIFICACIÓN GET (solo para Meta)
        if request.method == 'GET':
            mode = request.args.get('hub.mode')
            token = request.args.get('hub.verify_token')
            challenge = request.args.get('hub.challenge')
            
            verify_token = "EAAUn9pg7tjIBRAIeJcCwfuS8npQDT4bZCTFZCQjLz9ge6ZAcQPHCZAZCaPWkglZBf7FgvRCYVlgZCjJCpdNZBZAA23l95ABJhE1mnq8eFjy7jBC6kDZCSR7VzC2mZB7x5ZBe8pzpjg3wQGkji4flEjZBuAxnSdUs3r1yNhcZA0ZBJXx0DyWtbmxNP47X5mzTZBP0bXZCjDevZAoyPO9BwheuhbPVZC0jlspVpWafQ6mVcZBM06quFtv6"
            
            if mode == 'subscribe' and token == verify_token:
                logger.info("✅ Webhook verificado correctamente")
                return challenge, 200
            else:
                logger.warning(f"❌ Verificación fallida. Token recibido: {token[:30]}...")
                return "Verification failed", 403
        
        # PROCESAR MENSAJES POST
        try:
            data = request.get_json(force=True)
            logger.info(f"📨 POST recibido: {data}")
            
            # Verificar si es un mensaje de WhatsApp real
            if data.get('object') == 'whatsapp_business_account':
                entry = data.get('entry', [])
                if entry:
                    changes = entry[0].get('changes', [])
                    if changes:
                        value = changes[0].get('value', {})
                        messages = value.get('messages', [])
                        if messages:
                            msg = messages[0]
                            from_number = msg.get('from')
                            text = msg.get('text', {}).get('body')
                            logger.info(f"📱 Mensaje de {from_number}: {text}")
                            
                            # Aquí llamas a message_handler.process()
                            # from whatsapp.message_handler import message_handler
                            # message_handler.process(phone_id, from_number, text)
                            
            return "ok", 200
            
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return "error", 500