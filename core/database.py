import psycopg
from core.config import config
from core.logger import logger
from datetime import datetime

class DatabaseManager:
    def __init__(self):
        self._base_conn = None
        self._tenant_connections = {}
        self._tenant_schema_cache = {}  # Caché de schema_name por tenant_id
    
    def _get_schema_name(self, tenant_id: str):
        """Obtiene el schema_name de un tenant desde la base de datos"""
        # Verificar caché primero
        if tenant_id in self._tenant_schema_cache:
            return self._tenant_schema_cache[tenant_id]
        
        try:
            with self.get_connection_global() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT schema_name FROM public.tenants 
                        WHERE id = %s AND activo = true
                    """, (tenant_id,))
                    row = cur.fetchone()
                    if row:
                        schema_name = row[0]
                        self._tenant_schema_cache[tenant_id] = schema_name
                        return schema_name
                    return None
        except Exception as e:
            logger.error(f"Error obteniendo schema_name para tenant {tenant_id}: {e}")
            return None
    
    def get_connection_global(self):
        """Obtiene una conexión global (sin cambiar de schema)"""
        try:
            if not self._base_conn or self._base_conn.closed:
                logger.info('Creando conexion global')
                self._base_conn = psycopg.connect(config.database_url)
                self._base_conn.autocommit = True
            return self._base_conn
        except Exception as e:
            logger.error(f'Error de conexion global: {e}')
            raise
    
    def get_connection(self, tenant_id: str = None):
        """Obtiene una conexión activa, crea una nueva si es necesario"""
        try:
            if tenant_id:
                # Verificar si ya tenemos una conexión para este tenant
                if tenant_id in self._tenant_connections and not self._tenant_connections[tenant_id].closed:
                    return self._tenant_connections[tenant_id]
                
                logger.info(f'Creando conexion para tenant: {tenant_id}')
                
                # Obtener el schema_name del tenant
                schema_name = self._get_schema_name(tenant_id)
                
                if not schema_name:
                    # Si no se encuentra el tenant, usar el tenant_id como schema (pero sanitizado)
                    schema_name = f"tenant_{tenant_id.replace('-', '_')}"
                    logger.warning(f"Tenant {tenant_id} no encontrado en BD, usando schema: {schema_name}")
                
                # Crear conexión
                conn = psycopg.connect(config.database_url)
                conn.autocommit = True
                
                with conn.cursor() as cur:
                    # Crear esquema si no existe (escapado con comillas dobles por si tiene caracteres especiales)
                    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
                    # Cambiar al esquema del tenant
                    cur.execute(f'SET search_path TO "{schema_name}", public')
                    logger.info(f"Conexión establecida - Schema: {schema_name}, Tenant: {tenant_id}")
                
                self._tenant_connections[tenant_id] = conn
                return conn
            else:
                # Conexión global (schema public)
                if not self._base_conn or self._base_conn.closed:
                    logger.info('Creando conexion global')
                    self._base_conn = psycopg.connect(config.database_url)
                    self._base_conn.autocommit = True
                return self._base_conn
        except Exception as e:
            logger.error(f'Error de conexion: {e}')
            raise
    
    def get_connection_by_schema(self, schema_name: str):
        """Obtiene una conexión directamente por nombre de esquema (útil cuando ya se conoce el schema)"""
        try:
            conn = psycopg.connect(config.database_url)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
                cur.execute(f'SET search_path TO "{schema_name}", public')
            return conn
        except Exception as e:
            logger.error(f'Error de conexion para schema {schema_name}: {e}')
            raise
    
    def close_all_connections(self):
        """Cierra todas las conexiones (útil para shutdown)"""
        if self._base_conn and not self._base_conn.closed:
            self._base_conn.close()
        for tenant_id, conn in self._tenant_connections.items():
            if conn and not conn.closed:
                conn.close()
        self._tenant_schema_cache.clear()
        logger.info('Todas las conexiones cerradas')
    
    def generar_numero_pedido(self, tenant_id: str, secuencial: int) -> str:
        """Genera número de pedido compuesto: ID_Negocio + Fecha + Hora + Secuencial"""
        # Obtener schema_name para generar el prefijo
        schema_name = self._get_schema_name(tenant_id)
        if schema_name:
            # Extraer número del schema_name (ej: tenant_5deac974_6c20_46c2_abc8_2a5419b78235)
            tenant_num = schema_name.replace('tenant_', '').replace('-', '').replace('_', '').upper()
        else:
            tenant_num = tenant_id.replace('tenant_', '').replace('-', '').upper()
        
        # Limitar a 8 caracteres
        if len(tenant_num) > 8:
            tenant_num = tenant_num[:8]
        elif len(tenant_num) < 8:
            tenant_num = tenant_num.ljust(8, '0')
        
        # Fecha y hora: YYYYMMDDHHMMSS
        ahora = datetime.now()
        fecha_hora = ahora.strftime('%Y%m%d%H%M%S')
        
        # Secuencial con 4 dígitos
        sec = str(secuencial).zfill(4)
        
        # Formato: ID_Negocio(8) + FechaHora(14) + Secuencial(4) = 26 caracteres
        numero_pedido = f"{tenant_num}{fecha_hora}{sec}"
        
        return numero_pedido
    
    def clear_tenant_cache(self, tenant_id: str = None):
        """Limpia la caché de esquemas"""
        if tenant_id:
            self._tenant_schema_cache.pop(tenant_id, None)
        else:
            self._tenant_schema_cache.clear()
    
def init_global_tables(self):
    """Inicializa tablas globales con manejo de errores"""
    logger.info('Inicializando tablas globales...')
    
    try:
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
                
                # Tabla de usuarios
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.usuarios (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email VARCHAR(200) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    nombre_completo VARCHAR(200),
                    telefono VARCHAR(50),
                    email_verificado BOOLEAN DEFAULT false,
                    codigo_verificacion VARCHAR(10),
                    created_at TIMESTAMP DEFAULT NOW(),
                    ultimo_acceso TIMESTAMP,
                    activo BOOLEAN DEFAULT true
                )
                ''')
                
                # Tabla de roles de sistema
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.roles_sistema (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(50) UNIQUE NOT NULL
                )
                ''')
                
                # Insertar roles por defecto
                cur.execute('''
                INSERT INTO public.roles_sistema (nombre) VALUES 
                    ('super_admin'), ('admin_cliente'), ('viewer')
                ON CONFLICT (nombre) DO NOTHING
                ''')
                
                # Agregar columna rol_sistema a la tabla usuarios
                cur.execute('''
                DO $$ 
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                   WHERE table_name='usuarios' AND column_name='rol_sistema_id') THEN
                        ALTER TABLE public.usuarios ADD COLUMN rol_sistema_id INTEGER REFERENCES public.roles_sistema(id) DEFAULT 2;
                    END IF;
                END $$;
                ''')
                
                # Tabla de roles por negocio
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.roles_negocio (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(50) UNIQUE NOT NULL
                )
                ''')
                
                # Insertar roles por defecto
                cur.execute('''
                INSERT INTO public.roles_negocio (nombre) VALUES 
                    ('owner'), ('admin'), ('editor'), ('viewer')
                ON CONFLICT (nombre) DO NOTHING
                ''')
                
                # Tabla de relación usuario-tenant (negocios)
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.usuario_negocio (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    usuario_id UUID REFERENCES public.usuarios(id) ON DELETE CASCADE,
                    tenant_id TEXT REFERENCES public.tenants(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(usuario_id, tenant_id)
                )
                ''')
                
                # Modificar tabla usuario_negocio para incluir rol
                cur.execute('''
                DO $$ 
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                   WHERE table_name='usuario_negocio' AND column_name='rol_id') THEN
                        ALTER TABLE public.usuario_negocio 
                            ADD COLUMN rol_id INTEGER REFERENCES public.roles_negocio(id),
                            ADD COLUMN invitado_por UUID REFERENCES public.usuarios(id),
                            ADD COLUMN invitado_en TIMESTAMP DEFAULT NOW(),
                            ADD COLUMN invitacion_aceptada BOOLEAN DEFAULT true;
                    END IF;
                END $$;
                ''')
                
                # Tabla de verificación de negocios
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.verificacion_negocio (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id TEXT REFERENCES public.tenants(id) ON DELETE CASCADE,
                    metodo_verificacion VARCHAR(50),
                    codigo_verificacion VARCHAR(10),
                    codigo_enviado TIMESTAMP,
                    verificado BOOLEAN DEFAULT false,
                    fecha_verificacion TIMESTAMP,
                    intentos_fallidos INTEGER DEFAULT 0
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
                )
                ''')
                
                # Tabla de pedidos
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.pedidos (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT REFERENCES public.tenants(id) ON DELETE CASCADE,
                    cliente_numero TEXT NOT NULL,
                    cliente_nombre TEXT,
                    items JSONB NOT NULL,
                    total INTEGER NOT NULL,
                    estado VARCHAR(50) DEFAULT 'nuevo',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    pagado_at TIMESTAMP,
                    enviado_at TIMESTAMP,
                    cancelado_at TIMESTAMP,
                    notas TEXT
                )
                ''')
                
                # Tabla de conversaciones IA
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.conversaciones_ia (
                    id SERIAL PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    cliente_numero TEXT NOT NULL,
                    mensaje TEXT NOT NULL,
                    respuesta TEXT,
                    tipo VARCHAR(20) DEFAULT 'cliente',
                    created_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # Tabla de carritos
                cur.execute('''
                CREATE TABLE IF NOT EXISTS public.carritos (
                    id SERIAL PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    cliente_numero TEXT NOT NULL,
                    items JSONB DEFAULT '[]',
                    total INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # ÍNDICES - Solo los que funcionan
                cur.execute('CREATE INDEX IF NOT EXISTS idx_tenants_phone_id ON public.tenants(phone_id)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_tenants_schema_name ON public.tenants(schema_name)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_usuario_negocio_usuario ON public.usuario_negocio(usuario_id)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_usuario_negocio_tenant ON public.usuario_negocio(tenant_id)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_conversaciones_tenant ON public.conversaciones_ia(tenant_id)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_conversaciones_cliente ON public.conversaciones_ia(cliente_numero)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_carritos_tenant_cliente ON public.carritos(tenant_id, cliente_numero)')
                # COMENTA esta línea si tu tabla pedidos no tiene tenant_id:
                # cur.execute('CREATE INDEX IF NOT EXISTS idx_pedidos_tenant_cliente ON public.pedidos(tenant_id, cliente_numero)')
                
            conn.commit()
        
        logger.info('Tablas globales listas')
        
    except Exception as e:
        logger.error(f'Error inicializando tablas globales: {e}')
        raise

db_manager = DatabaseManager()