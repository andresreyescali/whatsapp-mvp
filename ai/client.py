from openai import OpenAI
from core.config import config
from core.logger import logger
from ai.vision import vision_client

class DeepSeekClient:
    def __init__(self):
        self.model = config.deepseek_model
        if not config.deepseek_api_key:
            logger.warning('DEEPSEEK_API_KEY no configurada')
            self.client = None
        else:
            self.client = OpenAI(
                api_key=config.deepseek_api_key,
                base_url="https://api.deepseek.com"
            )
            logger.info('Cliente DeepSeek inicializado')

    def analyze_image(self, image_path, prompt=None):
        """Analiza una imagen usando el cliente de visión"""
        return vision_client.analyze_image(image_path, prompt)
    
    def analyze_cake_design(self, image_path):
        """Analiza específicamente un diseño de torta"""
        return vision_client.analyze_design_for_cake(image_path)
    
ai_client = DeepSeekClient()