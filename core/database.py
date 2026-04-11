import psycopg
from psycopg.rows import dict_row
from core.config import config
from core.logger import logger

class DatabaseManager:
    def __init__(self):
        self._base_conn = None
        self._tenant_connections = {}
    
    def get_connection(self, tenant_id: str = None):
        if tenant_id:
            if tenant_id not in self._tenant_connections:
                logger.info(f'Creando conexion para tenant: {tenant_id}')
                conn = psycopg.connect(config.database_url)
                with conn.cursor() as cur:
                    cur.execute(f'SET search_path TO {tenant_id}, public')
                self._tenant_connections[tenant_id] = conn
            return self._tenant_connections[tenant_id]
        else:
            if not self._base_conn:
                self._base_conn = psycopg.connect(config.database_url)
            return self._base_conn
    
    def init_global_tables(self):
        logger.info('Inicializando tablas globales...')
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.tenants (
                    id TEXT PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    tipo_negocio TEXT,
                    schema_name TEXT UNIQUE NOT NULL,
                    phone_id TEXT,
                    token TEXT,
                    usar_ia BOOLEAN DEFAULT false,
                    configuracion JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW(),
                    activo BOOLEAN DEFAULT true
                );
                ''')
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.metricas_tenants (
                    id SERIAL PRIMARY KEY,
                    tenant_id TEXT,
                    fecha DATE DEFAULT CURRENT_DATE,
                    mensajes INTEGER DEFAULT 0,
                    pedidos INTEGER DEFAULT 0,
                    costo_ia DECIMAL(10,4) DEFAULT 0
                );
                ''')
            conn.commit()
        logger.info('Tablas globales listas')

db_manager = DatabaseManager()