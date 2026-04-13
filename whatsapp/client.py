import requests
from core.logger import logger

class WhatsAppClient:
    """Cliente para enviar mensajes por WhatsApp"""
    
    def send_message(self, tenant, numero: str, mensaje: str) -> bool:
        """Envía un mensaje de WhatsApp usando la API de Meta"""
        
        url = f"https://graph.facebook.com/v15.0/{tenant['phone_id']}/messages"
        
        headers = {
            "Authorization": f"Bearer {tenant['token']}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messaging_product": "whatsapp",
            "to": numero,
            "text": {"body": mensaje}
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                logger.info(f'Mensaje enviado a {numero}')
                return True
            else:
                logger.error(f'Error WhatsApp: {response.status_code} - {response.text}')
                return False
                
        except requests.exceptions.Timeout:
            logger.error(f'Timeout enviando mensaje a {numero}')
            return False
        except Exception as e:
            logger.error(f'Error enviando mensaje: {e}')
            return False

# Instancia global
whatsapp_client = WhatsAppClient()