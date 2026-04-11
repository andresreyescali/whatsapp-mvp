# generar_estructura.ps1 - Versión corregida
Write-Host "🚀 Generando estructura modular..." -ForegroundColor Green

# Crear carpetas
$folders = @("core", "tenants", "ai", "orders", "whatsapp", "web", "admin", "utils", "web\templates")
foreach ($folder in $folders) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    Write-Host "  ✓ Creada: $folder" -ForegroundColor Cyan
}

# Función para crear archivos
function Create-File {
    param($Path, $Lines)
    $Content = $Lines -join "`r`n"
    Set-Content -Path $Path -Value $Content -Encoding UTF8
    Write-Host "  ✓ Creado: $Path" -ForegroundColor Green
}

# ==================== CORE ====================
Create-File "core\__init__.py" @(
    "# Core module"
)

Create-File "core\config.py" @(
    "import os",
    "from dataclasses import dataclass",
    "from dotenv import load_dotenv",
    "",
    "load_dotenv()",
    "",
    "@dataclass",
    "class Config:",
    "    database_url: str = os.environ.get('DATABASE_URL', '')",
    "    deepseek_api_key: str = os.environ.get('DEEPSEEK_API_KEY', '')",
    "    deepseek_model: str = 'deepseek-chat'",
    "    admin_key: str = os.environ.get('ADMIN_KEY', '')",
    "    port: int = int(os.environ.get('PORT', 10000))",
    "",
    "config = Config()"
)

Create-File "core\logger.py" @(
    "import logging",
    "import sys",
    "",
    "def setup_logging():",
    "    logging.basicConfig(",
    "        level=logging.INFO,",
    "        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',",
    "        handlers=[logging.StreamHandler(sys.stdout)]",
    "    )",
    "",
    "def get_logger(name: str):",
    "    return logging.getLogger(name)",
    "",
    "logger = get_logger('whatsapp-saas')"
)

Create-File "core\database.py" @(
    "import psycopg",
    "from psycopg.rows import dict_row",
    "from core.config import config",
    "from core.logger import logger",
    "",
    "class DatabaseManager:",
    "    def __init__(self):",
    "        self._base_conn = None",
    "        self._tenant_connections = {}",
    "    ",
    "    def get_connection(self, tenant_id: str = None):",
    "        if tenant_id:",
    "            if tenant_id not in self._tenant_connections:",
    "                logger.info(f'Creando conexion para tenant: {tenant_id}')",
    "                conn = psycopg.connect(config.database_url)",
    "                with conn.cursor() as cur:",
    "                    cur.execute(f'SET search_path TO {tenant_id}, public')",
    "                self._tenant_connections[tenant_id] = conn",
    "            return self._tenant_connections[tenant_id]",
    "        else:",
    "            if not self._base_conn:",
    "                self._base_conn = psycopg.connect(config.database_url)",
    "            return self._base_conn",
    "    ",
    "    def init_global_tables(self):",
    "        logger.info('Inicializando tablas globales...')",
    "        with self.get_connection() as conn:",
    "            with conn.cursor() as cur:",
    "                cur.execute('''",
    "                CREATE TABLE IF NOT EXISTS public.tenants (",
    "                    id TEXT PRIMARY KEY,",
    "                    nombre TEXT NOT NULL,",
    "                    tipo_negocio TEXT,",
    "                    schema_name TEXT UNIQUE NOT NULL,",
    "                    phone_id TEXT,",
    "                    token TEXT,",
    "                    usar_ia BOOLEAN DEFAULT false,",
    "                    configuracion JSONB DEFAULT '{}',",
    "                    created_at TIMESTAMP DEFAULT NOW(),",
    "                    activo BOOLEAN DEFAULT true",
    "                );",
    "                ''')",
    "                cur.execute('''",
    "                CREATE TABLE IF NOT EXISTS public.metricas_tenants (",
    "                    id SERIAL PRIMARY KEY,",
    "                    tenant_id TEXT,",
    "                    fecha DATE DEFAULT CURRENT_DATE,",
    "                    mensajes INTEGER DEFAULT 0,",
    "                    pedidos INTEGER DEFAULT 0,",
    "                    costo_ia DECIMAL(10,4) DEFAULT 0",
    "                );",
    "                ''')",
    "            conn.commit()",
    "        logger.info('Tablas globales listas')",
    "",
    "db_manager = DatabaseManager()"
)

# ==================== TENANTS ====================
Create-File "tenants\__init__.py" @(
    "# Tenants module"
)

Create-File "tenants\models.py" @(
    "from dataclasses import dataclass",
    "from typing import Dict, Optional",
    "from datetime import datetime",
    "",
    "@dataclass",
    "class Tenant:",
    "    id: str",
    "    nombre: str",
    "    phone_id: str",
    "    token: str",
    "    tipo_negocio: str = 'restaurante'",
    "    usar_ia: bool = False",
    "    configuracion: Dict = None",
    "    created_at: Optional[datetime] = None",
    "    activo: bool = True",
    "    ",
    "    @classmethod",
    "    def from_db_row(cls, row: dict):",
    "        return cls(",
    "            id=row['id'],",
    "            nombre=row['nombre'],",
    "            phone_id=row['phone_id'],",
    "            token=row['token'],",
    "            tipo_negocio=row.get('tipo_negocio', 'restaurante'),",
    "            usar_ia=row.get('usar_ia', False),",
    "            configuracion=row.get('configuracion', {}),",
    "            created_at=row.get('created_at'),",
    "            activo=row.get('activo', True)",
    "        )"
)

Create-File "tenants\repository.py" @(
    "import uuid",
    "from core.database import db_manager",
    "from tenants.models import Tenant",
    "",
    "class TenantRepository:",
    "    def find_by_phone_id(self, phone_id: str):",
    "        with db_manager.get_connection() as conn:",
    "            with conn.cursor(row_factory=dict_row) as cur:",
    "                cur.execute(",
    "                    'SELECT * FROM public.tenants WHERE phone_id = %s AND activo = true',",
    "                    (phone_id,)",
    "                )",
    "                row = cur.fetchone()",
    "                return Tenant.from_db_row(row) if row else None",
    "    ",
    "    def create(self, nombre: str, phone_id: str, token: str, tipo_negocio: str = 'restaurante'):",
    "        tenant_id = f'tenant_{uuid.uuid4().hex[:8]}'",
    "        with db_manager.get_connection() as conn:",
    "            with conn.cursor() as cur:",
    "                cur.execute('''",
    "                    INSERT INTO public.tenants (id, nombre, tipo_negocio, schema_name, phone_id, token)",
    "                    VALUES (%s, %s, %s, %s, %s, %s)",
    "                ''', (tenant_id, nombre, tipo_negocio, tenant_id, phone_id, token))",
    "            conn.commit()",
    "        return Tenant(id=tenant_id, nombre=nombre, phone_id=phone_id, token=token, tipo_negocio=tipo_negocio)",
    "    ",
    "    def update_ia_config(self, tenant_id: str, usar_ia: bool):",
    "        with db_manager.get_connection() as conn:",
    "            with conn.cursor() as cur:",
    "                cur.execute('UPDATE public.tenants SET usar_ia = %s WHERE id = %s', (usar_ia, tenant_id))",
    "            conn.commit()",
    "",
    "tenant_repo = TenantRepository()"
)

Create-File "tenants\schema_manager.py" @(
    "from core.database import db_manager",
    "",
    "class SchemaManager:",
    "    def create_tenant_schema(self, tenant_id: str, tipo_negocio: str):",
    "        with db_manager.get_connection() as conn:",
    "            with conn.cursor() as cur:",
    "                cur.execute(f'CREATE SCHEMA IF NOT EXISTS {tenant_id}')",
    "                cur.execute(f'''",
    "                CREATE TABLE IF NOT EXISTS {tenant_id}.productos (",
    "                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),",
    "                    nombre TEXT NOT NULL,",
    "                    descripcion TEXT,",
    "                    precio INTEGER NOT NULL,",
    "                    categoria TEXT,",
    "                    disponible BOOLEAN DEFAULT true",
    "                )",
    "                ''')",
    "                cur.execute(f'''",
    "                CREATE TABLE IF NOT EXISTS {tenant_id}.pedidos (",
    "                    id TEXT PRIMARY KEY,",
    "                    cliente_numero TEXT,",
    "                    items JSONB,",
    "                    total INTEGER,",
    "                    estado TEXT DEFAULT 'pendiente_pago',",
    "                    created_at TIMESTAMP DEFAULT NOW()",
    "                )",
    "                ''')",
    "            conn.commit()",
    "    ",
    "    def get_menu(self, tenant_id: str):",
    "        with db_manager.get_connection(tenant_id) as conn:",
    "            with conn.cursor(row_factory=dict_row) as cur:",
    "                cur.execute(f'SELECT * FROM {tenant_id}.productos WHERE disponible = true')",
    "                return cur.fetchall()",
    "",
    "schema_manager = SchemaManager()"
)

Create-File "tenants\onboarding.py" @(
    "from flask import request, jsonify",
    "from tenants.repository import tenant_repo",
    "from tenants.schema_manager import schema_manager",
    "",
    "def register_new_tenant():",
    "    data = request.json",
    "    required = ['nombre', 'phone_id', 'token']",
    "    if not all(k in data for k in required):",
    "        return jsonify({'error': 'Faltan campos'}), 400",
    "    ",
    "    tenant = tenant_repo.create(",
    "        nombre=data['nombre'],",
    "        phone_id=data['phone_id'],",
    "        token=data['token'],",
    "        tipo_negocio=data.get('tipo_negocio', 'restaurante')",
    "    )",
    "    schema_manager.create_tenant_schema(tenant.id, tenant.tipo_negocio)",
    "    return jsonify({'status': 'ok', 'tenant_id': tenant.id}), 201"
)

# ==================== AI ====================
Create-File "ai\__init__.py" @(
    "# AI module"
)

Create-File "ai\client.py" @(
    "from openai import OpenAI",
    "from core.config import config",
    "from core.logger import logger",
    "",
    "class DeepSeekClient:",
    "    def __init__(self):",
    "        if not config.deepseek_api_key:",
    "            logger.warning('DEEPSEEK_API_KEY no configurada')",
    "            self.client = None",
    "        else:",
    "            self.client = OpenAI(",
    "                api_key=config.deepseek_api_key,",
    "                base_url='https://api.deepseek.com'",
    "            )",
    "    ",
    "    def chat(self, messages: list, temperature: float = 0.7, max_tokens: int = 300):",
    "        if not self.client:",
    "            return None",
    "        try:",
    "            response = self.client.chat.completions.create(",
    "                model=config.deepseek_model,",
    "                messages=messages,",
    "                temperature=temperature,",
    "                max_tokens=max_tokens",
    "            )",
    "            return response.choices[0].message.content",
    "        except Exception as e:",
    "            logger.error(f'Error en DeepSeek: {e}')",
    "            return None",
    "",
    "ai_client = DeepSeekClient()"
)

Create-File "ai\prompts.py" @(
    "class PromptBuilder:",
    "    @staticmethod",
    "    def build_response_prompt(texto: str, tenant, menu: list) -> list:",
    "        menu_texto = '\\n'.join([f'- {p[\"nombre\"]}: ${p[\"precio\"]}' for p in menu[:20]])",
    "        system_prompt = f'''",
    "Eres un asistente de ventas para {tenant.nombre}.",
    "",
    "Menu:",
    "{menu_texto}",
    "",
    "Responde de forma amable y breve.",
    "'''",
    "        return [",
    "            {'role': 'system', 'content': system_prompt},",
    "            {'role': 'user', 'content': texto}",
    "        ]"
)

Create-File "ai\cache.py" @(
    "class PromptCache:",
    "    def __init__(self):",
    "        self._cache = {}",
    "    ",
    "    def invalidate(self, tenant_id: str):",
    "        keys_to_delete = [k for k in self._cache if k.startswith(tenant_id)]",
    "        for k in keys_to_delete:",
    "            del self._cache[k]",
    "",
    "prompt_cache = PromptCache()"
)

# ==================== ORDERS ====================
Create-File "orders\__init__.py" @(
    "# Orders module"
)

Create-File "orders\repository.py" @(
    "import uuid",
    "import json",
    "from core.database import db_manager",
    "",
    "class OrderRepository:",
    "    def create(self, tenant_id: str, cliente_numero: str, producto_nombre: str, precio: int):",
    "        pedido_id = str(uuid.uuid4())",
    "        items = [{'nombre': producto_nombre, 'precio': precio, 'cantidad': 1}]",
    "        with db_manager.get_connection(tenant_id) as conn:",
    "            with conn.cursor() as cur:",
    "                cur.execute(f'''",
    "                    INSERT INTO {tenant_id}.pedidos (id, cliente_numero, items, total, estado)",
    "                    VALUES (%s, %s, %s, %s, %s)",
    "                ''', (pedido_id, cliente_numero, json.dumps(items), precio, 'pendiente_pago'))",
    "            conn.commit()",
    "        return {'id': pedido_id, 'total': precio}",
    "    ",
    "    def marcar_pagado(self, tenant_id: str, cliente_numero: str):",
    "        with db_manager.get_connection(tenant_id) as conn:",
    "            with conn.cursor() as cur:",
    "                cur.execute(f'''",
    "                    UPDATE {tenant_id}.pedidos SET estado = 'pagado'",
    "                    WHERE cliente_numero = %s AND estado = 'pendiente_pago'",
    "                ''', (cliente_numero,))",
    "                return cur.rowcount",
    "            conn.commit()",
    "",
    "order_repo = OrderRepository()"
)

Create-File "orders\payment.py" @(
    "def generar_link_pago(total: int, referencia: str) -> str:",
    "    return f'https://checkout.wompi.co/l/test_{referencia}_{total}'"
)

# ==================== WHATSAPP ====================
Create-File "whatsapp\__init__.py" @(
    "# WhatsApp module"
)

Create-File "whatsapp\client.py" @(
    "import requests",
    "from core.logger import logger",
    "",
    "class WhatsAppClient:",
    "    def send_message(self, tenant, numero: str, mensaje: str):",
    "        url = f'https://graph.facebook.com/v15.0/{tenant.phone_id}/messages'",
    "        headers = {'Authorization': f'Bearer {tenant.token}', 'Content-Type': 'application/json'}",
    "        data = {'messaging_product': 'whatsapp', 'to': numero, 'text': {'body': mensaje}}",
    "        try:",
    "            r = requests.post(url, headers=headers, json=data, timeout=10)",
    "            return r.status_code == 200",
    "        except Exception as e:",
    "            logger.error(f'Error: {e}')",
    "            return False",
    "",
    "whatsapp_client = WhatsAppClient()"
)

Create-File "whatsapp\message_handler.py" @(
    "from tenants.repository import tenant_repo",
    "from tenants.schema_manager import schema_manager",
    "from orders.repository import order_repo",
    "from orders.payment import generar_link_pago",
    "from ai.client import ai_client",
    "from ai.prompts import PromptBuilder",
    "from whatsapp.client import whatsapp_client",
    "",
    "class MessageHandler:",
    "    def process(self, phone_id: str, numero: str, texto: str):",
    "        tenant = tenant_repo.find_by_phone_id(phone_id)",
    "        if not tenant:",
    "            return",
    "        menu = schema_manager.get_menu(tenant.id)",
    "        if tenant.usar_ia and ai_client.client:",
    "            respuesta = self._responder_con_ia(texto, tenant, menu, numero)",
    "        else:",
    "            respuesta = self._responder_tradicional(texto, tenant, menu, numero)",
    "        whatsapp_client.send_message(tenant, numero, respuesta)",
    "    ",
    "    def _responder_con_ia(self, texto: str, tenant, menu: list, numero: str) -> str:",
    "        texto_lower = texto.lower()",
    "        if any(p in texto_lower for p in ['pague', 'pago']):",
    "            order_repo.marcar_pagado(tenant.id, numero)",
    "            return 'Pago confirmado!'",
    "        if 'menu' in texto_lower:",
    "            return self._formatear_menu(menu)",
    "        messages = PromptBuilder.build_response_prompt(texto, tenant, menu)",
    "        respuesta = ai_client.chat(messages)",
    "        return respuesta if respuesta else self._responder_tradicional(texto, tenant, menu, numero)",
    "    ",
    "    def _responder_tradicional(self, texto: str, tenant, menu: list, numero: str) -> str:",
    "        texto_lower = texto.lower()",
    "        if 'menu' in texto_lower:",
    "            return self._formatear_menu(menu)",
    "        return 'Escribe \"menu\" para ver nuestros productos'",
    "    ",
    "    def _formatear_menu(self, menu: list) -> str:",
    "        if not menu:",
    "            return 'Menu no disponible'",
    "        respuesta = 'Menu:\\n'",
    "        for p in menu:",
    "            respuesta += f'- {p[\"nombre\"]}: ${p[\"precio\"]}\\n'",
    "        return respuesta",
    "",
    "message_handler = MessageHandler()"
)

Create-File "whatsapp\webhook.py" @(
    "from flask import request",
    "from core.logger import logger",
    "from whatsapp.message_handler import message_handler",
    "",
    "def register_webhook_routes(app):",
    "    @app.route('/webhook', methods=['POST'])",
    "    def webhook():",
    "        data = request.get_json(force=True)",
    "        try:",
    "            value = data['entry'][0]['changes'][0]['value']",
    "            if 'messages' not in value:",
    "                return 'ok'",
    "            msg = value['messages'][0]",
    "            if 'text' not in msg:",
    "                return 'ok'",
    "            phone_id = value['metadata']['phone_number_id']",
    "            numero = msg['from']",
    "            texto = msg['text']['body']",
    "            message_handler.process(phone_id, numero, texto)",
    "        except Exception as e:",
    "            logger.error(f'Error: {e}')",
    "            return 'error', 500",
    "        return 'ok'"
)

# ==================== WEB ====================
Create-File "web\__init__.py" @(
    "# Web module"
)

Create-File "web\dashboard.py" @(
    "from flask import Blueprint, jsonify, request",
    "from tenants.repository import tenant_repo",
    "from tenants.schema_manager import schema_manager",
    "from orders.repository import order_repo",
    "",
    "dashboard_bp = Blueprint('dashboard', __name__)",
    "",
    "@dashboard_bp.route('/api/tenant/<tenant_id>/menu', methods=['GET'])",
    "def get_menu(tenant_id):",
    "    return jsonify(schema_manager.get_menu(tenant_id))",
    "",
    "@dashboard_bp.route('/api/tenant/<tenant_id>/pedidos', methods=['GET'])",
    "def get_pedidos(tenant_id):",
    "    return jsonify(order_repo.get_all(tenant_id))",
    "",
    "@dashboard_bp.route('/api/tenant/<tenant_id>/config/ia', methods=['PUT'])",
    "def config_ia(tenant_id):",
    "    data = request.json",
    "    tenant_repo.update_ia_config(tenant_id, data.get('usar_ia', False))",
    "    return jsonify({'status': 'ok'})"
)

Create-File "web\templates\dashboard.html" @(
    "<!DOCTYPE html>",
    "<html>",
    "<head><title>Dashboard</title></head>",
    "<body>",
    "<h1>Panel de Control</h1>",
    "<p>Configura tu asistente de WhatsApp</p>",
    "</body>",
    "</html>"
)

# ==================== ADMIN ====================
Create-File "admin\__init__.py" @(
    "# Admin module"
)

Create-File "admin\metrics.py" @(
    "from flask import Blueprint, jsonify",
    "from core.database import db_manager",
    "",
    "metrics_bp = Blueprint('metrics', __name__)",
    "",
    "@metrics_bp.route('/admin/health')",
    "def health():",
    "    return jsonify({'status': 'ok'})"
)

# ==================== UTILS ====================
Create-File "utils\__init__.py" @(
    "# Utils module"
)

# ==================== APP PRINCIPAL ====================
Create-File "app.py" @(
    "from flask import Flask, jsonify, request",
    "from core.config import config",
    "from core.database import db_manager",
    "from core.logger import setup_logging, logger",
    "from whatsapp.webhook import register_webhook_routes",
    "from web.dashboard import dashboard_bp",
    "from admin.metrics import metrics_bp",
    "from tenants.onboarding import register_new_tenant",
    "",
    "setup_logging()",
    "",
    "app = Flask(__name__)",
    "db_manager.init_global_tables()",
    "register_webhook_routes(app)",
    "app.register_blueprint(dashboard_bp)",
    "app.register_blueprint(metrics_bp)",
    "",
    "@app.route('/api/register', methods=['POST'])",
    "def api_register():",
    "    return register_new_tenant()",
    "",
    "@app.route('/health')",
    "def health():",
    "    return {'status': 'ok'}",
    "",
    "if __name__ == '__main__':",
    "    app.run(host='0.0.0.0', port=config.port)"
)

# ==================== CONFIGURACIÓN ====================
Create-File "requirements.txt" @(
    "Flask==2.3.3",
    "psycopg[binary]>=3.3.3",
    "openai>=1.58.1",
    "python-dotenv>=1.0.1",
    "requests>=2.32.3",
    "gunicorn==22.0.0"
)

Create-File "runtime.txt" @(
    "3.12.8"
)

Create-File ".env.example" @(
    "DATABASE_URL=postgresql://user:pass@localhost:5432/whatsapp_saas",
    "ADMIN_KEY=tu_clave_admin",
    "DEEPSEEK_API_KEY=tu_api_key",
    "PORT=10000"
)

Write-Host "`n✅ Estructura creada exitosamente!" -ForegroundColor Green
Write-Host "`n📌 Siguientes pasos:" -ForegroundColor Yellow
Write-Host "1. pip install -r requirements.txt"
Write-Host "2. Copiar .env.example a .env y configurar"
Write-Host "3. python app.py"