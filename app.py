from flask import Flask, jsonify, request
from core.config import config
from core.database import db_manager
from core.logger import setup_logging, logger
from whatsapp.webhook import register_webhook_routes
from tenants.onboarding import register_new_tenant

setup_logging()

app = Flask(__name__)
db_manager.init_global_tables()
register_webhook_routes(app)

@app.route('/api/register', methods=['POST'])
def api_register():
    return register_new_tenant()

@app.route('/health')
def health():
    return {'status': 'ok'}

if __name__ == '__main__':
    logger.info(f'Iniciando en puerto {config.port}')
    app.run(host='0.0.0.0', port=config.port)
