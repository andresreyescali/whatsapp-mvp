import os
import base64
import requests
from core.logger import logger
from core.config import config

class VisionClient:
    """Cliente para análisis de imágenes usando DeepSeek-VL o GPT-4 Vision"""
    
    def __init__(self):
        self.api_key = config.deepseek_api_key
        self.base_url = "https://api.deepseek.com"
        
    def encode_image(self, image_path):
        """Convierte una imagen a base64"""
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error codificando imagen: {e}")
            return None
    
    def encode_image_from_bytes(self, image_bytes):
        """Convierte bytes de imagen a base64"""
        try:
            return base64.b64encode(image_bytes).decode('utf-8')
        except Exception as e:
            logger.error(f"Error codificando imagen desde bytes: {e}")
            return None
    
    def analyze_image(self, image_path, prompt=None):
        """
        Analiza una imagen usando DeepSeek-VL
        
        Args:
            image_path: Ruta de la imagen
            prompt: Pregunta específica sobre la imagen
        """
        try:
            if not self.api_key:
                logger.warning("API key no configurada para visión")
                return None
            
            base64_image = self.encode_image(image_path)
            if not base64_image:
                return None
            
            # Prompt genérico que funciona para cualquier negocio
            default_prompt = """Analiza esta imagen y describe:
1. Qué tipo de objeto/producto se muestra
2. Características principales (colores, forma, tamaño aparente)
3. Detalles notables que puedan ser relevantes
4. Si es un documento/factura, extrae los datos principales
5. Si es una ubicación/propiedad, describe lo que ves
6. Si es un producto, describe sus características

Sé conciso pero descriptivo. Responde en español."""
            
            final_prompt = prompt or default_prompt
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "deepseek-vl",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": final_prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 500,
                "temperature": 0.7
            }
            
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload
            )
            
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                logger.error(f"Error en análisis de imagen: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error en analyze_image: {e}")
            return None
    
    def analyze_with_business_context(self, image_path, business_type, additional_context=None):
        """
        Analiza una imagen con contexto específico del negocio
        
        Args:
            image_path: Ruta de la imagen
            business_type: Tipo de negocio (restaurante, inmobiliaria, etc.)
            additional_context: Información adicional del negocio
        """
        context_text = additional_context if additional_context else ""
        
        prompt = f"""Eres un asistente de ventas para un negocio de tipo '{business_type}'.

{context_text}

Analiza esta imagen que un cliente envió como referencia y responde:

1. QUÉ ES: Describe brevemente lo que se muestra en la imagen
2. CARACTERÍSTICAS: Puntos clave que sean relevantes para este tipo de negocio
3. COTIZACIÓN: Si aplica, sugiere cómo podríamos ofrecer un producto similar
4. PREGUNTA: Formula una pregunta al cliente para obtener más detalles

Responde en español, de manera amable y profesional."""
        
        return self.analyze_image(image_path, prompt)
    
    def extract_information(self, image_path, info_type):
        """
        Extrae información específica de una imagen
        
        Args:
            image_path: Ruta de la imagen
            info_type: 'product', 'document', 'location', 'design', 'general'
        """
        prompts = {
            'product': """Analiza esta imagen de un producto y extrae:
- Tipo de producto
- Color/es principal/es
- Tamaño aparente
- Material/Textura
- Estado (nuevo, usado, etc.)
- Cualquier texto visible (marca, etiqueta)
Responde en español, en formato lista.""",
            
            'document': """Analiza este documento/imagen y extrae:
- Tipo de documento (factura, contrato, recibo, etc.)
- Fechas visibles
- Montos o números importantes
- Nombres de personas o empresas
- Cualquier otro dato relevante
Responde en español, en formato claro.""",
            
            'location': """Analiza esta imagen de una ubicación/propiedad y describe:
- Tipo de espacio (casa, apartamento, local, terreno, etc.)
- Estado general
- Características notables
- Tamaño aparente
- Si hay mobiliario o elementos adicionales
Responde en español, de forma descriptiva.""",
            
            'design': """Analiza esta imagen de diseño/referencia y describe:
- Estilo general
- Colores principales
- Patrones o elementos decorativos
- Lo que podría destacar para un cliente
Responde en español, de forma atractiva.""",
            
            'general': """Describe esta imagen en 3-4 líneas, destacando:
- Lo más importante que un vendedor debería saber
- Posibles preguntas para hacerle al cliente
Responde en español."""
        }
        
        selected_prompt = prompts.get(info_type, prompts['general'])
        return self.analyze_image(image_path, selected_prompt)
    
    def compare_with_catalog(self, image_path, catalog_items):
        """
        Compara la imagen del cliente con productos del catálogo
        
        Args:
            image_path: Ruta de la imagen
            catalog_items: Lista de productos disponibles
        """
        catalog_text = ""
        for item in catalog_items[:20]:
            nombre = item.get('nombre', '')
            descripcion = item.get('descripcion', '')
            catalog_text += f"- {nombre}: {descripcion}\n"
        
        prompt = f"""Cliente envió una imagen de referencia. Compárala con nuestro catálogo:

CATÁLOGO DISPONIBLE:
{catalog_text}

Analiza la imagen del cliente y responde:
1. ¿Hay algún producto en nuestro catálogo similar?
2. ¿Qué producto recomendarías y por qué?
3. ¿Qué diferencias notas entre lo que pide el cliente y lo que tenemos?
4. Sugiere una respuesta para el cliente

Responde en español."""
        
        return self.analyze_image(image_path, prompt)


# Instancia global
vision_client = VisionClient()