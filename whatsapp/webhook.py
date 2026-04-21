from flask import request
from core.logger import logger
from whatsapp.message_handler import message_handler
from tenants.repository import tenant_repo

def register_webhook_routes(app):
    
    @app.route('/webhook', methods=['GET', 'POST'])
    def webhook():
        # Verificación GET (ya funciona)
        if request.method == 'GET':
            mode = request.args.get('hub.mode')
            token = request.args.get('hub.verify_token')
            challenge = request.args.get('hub.challenge')
            
            verify_token = "EAAUn9pg7tjIBRAIeJcCwfuS8npQDT4bZCTFZCQjLz9ge6ZAcQPHCZAZCaPWkglZBf7FgvRCYVlgZCjJCpdNZBZAA23l95ABJhE1mnq8eFjy7jBC6kDZCSR7VzC2mZB7x5ZBe8pzpjg3wQGkji4flEjZBuAxnSdUs3r1yNhcZA0ZBJXx0DyWtbmxNP47X5mzTZBP0bXZCjDevZAoyPO9BwheuhbPVZC0jlspVpWafQ6mVcZBM06quFtv6"
            
            if mode == 'subscribe' and token == verify_token:
                logger.info("✅ Webhook verificado correctamente")
                return challenge, 200
            else:
                logger.warning(f"❌ Verificación fallida. mode={mode}, token recibido={token[:20] if token else 'None'}...")
                return "Verification failed", 403
        
        # POST: Procesar mensajes
        try:
            logger.info("=" * 50)
            logger.info("📨 WEBHOOK POST RECIBIDO")
            logger.info("=" * 50)
            
            data = request.get_json(force=True)
            logger.info(f"Datos completos: {data}")
            
            # Extraer información
            entry = data.get('entry', [])
            if not entry:
                logger.warning("No hay entry en el payload")
                return "ok", 200
            
            changes = entry[0].get('changes', [])
            if not changes:
                logger.warning("No hay changes en el payload")
                return "ok", 200
            
            value = changes[0].get('value', {})
            
            # Verificar si hay mensajes
            if 'messages' not in value:
                logger.info("Evento sin mensaje (puede ser status o lectura)")
                return "ok", 200
            
            message = value['messages'][0]
            logger.info(f"Mensaje completo: {message}")
            
            if 'text' not in message:
                logger.info("Mensaje sin texto (puede ser imagen, audio, etc.)")
                return "ok", 200
            
            # Extraer datos importantes
            phone_id = value['metadata']['phone_number_id']
            from_number = message['from']
            text = message['text']['body']
            
            logger.info(f"📱 Phone ID: {phone_id}")
            logger.info(f"👤 De: {from_number}")
            logger.info(f"💬 Texto: {text}")
            
            # Buscar el tenant
            logger.info(f"Buscando tenant con phone_id: {phone_id}")
            tenant = tenant_repo.find_by_phone_id(phone_id)
            
            if not tenant:
                logger.error(f"❌ No se encontró tenant para phone_id: {phone_id}")
                logger.info(f"Tenants disponibles en DB: {tenant_repo.get_all()}")
                return "ok", 200
            
            logger.info(f"✅ Tenant encontrado: {tenant['nombre']} (ID: {tenant['id']})")
            
            # Procesar mensaje
            logger.info("Procesando mensaje con message_handler...")
            message_handler.process(phone_id, from_number, text)
            logger.info("✅ Mensaje procesado correctamente")
            
            return "ok", 200
            
        except Exception as e:
            logger.error(f"❌ Error procesando webhook: {e}")
            import traceback
            traceback.print_exc()
            return "error", 500