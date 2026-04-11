import requests
from core.logger import logger

class WhatsAppClient:
    def send_message(self, tenant, numero: str, mensaje: str):
        url = f'https://graph.facebook.com/v15.0/{tenant["phone_id"]}/messages'
        headers = {'Authorization': f'Bearer {tenant["token"]}', 'Content-Type': 'application/json'}
        data = {'messaging_product': 'whatsapp', 'to': numero, 'text': {'body': mensaje}}
        try:
            r = requests.post(url, headers=headers, json=data, timeout=10)
            logger.info(f'Mensaje enviado a {numero}')
            return r.status_code == 200
        except Exception as e:
            logger.error(f'Error: {e}')
            return False

whatsapp_client = WhatsAppClient()