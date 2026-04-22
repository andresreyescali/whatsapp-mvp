import requests
from core.logger import logger

class WhatsAppClient:
    """Cliente para enviar mensajes por WhatsApp"""
    
    def send_message(self, tenant, numero: str, mensaje: str) -> bool:
        """Envía un mensaje de WhatsApp usando la API de Meta"""
        
        url = f"https://graph.facebook.com/v18.0/{tenant['phone_id']}/messages"
        
        headers = {
            "Authorization": f"Bearer {tenant['token']}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messaging_product": "whatsapp",
            "to": numero,
            "text": {"body": mensaje}
        }
        
        logger.info(f"📤 Enviando mensaje a {numero}")
        logger.info(f"URL: {url}")
        logger.info(f"Phone ID: {tenant['phone_id']}")
        logger.info(f"Token: {tenant['token'][:50]}...")
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            logger.info(f"Respuesta WhatsApp - Status: {response.status_code}")
            logger.info(f"Respuesta WhatsApp - Body: {response.text}")
            
            if response.status_code == 200:
                logger.info(f'✅ Mensaje enviado a {numero}')
                return True
            else:
                logger.error(f'❌ Error WhatsApp: {response.status_code} - {response.text}')
                return False
                
        except requests.exceptions.Timeout:
            logger.error(f'⏰ Timeout enviando mensaje a {numero}')
            return False
        except Exception as e:
            logger.error(f'❌ Error enviando mensaje: {e}')
            return False

whatsapp_client = WhatsAppClient()