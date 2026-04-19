import base64
import io
import json
import re
from PIL import Image
import pytesseract
from core.logger import logger
from ai.client import ai_client

class IATrainer:
    """Entrenador de IA para cada negocio con soporte OCR"""
    
    def procesar_imagen(self, image_base64: str) -> dict:
        """Procesa una imagen de menú usando Tesseract OCR + IA"""
        
        try:
            # 1. Decodificar la imagen base64
            image_data = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_data))
            
            # 2. Aplicar OCR con Tesseract (español)
            logger.info("Aplicando OCR a la imagen...")
            texto_extraido = pytesseract.image_to_string(image, lang='spa')
            
            if not texto_extraido or len(texto_extraido.strip()) < 10:
                logger.warning("No se pudo extraer texto suficiente de la imagen")
                return None
            
            logger.info(f"Texto extraído ({len(texto_extraido)} caracteres): {texto_extraido[:200]}...")
            
            # 3. Usar IA para estructurar el texto extraído
            resultado = self._estructurar_con_ia(texto_extraido)
            
            return resultado
            
        except Exception as e:
            logger.error(f"Error procesando imagen con OCR: {e}")
            return None
    
    def _estructurar_con_ia(self, texto_ocr: str) -> dict:
        """Usa IA para estructurar el texto extraído por OCR"""
        
        prompt = f"""
        Eres un experto en extraer información de menús de restaurantes.
        
        Este texto fue extraído de una imagen de menú mediante OCR. Puede tener errores.
        Limpia y estructura la información:
        
        TEXTO EXTRAÍDO:
        {texto_ocr}
        
        Extrae y devuelve SOLO un JSON válido con:
        {{
            "productos": [
                {{"nombre": "", "precio": 0, "descripcion": "", "categoria": ""}}
            ],
            "horario": "",
            "ubicacion": "",
            "politicas": "",
            "instrucciones_adicionales": ""
        }}
        
        Si no encuentras cierta información, deja el campo vacío o null.
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.3
            )
            
            resultado = json.loads(response.choices[0].message.content)
            return resultado
            
        except Exception as e:
            logger.error(f"Error estructurando texto con IA: {e}")
            return None
    
    def procesar_texto(self, texto: str) -> dict:
        """Procesa texto descriptivo del negocio (sin OCR)"""
        
        prompt = f"""
        Basado en esta descripción del negocio, extrae la información estructurada:
        
        DESCRIPCIÓN:
        {texto}
        
        Devuelve SOLO un JSON válido:
        {{
            "productos": [{{"nombre": "", "precio": 0, "descripcion": "", "categoria": ""}}],
            "horario": "",
            "ubicacion": "",
            "politicas": "",
            "instrucciones_adicionales": ""
        }}
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.3
            )
            
            resultado = json.loads(response.choices[0].message.content)
            return resultado
            
        except Exception as e:
            logger.error(f"Error procesando texto: {e}")
            return None
    
    def generar_prompt_personalizado(self, contexto: dict) -> str:
        """Genera prompt personalizado para el asistente"""
        
        prompt = f"""
        Genera un prompt de sistema para un asistente de ventas de WhatsApp.
        
        Información del negocio:
        - Productos: {json.dumps(contexto.get('productos', []), indent=2)}
        - Horario: {contexto.get('horario', 'No especificado')}
        - Ubicación: {contexto.get('ubicacion', 'No especificada')}
        - Políticas: {contexto.get('politicas', 'No especificadas')}
        - Instrucciones: {contexto.get('instrucciones_adicionales', '')}
        
        El prompt debe ser breve, en español, incluyendo toda esta información.
        Responde SOLO con el prompt.
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.5
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error generando prompt: {e}")
            return None

# Instancia global
trainer = IATrainer()