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
    
    def send_document(self, tenant, to_number, document_url, filename, caption=""):
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
                "type": "document",
                "document": {
                    "link": document_url,
                    "filename": filename,
                    "caption": caption[:200] if caption else ""
                }
            }
            
            logger.info(f"📄 Enviando documento a {to_number}: {filename}")
            logger.info(f"📄 URL del documento: {document_url}")
            response = requests.post(url, headers=headers, json=payload)
            
            # WhatsApp API puede devolver 200 o 201
            if response.status_code in [200, 201]:
                logger.info(f"✅ Documento enviado exitosamente")
                return True
            else:
                logger.error(f"❌ Error enviando documento: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error en send_document: {e}")
            return False
    
    def send_video(self, tenant, to_number, video_url, caption=""):
        """
        Envía un video por WhatsApp
        
        Args:
            tenant: Diccionario con información del tenant (phone_id, token)
            to_number: Número de teléfono del destinatario
            video_url: URL pública del video
            caption: Texto opcional que acompaña el video
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
                "type": "video",
                "video": {
                    "link": video_url,
                    "caption": caption[:200] if caption else ""
                }
            }
            
            logger.info(f"Enviando video a {to_number}: {video_url}")
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code in [200, 201]:
                logger.info(f"✅ Video enviado exitosamente a {to_number}")
                return True
            else:
                logger.error(f"❌ Error enviando video: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error en send_video: {e}")
            return False
    
    def send_audio(self, tenant, to_number, audio_url):
        """
        Envía un audio por WhatsApp
        
        Args:
            tenant: Diccionario con información del tenant (phone_id, token)
            to_number: Número de teléfono del destinatario
            audio_url: URL pública del audio
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
                "type": "audio",
                "audio": {
                    "link": audio_url
                }
            }
            
            logger.info(f"Enviando audio a {to_number}: {audio_url}")
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code in [200, 201]:
                logger.info(f"✅ Audio enviado exitosamente a {to_number}")
                return True
            else:
                logger.error(f"❌ Error enviando audio: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error en send_audio: {e}")
            return False
    
    def send_media_message(self, tenant, to_number, media_type, media_url, filename=None, caption=""):
        """
        Envía cualquier tipo de medio (imagen, video, documento) por WhatsApp
        Método unificado para enviar diferentes tipos de medios
        
        Args:
            tenant: Diccionario con información del tenant
            to_number: Número del destinatario
            media_type: 'image', 'video', 'document', 'audio'
            media_url: URL del archivo
            filename: Nombre del archivo (solo para documentos)
            caption: Texto opcional
        """
        if media_type == 'image':
            return self.send_image(tenant, to_number, media_url, caption)
        elif media_type == 'video':
            return self.send_video(tenant, to_number, media_url, caption)
        elif media_type == 'document':
            doc_filename = filename or 'documento.pdf'
            return self.send_document(tenant, to_number, media_url, doc_filename, caption)
        elif media_type == 'audio':
            return self.send_audio(tenant, to_number, media_url)
        else:
            logger.error(f"Tipo de medio no soportado: {media_type}")
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