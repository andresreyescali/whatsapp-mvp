from core.database import db_manager

class SchemaManager:
    def create_tenant_schema(self, tenant_id: str, tipo_negocio: str):
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS {tenant_id}')
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS {tenant_id}.productos (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    precio INTEGER NOT NULL,
                    categoria TEXT,
                    disponible BOOLEAN DEFAULT true
                )
                ''')
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS {tenant_id}.pedidos (
                    id TEXT PRIMARY KEY,
                    cliente_numero TEXT,
                    items JSONB,
                    total INTEGER,
                    estado TEXT DEFAULT 'pendiente_pago',
                    created_at TIMESTAMP DEFAULT NOW()
                )
                ''')
            conn.commit()
    
    def get_menu(self, tenant_id: str):
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f'SELECT * FROM {tenant_id}.productos WHERE disponible = true')
                return cur.fetchall()

schema_manager = SchemaManager()