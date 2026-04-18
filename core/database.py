import psycopg
from core.config import config
from core.logger import logger

class DatabaseManager:
    def __init__(self):
        self._base_conn = None
        self._tenant_connections = {}
    
    def get_connection(self, tenant_id: str = None):
        """Obtiene una conexión activa, crea una nueva si es necesario"""
        try:
            if tenant_id:
                # Conexión para tenant específico
                if tenant_id not in self._tenant_connections or self._tenant_connections[tenant_id].closed:
                    logger.info(f'Creando conexion para tenant: {tenant_id}')
                    conn = psycopg.connect(config.database_url)
                    conn.autocommit = True
                    with conn.cursor() as cur:
                        cur.execute(f'CREATE SCHEMA IF NOT EXISTS {tenant_id}')
                        cur.execute(f'SET search_path TO {tenant_id}, public')
                    self._tenant_connections[tenant_id] = conn
                return self._tenant_connections[tenant_id]
            else:
                # Conexión global
                if not self._base_conn or self._base_conn.closed:
                    logger.info('Creando conexion global')
                    self._base_conn = psycopg.connect(config.database_url)
                    self._base_conn.autocommit = True
                return self._base_conn
        except Exception as e:
            logger.error(f'Error de conexion: {e}')
            raise
    
    def close_all_connections(self):
        """Cierra todas las conexiones (útil para shutdown)"""
        if self._base_conn and not self._base_conn.closed:
            self._base_conn.close()
        for tenant_id, conn in self._tenant_connections.items():
            if conn and not conn.closed:
                conn.close()
        logger.info('Todas las conexiones cerradas')
    
    def init_global_tables(self):
        """Inicializa tablas globales"""
        logger.info('Inicializando tablas globales...')
        
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Tabla de tenants
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
                )
                ''')
                
                # Tabla de métricas
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.metricas_tenants (
                    id SERIAL PRIMARY KEY,
                    tenant_id TEXT,
                    fecha DATE DEFAULT CURRENT_DATE,
                    mensajes INTEGER DEFAULT 0,
                    pedidos INTEGER DEFAULT 0,
                    costo_ia DECIMAL(10,4) DEFAULT 0
                )
                ''')
                
                # Índices
                cur.execute('CREATE INDEX IF NOT EXISTS idx_tenants_phone_id ON public.tenants(phone_id)')

                # Tabla de contexto IA por tenant
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS public.tenant_context (
                    tenant_id TEXT PRIMARY KEY,
                    menu_estructurado JSONB DEFAULT '[]',
                    instrucciones TEXT,
                    politicas TEXT,
                    horario TEXT,
                    ubicacion TEXT,
                    prompt_personalizado TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                    );
                ''')                
            conn.commit()
        
        logger.info('Tablas globales listas')

db_manager = DatabaseManager()