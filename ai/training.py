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
    logger.info("=== INICIO _estructurar_con_ia ===")
    
    if not ai_client.client:
        logger.error("Cliente de IA no disponible")
        return None
    
    prompt = f"""
    Extrae información de menú del siguiente texto OCR.
    
    TEXTO OCR:
    {texto_ocr}
    
    IMPORTANTE: Devuelve SOLO un JSON válido. Sin explicaciones, sin markdown.
    
    Formato exacto:
    {{
        "productos": [
            {{"nombre": "nombre", "precio": 12345, "descripcion": "descripción", "categoria": "categoría"}}
        ],
        "horario": "horario",
        "ubicacion": "dirección",
        "politicas": "políticas",
        "instrucciones_adicionales": "instrucciones"
    }}
    """
    
    try:
        response = ai_client.client.chat.completions.create(
            model=ai_client.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3
        )
        
        contenido = response.choices[0].message.content
        
        # Limpiar markdown
        contenido_limpio = contenido.strip()
        if contenido_limpio.startswith('```json'):
            contenido_limpio = contenido_limpio[7:]
        elif contenido_limpio.startswith('```'):
            contenido_limpio = contenido_limpio[3:]
        if contenido_limpio.endswith('```'):
            contenido_limpio = contenido_limpio[:-3]
        
        # Extraer JSON
        inicio = contenido_limpio.find('{')
        fin = contenido_limpio.rfind('}')
        if inicio != -1 and fin != -1:
            contenido_limpio = contenido_limpio[inicio:fin+1]
        
        resultado = json.loads(contenido_limpio)
        return resultado
        
    except Exception as e:
        logger.error(f"Error estructurando texto con IA: {e}")
        return None
    
def procesar_texto(self, texto: str) -> dict:
    """Procesa texto descriptivo del negocio (sin OCR)"""
    logger.info("=== INICIO procesar_texto ===")
    
    if not ai_client.client:
        logger.error("Cliente de IA no disponible")
        return None
    
    prompt = f"""
    Basado en esta descripción del negocio, extrae la información estructurada.
    
    DESCRIPCIÓN:
    {texto}
    
    IMPORTANTE: Debes devolver SOLO un JSON válido, sin texto adicional, sin markdown, sin explicaciones.
    
    Formato exacto requerido:
    {{
        "productos": [
            {{"nombre": "nombre del producto", "precio": 12345, "descripcion": "descripción", "categoria": "categoría"}}
        ],
        "horario": "horario del negocio",
        "ubicacion": "dirección",
        "politicas": "políticas del negocio",
        "instrucciones_adicionales": "instrucciones para atender"
    }}
    
    Si no encuentras información para algún campo, déjalo como cadena vacía o array vacío.
    """
    
    try:
        logger.info("Llamando a DeepSeek para procesar texto...")
        response = ai_client.client.chat.completions.create(
            model=ai_client.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3
        )
        
        contenido = response.choices[0].message.content
        logger.info(f"Respuesta recibida (longitud: {len(contenido)} caracteres)")
        logger.info(f"Respuesta: {contenido[:500]}...")
        
        # Limpiar la respuesta - eliminar markdown y texto adicional
        contenido_limpio = contenido.strip()
        
        # Eliminar bloques de código markdown
        if contenido_limpio.startswith('```json'):
            contenido_limpio = contenido_limpio[7:]
        elif contenido_limpio.startswith('```'):
            contenido_limpio = contenido_limpio[3:]
        
        if contenido_limpio.endswith('```'):
            contenido_limpio = contenido_limpio[:-3]
        
        contenido_limpio = contenido_limpio.strip()
        
        # Buscar el primer { y el último }
        inicio = contenido_limpio.find('{')
        fin = contenido_limpio.rfind('}')
        if inicio != -1 and fin != -1:
            contenido_limpio = contenido_limpio[inicio:fin+1]
        
        logger.info(f"JSON limpio: {contenido_limpio[:200]}...")
        
        # Intentar parsear JSON
        resultado = json.loads(contenido_limpio)
        
        # Validar que tenga la estructura esperada
        if 'productos' not in resultado:
            resultado['productos'] = []
        if 'horario' not in resultado:
            resultado['horario'] = ''
        if 'ubicacion' not in resultado:
            resultado['ubicacion'] = ''
        if 'politicas' not in resultado:
            resultado['politicas'] = ''
        if 'instrucciones_adicionales' not in resultado:
            resultado['instrucciones_adicionales'] = ''
        
        logger.info(f"Productos encontrados: {len(resultado.get('productos', []))}")
        return resultado
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decodificando JSON: {e}")
        logger.error(f"Contenido que falló: {contenido[:500] if 'contenido' in locals() else 'No hay contenido'}")
        return None
    except Exception as e:
        logger.error(f"Error procesando texto: {e}")
        import traceback
        traceback.print_exc()
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

# Al final del archivo, después de trainer = IATrainer()
def test_trainer():
    """Prueba simple para verificar que el trainer funciona"""
    test_text = "Pizza Margarita 25000, Pizza Pepperoni 32000"
    result = trainer.procesar_texto(test_text)
    return result is not None