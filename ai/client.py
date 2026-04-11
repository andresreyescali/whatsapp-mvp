from openai import OpenAI
from core.config import config
from core.logger import logger

class DeepSeekClient:
    def __init__(self):
        if not config.deepseek_api_key:
            logger.warning('DEEPSEEK_API_KEY no configurada')
            self.client = None
        else:
            self.client = OpenAI(
                api_key=config.deepseek_api_key,
                base_url='https://api.deepseek.com'
            )

ai_client = DeepSeekClient()