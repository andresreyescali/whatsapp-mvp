from flask import request
from core.logger import logger

def register_webhook_routes(app):
    @app.route('/webhook', methods=['POST'])
    def webhook():
        data = request.get_json(force=True)
        logger.info(f'Webhook recibido: {data}')
        return 'ok'