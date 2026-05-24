import base64
import io
import json
import re
import logging
import pytesseract
from PIL import Image
import numpy as np
from core.logger import logger
from ai.client import ai_client

# Intentar importar OpenCV para procesamiento avanzado de imágenes
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV (cv2) no está instalado. El procesamiento de imágenes será limitado. Instala con: pip install opencv-python")

class IATrainer:
    """Entrenador de IA para cada negocio con soporte OCR mejorado"""
    
    def _preprocesar_imagen(self, image: Image.Image) -> Image.Image:
        """Preprocesa la imagen para mejorar el reconocimiento OCR"""
        try:
            if not CV2_AVAILABLE:
                # Si no hay OpenCV, solo convertir a escala de grises
                return image.convert('L')
            
            # Convertir PIL a OpenCV
            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            
            # 1. Convertir a escala de grises
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # 2. Redimensionar si es muy pequeña (mejora OCR)
            height, width = gray.shape
            if height < 800 or width < 600:
                scale = max(2, int(1200 / width))
                new_width = int(width * scale)
                new_height = int(height * scale)
                gray = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
                logger.info(f"Imagen redimensionada: {width}x{height} -> {new_width}x{new_height}")
            
            # 3. Aplicar filtro bilateral para reducir ruido sin perder bordes
            denoised = cv2.bilateralFilter(gray, 9, 75, 75)
            
            # 4. Aumentar contraste usando CLAHE
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            contrast = clahe.apply(denoised)
            
            # 5. Binarización adaptativa (mejor para textos con iluminación variable)
            binary = cv2.adaptiveThreshold(contrast, 255, 
                                           cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                           cv2.THRESH_BINARY, 11, 2)
            
            # 6. Opcional: Limpiar ruido pequeño
            kernel = np.ones((1, 1), np.uint8)
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
            
            # Convertir de vuelta a PIL
            return Image.fromarray(binary)
            
        except Exception as e:
            logger.error(f"Error en preprocesamiento: {e}")
            return image.convert('L')  # Fallback a escala de grises simple
    
    def _limpiar_texto_ocr(self, texto: str) -> str:
        """Limpia y normaliza el texto extraído por OCR"""
        if not texto:
            return ""
        
        # Reemplazar caracteres confusos comunes
        correcciones = {
            '5': '$',      # El símbolo $ a menudo se lee como 5
            '5$': '$',     # Caso especial
            'S': '$',      # A veces S se confunde con $
            's': '$',      # s minúscula
            '|': '1',      # Pipe como 1
            'I': '1',      # I mayúscula como 1
            'l': '1',      # l minúscula como 1
            'O': '0',      # O mayúscula como 0
            'o': '0',      # o minúscula como 0
            ',': '.',      # Normalizar decimales
            ';': ',',      # Punto y coma como coma
            '€': '$',      # Euro como dólar
            '£': '$',      # Libra como dólar
        }
        
        for error, correcto in correcciones.items():
            texto = texto.replace(error, correcto)
        
        # Corregir patrones de precio comunes
        # Ej: "25000" vs "25.000" vs "25,000"
        texto = re.sub(r'(\d+)[.,](\d{3})', r'\1\2', texto)      # 25.000 -> 25000
        texto = re.sub(r'(\d+)[.,](\d{2})', r'\1.\2', texto)      # 25.00 -> 25.00
        texto = re.sub(r'\$?(\d+)\$', r'$\1', texto)               # 25000$ -> $25000
        
        # Eliminar caracteres no deseados
        texto = re.sub(r'[»«•*+_=~]', '', texto)
        
        # Normalizar espacios
        texto = re.sub(r'\s+', ' ', texto)
        
        return texto.strip()
    
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
    
    def _normalizar_precio(self, precio) -> int:
        """Normaliza un precio a entero"""
        if precio is None:
            return 0
        
        if isinstance(precio, int):
            return precio
        
        if isinstance(precio, float):
            return int(precio)
        
        if isinstance(precio, str):
            # Limpiar caracteres no numéricos
            precio_limpio = re.sub(r'[^0-9]', '', precio)
            if precio_limpio:
                return int(precio_limpio)
        
        return 0
    
    def procesar_imagen(self, image_base64: str) -> dict:
        """Procesa una imagen de menú usando Tesseract OCR + IA con preprocesamiento mejorado"""
        try:
            # Decodificar imagen
            image_data = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_data))
            
            logger.info(f"Imagen original: {image.size}, modo: {image.mode}")
            
            # Preprocesar imagen
            processed_image = self._preprocesar_imagen(image)
            
            # Configuración de Tesseract para mejor reconocimiento
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789$.,- "'
            
            # Aplicar OCR
            logger.info("Aplicando OCR a la imagen procesada...")
            texto_extraido = pytesseract.image_to_string(processed_image, lang='spa', config=custom_config)
            
            # Limpiar texto extraído
            texto_extraido = self._limpiar_texto_ocr(texto_extraido)
            
            logger.info(f"Texto extraído ({len(texto_extraido)} caracteres)")
            logger.debug(f"Texto OCR: {texto_extraido[:500]}...")
            
            if not texto_extraido or len(texto_extraido.strip()) < 10:
                logger.warning("No se pudo extraer texto suficiente de la imagen")
                return None
            
            # Estructurar con IA
            resultado = self._estructurar_con_ia(texto_extraido)
            return resultado
            
        except Exception as e:
            logger.error(f"Error procesando imagen: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _estructurar_con_ia(self, texto_ocr: str) -> dict:
        """Usa IA para estructurar el texto extraído por OCR con mejor manejo de precios"""
        
        if not ai_client.client:
            logger.error("Cliente de IA no disponible")
            return None
        
        prompt = f"""
        Extrae productos y precios del siguiente texto de menú extraído por OCR.
        
        TEXTO EXTRAÍDO (puede tener errores):
        {texto_ocr[:3000]}
        
        INSTRUCCIONES IMPORTANTES:
        1. El símbolo '$' puede aparecer como '5' o 'S' en el texto OCR. Corrígelo.
        2. Los precios pueden estar en formatos: "25000", "25.000", "25,000" o "$25.000"
        3. Normaliza todos los precios a números sin puntos ni comas (ej: 25000)
        4. Si un precio parece ser por kilo/libra/unidad, incluye esa información en la descripción
        5. Agrupa productos similares cuando sea posible
        6. En una imagen si al inicio del precio aparece el simbolo "$" entonces todos los precios lo tienen, y si alguno no lo tiene entonces o no es un precio o erroneamente lo interpretaste como "5".

        
        IMPORTANTE: Devuelve SOLO un JSON válido. Sin markdown, sin explicaciones.
        
        Formato exacto:
        {{
            "productos": [
                {{"nombre": "nombre del producto", "precio": 25000, "descripcion": "descripción si existe"}},
                {{"nombre": "otro producto", "precio": 15000, "descripcion": ""}}
            ],
            "horario": "horario del negocio si se menciona",
            "ubicacion": "ubicación si se menciona",
            "politicas": "políticas si se mencionan",
            "instrucciones_adicionales": "instrucciones especiales"
        }}
        
        Si no hay productos, devuelve {{"productos": []}}
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.1  # Temperatura más baja para respuestas más consistentes
            )
            
            contenido = response.choices[0].message.content
            logger.info(f"Respuesta DeepSeek recibida ({len(contenido)} chars)")
            
            resultado = self._extraer_json(contenido)
            
            if resultado and 'productos' in resultado:
                productos_validos = []
                for p in resultado['productos']:
                    nombre = p.get('nombre', '')
                    if nombre and isinstance(nombre, str):
                        # Limpiar nombre
                        nombre = re.sub(r'[»«•*+_\-]', '', nombre).strip()
                        if nombre and len(nombre) > 1:
                            p['nombre'] = nombre
                            # Normalizar precio
                            p['precio'] = self._normalizar_precio(p.get('precio', 0))
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
    
    def procesar_texto(self, texto: str) -> dict:
        """Procesa texto descriptivo del negocio"""
        logger.info("=== INICIO procesar_texto ===")
        
        if not ai_client.client:
            logger.error("Cliente de IA no disponible")
            return None
        
        prompt = f"""
        Extrae información de este negocio.
        
        DESCRIPCIÓN:
        {texto[:3000]}
        
        INSTRUCCIONES IMPORTANTES:
        1. Los precios deben ser números enteros (ej: 25000 en lugar de 25.000)
        2. Extrae todos los productos mencionados con sus precios
        3. Si un producto no tiene precio, ignóralo o pon precio 0
        
        IMPORTANTE: Devuelve SOLO un JSON válido.
        
        Formato:
        {{
            "productos": [{{"nombre": "nombre", "precio": 25000, "descripcion": ""}}],
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
                temperature=0.1
            )
            
            contenido = response.choices[0].message.content
            logger.info(f"Respuesta DeepSeek recibida ({len(contenido)} chars)")
            
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
                            p['precio'] = self._normalizar_precio(p.get('precio', 0))
                            p['descripcion'] = p.get('descripcion', '')
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
        {json.dumps(productos[:50], indent=2, ensure_ascii=False)}
        
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