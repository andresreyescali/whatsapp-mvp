from flask import request
from core.logger import logger
from whatsapp.message_handler import message_handler

def register_webhook_routes(app):
    @app.route('/webhook', methods=['GET', 'POST'])
    def webhook():
        if request.method == 'GET':
            verify_token = "EAAUn9pg7tjIBRAIeJcCwfuS8npQDT4bZCTFZCQjLz9ge6ZAcQPHCZAZCaPWkglZBf7FgvRCYVlgZCjJCpdNZBZAA23l95ABJhE1mnq8eFjy7jBC6kDZCSR7VzC2mZB7x5ZBe8pzpjg3wQGkji4flEjZBuAxnSdUs3r1yNhcZA0ZBJXx0DyWtbmxNP47X5mzTZBP0bXZCjDevZAoyPO9BwheuhbPVZC0jlspVpWafQ6mVcZBM06quFtv6"
            if request.args.get("hub.verify_token") == verify_token:
                return request.args.get("hub.challenge")
            return "Error", 403
        
        data = request.get_json(force=True)
        logger.info(f'Webhook recibido')
        
        try:
            value = data["entry"][0]["changes"][0]["value"]
            
            if "messages" not in value:
                return "ok"
            
            mensaje = value["messages"][0]
            if "text" not in mensaje:
                return "ok"
            
            phone_id = value["metadata"]["phone_number_id"]
            numero = mensaje["from"]
            texto = mensaje["text"]["body"]
            
            logger.info(f'Mensaje de {numero}: {texto}')
            
            # Procesar mensaje
            message_handler.process(phone_id, numero, texto)
            
        except Exception as e:
            logger.error(f'Error en webhook: {e}')
            import traceback
            traceback.print_exc()
            return "error", 500
        
        return "ok"