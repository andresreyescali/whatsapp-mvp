import base64
import io
import json
import re
import pytesseract
from PIL import Image
from core.logger import logger
from ai.client import ai_client

class IATrainer:
    """Entrenador de IA para cada negocio con soporte OCR"""
    
    def procesar_imagen(self, image_base64: str) -> dict:
        """Procesa una imagen de menú usando Tesseract OCR + IA"""
        try:
            # Decodificar imagen
            image_data = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_data))
            
            # Aplicar OCR
            logger.info("Aplicando OCR a la imagen...")
            texto_extraido = pytesseract.image_to_string(image, lang='spa')
            
            if not texto_extraido or len(texto_extraido.strip()) < 10:
                logger.warning("No se pudo extraer texto suficiente de la imagen")
                return None
            
            logger.info(f"Texto extraído ({len(texto_extraido)} caracteres)")
            
            # Estructurar con IA
            resultado = self._estructurar_con_ia(texto_extraido)
            return resultado
            
        except Exception as e:
            logger.error(f"Error procesando imagen: {e}")
            return None
    
    def _estructurar_con_ia(self, texto_ocr: str) -> dict:
        """Usa IA para estructurar el texto extraído por OCR"""
        logger.info("=== INICIO _estructurar_con_ia ===")
        
        if not ai_client.client:
            logger.error("Cliente de IA no disponible")
            return None
        
        # Limitar texto para evitar tokens excesivos
        texto_limitado = texto_ocr[:2000]
        
        prompt = f"""
        Extrae productos del siguiente texto de menú.
        
        TEXTO:
        {texto_limitado}
        
        IMPORTANTE: Devuelve SOLO un JSON válido. Sin markdown, sin explicaciones.
        
        Formato exacto:
        {{"productos": [{{"nombre": "nombre", "precio": 12345, "descripcion": ""}}]}}
        
        Si no hay productos, devuelve {{"productos": []}}
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.2
            )
            
            contenido = response.choices[0].message.content
            logger.info(f"Respuesta DeepSeek recibida ({len(contenido)} chars)")
            
            # Extraer JSON
            resultado = self._extraer_json(contenido)
            
            if resultado and 'productos' in resultado:
                # Limpiar productos
                productos_validos = []
                for p in resultado['productos']:
                    nombre = p.get('nombre', '')
                    if nombre and isinstance(nombre, str):
                        nombre = re.sub(r'[»«•*+_\-]', '', nombre).strip()
                        if nombre and len(nombre) > 1:
                            p['nombre'] = nombre
                            p['precio'] = p.get('precio', 0)
                            p['descripcion'] = p.get('descripcion', '')
                            productos_validos.append(p)
                resultado['productos'] = productos_validos
                logger.info(f"Productos extraídos: {len(productos_validos)}")
                return resultado
            
            logger.warning("No se pudo extraer JSON válido")
            return {'productos': []}
            
        except Exception as e:
            logger.error(f"Error en _estructurar_con_ia: {e}")
            return {'productos': []}
    
    def _extraer_json(self, texto: str) -> dict:
        """Extrae y parsea JSON de una respuesta de IA"""
        try:
            # Limpiar markdown
            texto_limpio = texto.strip()
            if texto_limpio.startswith('```json'):
                texto_limpio = texto_limpio[7:]
            elif texto_limpio.startswith('```'):
                texto_limpio = texto_limpio[3:]
            if texto_limpio.endswith('```'):
                texto_limpio = texto_limpio[:-3]
            
            # Buscar JSON
            inicio = texto_limpio.find('{')
            fin = texto_limpio.rfind('}')
            if inicio != -1 and fin != -1:
                texto_limpio = texto_limpio[inicio:fin+1]
            
            # Limpiar caracteres problemáticos
            texto_limpio = re.sub(r',\s*}', '}', texto_limpio)
            texto_limpio = re.sub(r',\s*]', ']', texto_limpio)
            
            return json.loads(texto_limpio)
        except json.JSONDecodeError as e:
            logger.error(f"Error JSON: {e}")
            return None
    
    def procesar_texto(self, texto: str) -> dict:
        """Procesa texto descriptivo del negocio"""
        logger.info("=== INICIO procesar_texto ===")
        
        if not ai_client.client:
            logger.error("Cliente de IA no disponible")
            return None
        
        prompt = f"""
        Extrae información de este negocio.
        
        DESCRIPCIÓN:
        {texto[:2000]}
        
        IMPORTANTE: Devuelve SOLO un JSON válido.
        
        Formato:
        {{
            "productos": [{{"nombre": "nombre", "precio": 12345, "descripcion": ""}}],
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
                max_tokens=1500,
                temperature=0.2
            )
            
            contenido = response.choices[0].message.content
            resultado = self._extraer_json(contenido)
            
            if resultado:
                # Asegurar estructura
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
                
                # Limpiar productos
                productos_validos = []
                for p in resultado.get('productos', []):
                    nombre = p.get('nombre', '')
                    if nombre and isinstance(nombre, str):
                        nombre = re.sub(r'[»«•*+_\-]', '', nombre).strip()
                        if nombre and len(nombre) > 1:
                            p['nombre'] = nombre
                            productos_validos.append(p)
                resultado['productos'] = productos_validos
                
                logger.info(f"Productos encontrados: {len(productos_validos)}")
                return resultado
            
            return {'productos': []}
            
        except Exception as e:
            logger.error(f"Error procesando texto: {e}")
            return {'productos': []}
    
    def generar_prompt_personalizado(self, contexto: dict) -> str:
        """Genera prompt personalizado para el asistente"""
        productos = contexto.get('productos', [])
        horario = contexto.get('horario', '')
        ubicacion = contexto.get('ubicacion', '')
        politicas = contexto.get('politicas', '')
        
        prompt = f"""
        Eres un asistente de ventas por WhatsApp.
        
        PRODUCTOS:
        {json.dumps(productos[:30], indent=2)}
        
        HORARIO: {horario}
        UBICACION: {ubicacion}
        POLITICAS: {politicas}
        
        Reglas:
        1. Sé amable y conversacional
        2. Confirma pedidos antes de generar pago
        3. Ofrece productos complementarios
        
        Responde en español, de forma breve.
        """
        
        return prompt.strip()

# Instancia global
trainer = IATrainer()