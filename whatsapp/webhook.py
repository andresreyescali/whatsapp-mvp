import requests
import os
import uuid
from flask import request
from core.logger import logger
from tenants.repository import tenant_repo
from whatsapp.message_handler import message_handler
from whatsapp.client import whatsapp_client
from ai.vision import vision_client

def register_webhook_routes(app):
    
    @app.route('/webhook', methods=['GET', 'POST'])
    def webhook():
        # Verificación GET
        if request.method == 'GET':
            mode = request.args.get('hub.mode')
            token = request.args.get('hub.verify_token')
            challenge = request.args.get('hub.challenge')
            
            verify_token = "EAAUn9pg7tjIBRAIeJcCwfuS8npQDT4bZCTFZCQjLz9ge6ZAcQPHCZAZCaPWkglZBf7FgvRCYVlgZCjJCpdNZBZAA23l95ABJhE1mnq8eFjy7jBC6kDZCSR7VzC2mZB7x5ZBe8pzpjg3wQGkji4flEjZBuAxnSdUs3r1yNhcZA0ZBJXx0DyWtbmxNP47X5mzTZBP0bXZCjDevZAoyPO9BwheuhbPVZC0jlspVpWafQ6mVcZBM06quFtv6"
            
            if mode == 'subscribe' and token == verify_token:
                logger.info("✅ Webhook verificado")
                return challenge, 200
            return "Verification failed", 403
        
        # Procesar mensajes POST
        try:
            data = request.get_json(force=True)
            logger.info(f"📨 POST recibido")
            
            # Extraer información del mensaje
            entry = data.get('entry', [])
            if not entry:
                return "ok", 200
            
            changes = entry[0].get('changes', [])
            if not changes:
                return "ok", 200
            
            value = changes[0].get('value', {})
            
            # Verificar si hay mensajes
            if 'messages' not in value:
                logger.info("Evento sin mensaje")
                return "ok", 200
            
            message = value['messages'][0]
            
            # Extraer datos comunes
            phone_id = value['metadata']['phone_number_id']
            from_number = message['from']
            message_type = message.get('type')
            timestamp = message.get('timestamp')
            
            logger.info(f"📱 Mensaje de {from_number} - Tipo: {message_type}")
            
            # Buscar el tenant
            tenant = tenant_repo.find_by_phone_id(phone_id)
            if not tenant:
                logger.warning(f"No se encontró tenant para phone_id: {phone_id}")
                return "ok", 200
            
            logger.info(f"Tenant encontrado: {tenant['nombre']}")
            
            # Procesar según el tipo de mensaje
            if message_type == 'text':
                text = message['text']['body']
                logger.info(f"📝 Texto: {text[:100]}")
                message_handler.process(phone_id, from_number, text)
            
            elif message_type == 'image':
                # Procesar imagen recibida
                image_data = message.get('image', {})
                media_id = image_data.get('id')
                caption = image_data.get('caption', '')
                mime_type = image_data.get('mime_type', 'image/jpeg')
                
                logger.info(f"📷 Imagen recibida - Media ID: {media_id}, Caption: {caption}")
                
                # Descargar y procesar la imagen
                respuesta = procesar_imagen_recibida(tenant, from_number, media_id, caption, mime_type)
                
                # Enviar respuesta
                if respuesta:
                    whatsapp_client.send_message(tenant, from_number, respuesta)
                
                # Guardar en conversación
                guardar_conversacion_con_archivo(tenant, from_number, f"[IMAGEN] {caption}", respuesta, 'image', media_id)
            
            elif message_type == 'document':
                # Procesar documento recibido
                doc_data = message.get('document', {})
                media_id = doc_data.get('id')
                filename = doc_data.get('filename', 'documento')
                caption = doc_data.get('caption', '')
                mime_type = doc_data.get('mime_type', 'application/pdf')
                
                logger.info(f"📄 Documento recibido - Nombre: {filename}, Media ID: {media_id}")
                
                # Descargar y procesar el documento
                respuesta = procesar_documento_recibido(tenant, from_number, media_id, filename, caption, mime_type)
                
                if respuesta:
                    whatsapp_client.send_message(tenant, from_number, respuesta)
                
                guardar_conversacion_con_archivo(tenant, from_number, f"[DOCUMENTO] {filename}: {caption}", respuesta, 'document', media_id)
            
            elif message_type == 'video':
                # Procesar video recibido
                video_data = message.get('video', {})
                media_id = video_data.get('id')
                caption = video_data.get('caption', '')
                mime_type = video_data.get('mime_type', 'video/mp4')
                
                logger.info(f"🎥 Video recibido - Media ID: {media_id}, Caption: {caption}")
                
                respuesta = procesar_video_recibido(tenant, from_number, media_id, caption, mime_type)
                
                if respuesta:
                    whatsapp_client.send_message(tenant, from_number, respuesta)
                
                guardar_conversacion_con_archivo(tenant, from_number, f"[VIDEO] {caption}", respuesta, 'video', media_id)
            
            elif message_type == 'audio':
                # Procesar audio recibido
                audio_data = message.get('audio', {})
                media_id = audio_data.get('id')
                mime_type = audio_data.get('mime_type', 'audio/ogg')
                
                logger.info(f"🎵 Audio recibido - Media ID: {media_id}")
                
                respuesta = procesar_audio_recibido(tenant, from_number, media_id, mime_type)
                
                if respuesta:
                    whatsapp_client.send_message(tenant, from_number, respuesta)
                
                guardar_conversacion_con_archivo(tenant, from_number, "[AUDIO]", respuesta, 'audio', media_id)
            
            elif message_type == 'location':
                # Procesar ubicación recibida
                location_data = message.get('location', {})
                latitude = location_data.get('latitude')
                longitude = location_data.get('longitude')
                name = location_data.get('name', '')
                
                logger.info(f"📍 Ubicación recibida - Lat: {latitude}, Lon: {longitude}")
                
                respuesta = f"📍 ¡Gracias por compartir tu ubicación! Estás en coordenadas: {latitude}, {longitude}"
                whatsapp_client.send_message(tenant, from_number, respuesta)
                
                guardar_conversacion_con_archivo(tenant, from_number, f"[UBICACIÓN] {name}", respuesta, 'location', None)
            
            else:
                logger.info(f"Tipo de mensaje no manejado: {message_type}")
                whatsapp_client.send_message(tenant, from_number, "Recibí tu mensaje, gracias.")
            
            return "ok", 200
            
        except Exception as e:
            logger.error(f"❌ Error en webhook: {e}")
            import traceback
            traceback.print_exc()
            return "error", 500


# ==================== FUNCIONES PARA PROCESAR ARCHIVOS RECIBIDOS ====================

def descargar_media(tenant, media_id):
    """
    Descarga un archivo multimedia usando el Media ID de WhatsApp
    Retorna la URL pública o el contenido del archivo
    """
    try:
        # Obtener la URL de descarga del media
        token = tenant['token']
        url_media_info = f"https://graph.facebook.com/v18.0/{media_id}"
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.get(url_media_info, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Error obteniendo info del media: {response.text}")
            return None
        
        media_info = response.json()
        media_url = media_info.get('url')
        
        if not media_url:
            logger.error("No se encontró URL del media")
            return None
        
        # Descargar el archivo
        media_response = requests.get(media_url, headers=headers)
        
        if media_response.status_code != 200:
            logger.error(f"Error descargando media: {media_response.text}")
            return None
        
        return {
            'url': media_url,
            'content': media_response.content,
            'info': media_info
        }
        
    except Exception as e:
        logger.error(f"Error en descargar_media: {e}")
        return None


def guardar_archivo_local(tenant_id, from_number, media_id, extension):
    """
    Guarda un archivo localmente y retorna la ruta
    """
    try:
        # Crear directorio si no existe
        upload_dir = f"uploads/tenants/{tenant_id}/{from_number}"
        os.makedirs(upload_dir, exist_ok=True)
        
        # Generar nombre único
        unique_filename = f"{uuid.uuid4().hex}.{extension}"
        filepath = os.path.join(upload_dir, unique_filename)
        
        return {
            'path': filepath,
            'filename': unique_filename,
            'dir': upload_dir
        }
        
    except Exception as e:
        logger.error(f"Error guardando archivo local: {e}")
        return None


def guardar_conversacion_con_archivo(tenant, from_number, mensaje_cliente, respuesta, tipo, media_id):
    """Guarda la conversación incluyendo referencia al archivo"""
    try:
        from core.database import db_manager
        from tenants.schema_manager import schema_manager
        
        schema_name = schema_manager._get_schema_name(tenant['id'])
        
        with db_manager.get_connection(tenant['id']) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO "{schema_name}".conversaciones 
                    (cliente_numero, mensaje, respuesta, tipo, created_at, media_id, media_type)
                    VALUES (%s, %s, %s, %s, NOW(), %s, %s)
                """, (from_number, mensaje_cliente, respuesta or 'Procesado', 'ia', media_id, tipo))
            conn.commit()
        logger.info(f"Conversación guardada con archivo tipo: {tipo}")
    except Exception as e:
        logger.error(f"Error guardando conversación con archivo: {e}")


def procesar_imagen_recibida(tenant, from_number, media_id, caption, mime_type):
    """
    Procesa la imagen recibida del cliente incluyendo análisis con IA
    """
    try:
        logger.info(f"🖼️ Procesando imagen de {from_number}")
        
        # Descargar la imagen
        media_data = descargar_media(tenant, media_id)
        
        if not media_data:
            return "📷 Recibí tu imagen, pero tuve problemas para descargarla. ¿Puedes intentar de nuevo?"
        
        # Guardar la imagen localmente
        extension = mime_type.split('/')[-1] if mime_type else 'jpg'
        archivo_info = guardar_archivo_local(tenant['id'], from_number, media_id, extension)
        
        if archivo_info:
            with open(archivo_info['path'], 'wb') as f:
                f.write(media_data['content'])
            logger.info(f"✅ Imagen guardada en: {archivo_info['path']}")
        
        # ========== ANALIZAR LA IMAGEN CON IA ==========
        analisis_texto = None
        
        if archivo_info:
            # Analizar diseño para torta
            analisis = vision_client.analyze_design_for_cake(archivo_info['path'])
            
            if analisis:
                analisis_texto = analisis
                logger.info(f"🔍 Análisis de imagen completado")
        
        # Construir respuesta
        respuesta = "📸 *¡Imagen recibida!*\n\n"
        
        if caption and caption.strip():
            respuesta += f"*Tu referencia:* {caption}\n\n"
        
        # Incluir análisis si está disponible
        if analisis_texto:
            respuesta += f"*🔍 Lo que veo en tu imagen:*\n{analisis_texto}\n\n"
            respuesta += "¿Es correcto lo que identificamos? ¿Te gustaría ajustar algo?"
        else:
            respuesta += "He guardado tu imagen de referencia para tenerla en cuenta en tu pedido.\n\n"
            respuesta += "¿Podrías describirme qué tipo de torta te gustaría? (sabor, tamaño, ocasión)"
        
        return respuesta
        
    except Exception as e:
        logger.error(f"Error en procesar_imagen_recibida: {e}")
        return "Recibí tu imagen, pero hubo un error al procesarla. ¿Puedes intentar de nuevo?"
    

def procesar_documento_recibido(tenant, from_number, media_id, filename, caption, mime_type):
    """
    Procesa el documento recibido del cliente
    """
    try:
        logger.info(f"📄 Procesando documento de {from_number}: {filename}")
        
        # Descargar el documento
        media_data = descargar_media(tenant, media_id)
        
        if not media_data:
            return "📄 Recibí tu documento, pero tuve problemas para descargarlo. ¿Puedes intentar de nuevo?"
        
        # Guardar el documento localmente
        extension = filename.split('.')[-1] if '.' in filename else 'pdf'
        archivo_info = guardar_archivo_local(tenant['id'], from_number, media_id, extension)
        
        if archivo_info:
            with open(archivo_info['path'], 'wb') as f:
                f.write(media_data['content'])
            logger.info(f"✅ Documento guardado en: {archivo_info['path']}")
        
        respuesta = "📄 *¡Documento recibido!*\n\n"
        
        if caption and caption.strip():
            respuesta += f"*Referencia:* {caption}\n\n"
        
        respuesta += "He guardado tu documento. Revisaré la información y te responderé pronto."
        
        return respuesta
        
    except Exception as e:
        logger.error(f"Error en procesar_documento_recibido: {e}")
        return "Recibí tu documento, pero hubo un error al procesarlo."


def procesar_video_recibido(tenant, from_number, media_id, caption, mime_type):
    """
    Procesa el video recibido del cliente
    """
    try:
        logger.info(f"🎥 Procesando video de {from_number}")
        
        media_data = descargar_media(tenant, media_id)
        
        if not media_data:
            return "🎥 Recibí tu video, pero tuve problemas para descargarlo."
        
        extension = 'mp4'
        archivo_info = guardar_archivo_local(tenant['id'], from_number, media_id, extension)
        
        if archivo_info:
            with open(archivo_info['path'], 'wb') as f:
                f.write(media_data['content'])
            logger.info(f"✅ Video guardado en: {archivo_info['path']}")
        
        respuesta = "🎥 *¡Video recibido!*\n\nHe guardado tu video de referencia. ¿Algún detalle adicional que quieras agregar a tu pedido?"
        
        return respuesta
        
    except Exception as e:
        logger.error(f"Error en procesar_video_recibido: {e}")
        return "Recibí tu video, pero hubo un error al procesarlo."


def procesar_audio_recibido(tenant, from_number, media_id, mime_type):
    """
    Procesa el audio recibido del cliente (nota de voz)
    """
    try:
        logger.info(f"🎵 Procesando audio de {from_number}")
        
        media_data = descargar_media(tenant, media_id)
        
        if not media_data:
            return "🎵 Recibí tu nota de voz, pero tuve problemas para descargarla."
        
        extension = 'ogg'
        archivo_info = guardar_archivo_local(tenant['id'], from_number, media_id, extension)
        
        if archivo_info:
            with open(archivo_info['path'], 'wb') as f:
                f.write(media_data['content'])
            logger.info(f"✅ Audio guardado en: {archivo_info['path']}")
        
        respuesta = "🎙️ *¡Nota de voz recibida!*\n\nGracias por tu mensaje. He guardado tu audio y lo revisaré."
        
        return respuesta
        
    except Exception as e:
        logger.error(f"Error en procesar_audio_recibido: {e}")
        return "Recibí tu nota de voz, pero hubo un error al procesarla."