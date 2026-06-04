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

        # ========= METODOS PARA ENVIAR IMAGEN POR WHATSAPP =======

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
                        "caption": caption[:200]  # Máximo 200 caracteres para el caption
                    }
                }
                
                logger.info(f"Enviando imagen a {to_number}: {image_url}")
                response = requests.post(url, headers=headers, json=payload)
                
                if response.status_code == 201:
                    logger.info(f"Imagen enviada exitosamente a {to_number}")
                    return True
                else:
                    logger.error(f"Error enviando imagen: {response.status_code} - {response.text}")
                    return False
                    
            except Exception as e:
                logger.error(f"Error en send_image: {e}")
                return False

        def _format_phone_number(self, number):
            """Formatea el número de teléfono para WhatsApp API"""
            import re
            number = re.sub(r'\D', '', str(number))
            if not number.startswith('57') and len(number) == 10:
                number = '57' + number
            if not number.startswith('+'):
                number = '+' + number
            return number

whatsapp_client = WhatsAppClient()