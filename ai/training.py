import base64
import io
import json
import re
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from core.logger import logger
from ai.client import ai_client

class IATrainer:
    """Entrenador de IA para cada negocio con soporte OCR mejorado (sin dependencias pesadas)"""
    
    def _preprocesar_imagen(self, image: Image.Image) -> Image.Image:
        """Preprocesa la imagen para mejorar el reconocimiento OCR usando solo PIL"""
        try:
            # 1. Convertir a escala de grises
            if image.mode != 'L':
                image = image.convert('L')
            
            # 2. Redimensionar si es muy pequeña (mejora OCR)
            width, height = image.size
            if width < 800 or height < 600:
                scale = max(1.5, 1200 / width)
                new_width = int(width * scale)
                new_height = int(height * scale)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                logger.info(f"Imagen redimensionada: {width}x{height} -> {new_width}x{new_height}")
            
            # 3. Aumentar contraste
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)
            
            # 4. Aumentar nitidez
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(2.0)
            
            # 5. Aplicar filtro para reducir ruido
            image = image.filter(ImageFilter.MedianFilter())
            
            # 6. Binarización (umbral simple)
            # Convertir a blanco y negro con umbral adaptativo
            image = image.point(lambda x: 0 if x < 128 else 255, '1')
            
            return image
            
        except Exception as e:
            logger.error(f"Error en preprocesamiento: {e}")
            # Fallback: solo escala de grises
            if image.mode != 'L':
                return image.convert('L')
            return image
    
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
            texto_limpio = texto.strip()
            if texto_limpio.startswith('```json'):
                texto_limpio = texto_limpio[7:]
            elif texto_limpio.startswith('```'):
                texto_limpio = texto_limpio[3:]
            if texto_limpio.endswith('```'):
                texto_limpio = texto_limpio[:-3]
            
            inicio = texto_limpio.find('{')
            fin = texto_limpio.rfind('}')
            if inicio != -1 and fin != -1:
                texto_limpio = texto_limpio[inicio:fin+1]
            
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
            precio_limpio = re.sub(r'[^0-9]', '', precio)
            if precio_limpio:
                return int(precio_limpio)
        
        return 0
    
    def procesar_imagen(self, image_base64: str) -> dict:
        """Procesa una imagen de menú usando Tesseract OCR + IA"""
        try:
            image_data = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_data))
            
            logger.info(f"Imagen original: {image.size}, modo: {image.mode}")
            
            # Preprocesar imagen
            processed_image = self._preprocesar_imagen(image)
            
            # Configuración de Tesseract
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789$.,- "'
            
            # Aplicar OCR
            logger.info("Aplicando OCR a la imagen procesada...")
            texto_extraido = pytesseract.image_to_string(processed_image, lang='spa', config=custom_config)
            
            # Limpiar texto
            texto_extraido = self._limpiar_texto_ocr(texto_extraido)
            
            logger.info(f"Texto extraído ({len(texto_extraido)} caracteres)")
            
            if not texto_extraido or len(texto_extraido.strip()) < 10:
                logger.warning("No se pudo extraer texto suficiente de la imagen")
                return None
            
            resultado = self._estructurar_con_ia(texto_extraido)
            return resultado
            
        except Exception as e:
            logger.error(f"Error procesando imagen: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _estructurar_con_ia(self, texto_ocr: str) -> dict:
        """Usa IA para estructurar el texto extraído por OCR"""
        
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
        
        IMPORTANTE: Devuelve SOLO un JSON válido.
        
        Formato exacto:
        {{
            "productos": [
                {{"nombre": "nombre del producto", "precio": 25000, "descripcion": ""}}
            ],
            "horario": "",
            "ubicacion": "",
            "politicas": "",
            "instrucciones_adicionales": ""
        }}
        
        Si no hay productos, devuelve {{"productos": []}}
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
            
            if resultado and 'productos' in resultado:
                productos_validos = []
                for p in resultado['productos']:
                    nombre = p.get('nombre', '')
                    if nombre and isinstance(nombre, str):
                        nombre = re.sub(r'[»«•*+_\-]', '', nombre).strip()
                        if nombre and len(nombre) > 1:
                            p['nombre'] = nombre
                            p['precio'] = self._normalizar_precio(p.get('precio', 0))
                            p['descripcion'] = p.get('descripcion', '')
                            productos_validos.append(p)
                
                resultado['productos'] = productos_validos
                logger.info(f"Productos extraídos: {len(productos_validos)}")
                return resultado
            
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
            resultado = self._extraer_json(contenido)
            
            if resultado:
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