import base64
import io
import json
import re
import uuid
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from core.logger import logger
from ai.client import ai_client
from core.database import db_manager


class IATrainer:
    """Entrenador de IA que guarda productos y precios en la base de datos"""
    
    def __init__(self):
        pass
    
    def _get_schema_name(self, tenant_id: str) -> str:
        """Obtiene el schema_name del tenant"""
        from tenants.repository import tenant_repo
        tenant = tenant_repo.find_by_id(tenant_id)
        if tenant and tenant.get('schema_name'):
            return tenant['schema_name']
        return f"tenant_{tenant_id.replace('-', '_')}"
    
    def _preprocesar_imagen(self, image: Image.Image) -> Image.Image:
        """Preprocesa la imagen para mejorar el reconocimiento OCR"""
        try:
            if image.mode != 'L':
                image = image.convert('L')
            
            width, height = image.size
            if width < 800 or height < 600:
                scale = max(1.5, 1200 / width)
                new_width = int(width * scale)
                new_height = int(height * scale)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)
            
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(2.0)
            
            image = image.filter(ImageFilter.MedianFilter())
            image = image.point(lambda x: 0 if x < 128 else 255, '1')
            
            return image
        except Exception as e:
            logger.error(f"Error en preprocesamiento: {e}")
            if image.mode != 'L':
                return image.convert('L')
            return image
    
    def _limpiar_texto_ocr(self, texto: str) -> str:
        """Limpia y normaliza el texto extraído por OCR"""
        if not texto:
            return ""
        
        correcciones = {
            '5': '$', 'S': '$', 's': '$', '|': '1', 'I': '1',
            'l': '1', 'O': '0', 'o': '0', ',': '.', ';': ',',
            '€': '$', '£': '$'
        }
        
        for error, correcto in correcciones.items():
            texto = texto.replace(error, correcto)
        
        texto = re.sub(r'(\d+)[.,](\d{3})', r'\1\2', texto)
        texto = re.sub(r'(\d+)[.,](\d{2})', r'\1.\2', texto)
        texto = re.sub(r'\$?(\d+)\$', r'$\1', texto)
        texto = re.sub(r'[»«•*+_=~]', '', texto)
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
    
    def _guardar_productos_en_bd(self, tenant_id: str, productos: list) -> int:
        """Guarda los productos extraídos en la base de datos del tenant"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            guardados = 0
            actualizados = 0
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    for producto in productos:
                        nombre = producto.get('nombre', '').strip()
                        precio = producto.get('precio', 0)
                        categoria = producto.get('categoria', 'general')
                        descripcion = producto.get('descripcion', '')
                        es_base = producto.get('es_base', True)
                        destacado = producto.get('destacado', False)
                        tiempo_preparacion = producto.get('tiempo_preparacion')
                        
                        if not nombre or precio <= 0:
                            continue
                        
                        # Verificar si ya existe
                        cur.execute(f'SELECT id, precio, nombre FROM "{schema_name}".productos WHERE nombre ILIKE %s', (nombre,))
                        existing = cur.fetchone()
                        
                        if existing:
                            existing_precio = existing[1]
                            if existing_precio != precio:
                                cur.execute(f"""
                                    UPDATE "{schema_name}".productos 
                                    SET precio = %s, descripcion = %s, categoria = %s, 
                                        updated_at = NOW()
                                    WHERE id = %s
                                """, (precio, descripcion, categoria, existing[0]))
                                actualizados += 1
                                logger.info(f"🔄 [BD] Actualizado: '{nombre}' ${existing_precio} → ${precio}")
                            else:
                                logger.debug(f"⏭️ [BD] Sin cambios: '{nombre}'")
                        else:
                            # Insertar nuevo producto
                            product_id = str(uuid.uuid4())
                            cur.execute(f"""
                                INSERT INTO "{schema_name}".productos 
                                (id, nombre, descripcion, precio, categoria, disponible, 
                                 es_base, destacado, tiempo_preparacion, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, true, %s, %s, %s, NOW(), NOW())
                            """, (product_id, nombre, descripcion, precio, categoria, 
                                  es_base, destacado, tiempo_preparacion))
                            guardados += 1
                            logger.info(f"➕ [BD] Nuevo producto: '{nombre}' - ${precio}")
                    
                    conn.commit()
            
            logger.info(f"✅ [BD] Productos: {guardados} nuevos, {actualizados} actualizados")
            return guardados
            
        except Exception as e:
            logger.error(f"Error guardando productos: {e}")
            return 0
    
    def _guardar_contexto_en_bd(self, tenant_id: str, contexto: dict):
        """Guarda el contexto (horario, ubicación, políticas) en la base de datos"""
        try:
            instrucciones = contexto.get('instrucciones_adicionales', '')
            politicas = contexto.get('politicas', '')
            horario = contexto.get('horario', '')
            ubicacion = contexto.get('ubicacion', '')
            
            if not any([instrucciones, politicas, horario, ubicacion]):
                return
            
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        INSERT INTO public.tenant_context 
                        (tenant_id, instrucciones, politicas, horario, ubicacion, updated_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (tenant_id) DO UPDATE SET
                            instrucciones = EXCLUDED.instrucciones,
                            politicas = EXCLUDED.politicas,
                            horario = EXCLUDED.horario,
                            ubicacion = EXCLUDED.ubicacion,
                            updated_at = NOW()
                    ''', (tenant_id, instrucciones, politicas, horario, ubicacion))
                    conn.commit()
                    
            logger.info(f"✅ [BD] Contexto guardado para tenant {tenant_id}")
            
        except Exception as e:
            logger.error(f"Error guardando contexto: {e}")
    
    def procesar_imagen(self, tenant_id: str, image_base64: str) -> dict:
        """Procesa una imagen de menú y guarda los productos en BD"""
        try:
            image_data = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_data))
            
            logger.info(f"📸 [OCR] Procesando imagen: {image.size}")
            
            # Preprocesar imagen
            processed_image = self._preprocesar_imagen(image)
            
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789$.,- "'
            
            texto_extraido = pytesseract.image_to_string(processed_image, lang='spa', config=custom_config)
            texto_extraido = self._limpiar_texto_ocr(texto_extraido)
            
            logger.info(f"📝 [OCR] Texto extraído: {len(texto_extraido)} caracteres")
            
            if not texto_extraido or len(texto_extraido.strip()) < 10:
                logger.warning("No se pudo extraer texto suficiente")
                return {'productos': [], 'error': 'No se pudo extraer texto de la imagen'}
            
            resultado = self._estructurar_con_ia(texto_extraido)
            
            if resultado and resultado.get('productos'):
                guardados = self._guardar_productos_en_bd(tenant_id, resultado['productos'])
                self._guardar_contexto_en_bd(tenant_id, resultado)
                resultado['productos_guardados'] = guardados
                resultado['message'] = f"✅ Se agregaron {guardados} nuevos productos"
            
            return resultado
            
        except Exception as e:
            logger.error(f"Error procesando imagen: {e}")
            import traceback
            traceback.print_exc()
            return {'productos': [], 'error': str(e)}
    
    def _estructurar_con_ia(self, texto_ocr: str) -> dict:
        """Usa IA para estructurar el texto extraído por OCR"""
        if not ai_client.client:
            logger.error("Cliente de IA no disponible")
            return None
        
        prompt = f"""
        Extrae productos y precios del siguiente texto de menú.
        
        TEXTO EXTRAÍDO:
        {texto_ocr[:3000]}
        
        IMPORTANTE: Devuelve SOLO un JSON válido.
        
        Formato exacto:
        {{
            "productos": [
                {{"nombre": "nombre del producto", "precio": 25000, "categoria": "tortas", "descripcion": ""}}
            ],
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
            
            if resultado and 'productos' in resultado:
                productos_validos = []
                for p in resultado['productos']:
                    nombre = p.get('nombre', '').strip()
                    if nombre and len(nombre) > 1:
                        p['nombre'] = re.sub(r'[»«•*+_\-]', '', nombre).strip()
                        p['precio'] = self._normalizar_precio(p.get('precio', 0))
                        p['categoria'] = p.get('categoria', 'general')
                        p['descripcion'] = p.get('descripcion', '')
                        p['es_base'] = True
                        if p['precio'] > 0:
                            productos_validos.append(p)
                
                resultado['productos'] = productos_validos
                logger.info(f"📊 [IA] Productos extraídos: {len(productos_validos)}")
                return resultado
            
            return {'productos': []}
            
        except Exception as e:
            logger.error(f"Error en _estructurar_con_ia: {e}")
            return {'productos': []}
    
    def procesar_texto(self, tenant_id: str, texto: str) -> dict:
        """Procesa texto descriptivo y guarda los productos en BD"""
        logger.info(f"📝 [TEXTO] Procesando texto para tenant {tenant_id}")
        
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
            "productos": [
                {{"nombre": "nombre", "precio": 25000, "categoria": "tortas", "descripcion": ""}}
            ],
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
                # Asegurar campos
                resultado.setdefault('productos', [])
                resultado.setdefault('horario', '')
                resultado.setdefault('ubicacion', '')
                resultado.setdefault('politicas', '')
                resultado.setdefault('instrucciones_adicionales', '')
                
                productos_validos = []
                for p in resultado.get('productos', []):
                    nombre = p.get('nombre', '').strip()
                    if nombre and len(nombre) > 1:
                        p['nombre'] = re.sub(r'[»«•*+_\-]', '', nombre).strip()
                        p['precio'] = self._normalizar_precio(p.get('precio', 0))
                        p['categoria'] = p.get('categoria', 'general')
                        p['es_base'] = True
                        if p['precio'] > 0:
                            productos_validos.append(p)
                
                resultado['productos'] = productos_validos
                
                # Guardar en BD
                guardados = self._guardar_productos_en_bd(tenant_id, productos_validos)
                self._guardar_contexto_en_bd(tenant_id, resultado)
                
                logger.info(f"📊 [IA] Productos extraídos: {len(productos_validos)}, guardados: {guardados}")
                
                resultado['productos_guardados'] = guardados
                resultado['message'] = f"✅ Se agregaron {guardados} nuevos productos"
                
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
        Eres un asistente de ventas por WhatsApp para una pastelería.
        
        PRODUCTOS (con precios):
        {json.dumps(productos[:50], indent=2, ensure_ascii=False)}
        
        HORARIO: {horario}
        UBICACION: {ubicacion}
        POLITICAS: {politicas}
        
        REGLAS IMPORTANTES:
        1. NO uses menús numéricos. Responde de forma natural y conversacional.
        2. Cuando el cliente pida un producto, usa el precio de la lista.
        3. Confirma el pedido antes de finalizar.
        4. Sé amable y cálido.
        
        Responde en español, de forma breve.
        """
        
        return prompt.strip()


# Instancia global
trainer = IATrainer()