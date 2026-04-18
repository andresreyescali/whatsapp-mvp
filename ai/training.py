import base64
import requests
from core.logger import logger
from ai.client import ai_client
import json

class IATrainer:
    """Entrenador de IA para cada negocio"""
    
    def procesar_imagen(self, image_base64: str) -> dict:
        """Procesa una imagen de menú usando IA (OCR + extracción)"""
        
        prompt = """
        Eres un experto en extraer información de menús de restaurantes.
        
        Analiza esta imagen de menú y extrae:
        1. Lista de productos con: nombre, precio, descripción, categoría
        2. Horario del negocio
        3. Ubicación/dirección
        4. Políticas especiales (mínimo de pedido, tiempo de entrega, etc.)
        
        Devuelve SOLO un JSON válido con esta estructura:
        {
            "productos": [{"nombre": "", "precio": 0, "descripcion": "", "categoria": ""}],
            "horario": "",
            "ubicacion": "",
            "politicas": "",
            "instrucciones_adicionales": ""
        }
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Extrae la información de este menú:"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]}
                ],
                max_tokens=2000
            )
            
            resultado = json.loads(response.choices[0].message.content)
            return resultado
            
        except Exception as e:
            logger.error(f"Error procesando imagen: {e}")
            return None
    
    def procesar_texto(self, texto: str) -> dict:
        """Procesa texto descriptivo del negocio"""
        
        prompt = f"""
        Eres un experto en configurar asistentes de ventas.
        
        Basado en esta descripción del negocio, extrae:
        1. Productos (si menciona alguno)
        2. Horario
        3. Ubicación
        4. Políticas
        5. Instrucciones para atender clientes
        
        DESCRIPCIÓN:
        {texto}
        
        Devuelve SOLO un JSON válido con esta estructura:
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
                max_tokens=2000
            )
            
            resultado = json.loads(response.choices[0].message.content)
            return resultado
            
        except Exception as e:
            logger.error(f"Error procesando texto: {e}")
            return None
    
    def generar_prompt_personalizado(self, contexto: dict) -> str:
        """Genera un prompt personalizado para el asistente basado en el contexto"""
        
        prompt = f"""
        Eres un asistente de ventas para un negocio con estas características:
        
        PRODUCTOS:
        {json.dumps(contexto.get('productos', []), indent=2)}
        
        HORARIO: {contexto.get('horario', 'No especificado')}
        UBICACIÓN: {contexto.get('ubicacion', 'No especificada')}
        POLÍTICAS: {contexto.get('politicas', 'No especificadas')}
        INSTRUCCIONES: {contexto.get('instrucciones_adicionales', '')}
        
        Genera un prompt de sistema personalizado para que el asistente:
        1. Conozca todos los productos y precios
        2. Sepa el horario y ubicación
        3. Siga las políticas del negocio
        4. Sea amable y eficiente
        5. Ayude al cliente a hacer pedidos
        
        El prompt debe ser breve pero completo.
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error generando prompt: {e}")
            return None

trainer = IATrainer()