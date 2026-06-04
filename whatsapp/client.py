import re
import requests
from core.logger import logger

class WhatsAppClient:
    def __init__(self):
        logger.info('WhatsApp Client inicializado')
    
    def send_image(self, tenant, to_number, image_url, caption=""):
        """
        Envía una imagen por WhatsApp
        
        Args:
            tenant: Diccionario con información del tenant (phone_id, token)
            to_number: Número de teléfono del destinatario
            image_url: URL pública de la imagen
            caption: Texto opcional que acompaña la imagen
        """
        try:
            phone_id = tenant['phone_id']
            token = tenant['token']
            
            url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            # Formatear número de teléfono
            formatted_number = self._format_phone_number(to_number)
            
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": formatted_number,
                "type": "image",
                "image": {
                    "link": image_url,
                    "caption": caption[:200] if caption else ""
                }
            }
            
            logger.info(f"Enviando imagen a {to_number}: {image_url}")
            response = requests.post(url, headers=headers, json=payload)
            
            # WhatsApp API devuelve 200 OK o 201 Created
            if response.status_code in [200, 201]:
                logger.info(f"✅ Imagen enviada exitosamente a {to_number}")
                return True
            else:
                logger.error(f"❌ Error enviando imagen: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error en send_image: {e}")
            return False
    
    def send_message(self, tenant, to_number, message):
        """
        Envía un mensaje de texto por WhatsApp
        """
        try:
            phone_id = tenant['phone_id']
            token = tenant['token']
            
            url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            formatted_number = self._format_phone_number(to_number)
            
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": formatted_number,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": message
                }
            }
            
            logger.info(f"Enviando mensaje a {to_number}")
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code == 201:
                logger.info(f"Mensaje enviado exitosamente a {to_number}")
                return True
            else:
                logger.error(f"Error enviando mensaje: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error en send_message: {e}")
            return False
    
    def _format_phone_number(self, number):
        """
        Formatea el número de teléfono para WhatsApp API
        """
        # Limpiar el número (solo dígitos)
        number = re.sub(r'\D', '', str(number))
        
        # Si es número colombiano de 10 dígitos (empieza con 3)
        if len(number) == 10 and number.startswith('3'):
            number = '57' + number
        # Si tiene código de país 57 pero es de 12 dígitos
        elif len(number) == 12 and number.startswith('57'):
            number = number
        # Si es más largo, asumir que ya tiene código de país
        elif len(number) > 10:
            number = number
        
        # Agregar + si no lo tiene
        if not number.startswith('+'):
            number = '+' + number
        
        return number

# Instancia global para usar en toda la aplicación
whatsapp_client = WhatsAppClient()