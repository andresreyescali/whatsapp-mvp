import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    database_url: str = os.environ.get("DATABASE_URL", "")
    deepseek_api_key: str = os.environ.get("DEEPSEEK_API_KEY", "")
    deepseek_model: str = "deepseek-chat"
    admin_key: str = os.environ.get("ADMIN_KEY", "")
    port: int = int(os.environ.get("PORT", 10000))

config = Config()