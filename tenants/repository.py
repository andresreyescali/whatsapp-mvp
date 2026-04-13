import uuid
from psycopg.rows import dict_row  # ← Esta línea DEBE estar
from core.database import db_manager
from core.logger import logger

class TenantRepository:
    def find_by_phone_id(self, phone_id: str):
        with db_manager.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    'SELECT * FROM public.tenants WHERE phone_id = %s AND activo = true',
                    (phone_id,)
                )
                row = cur.fetchone()
                return row if row else None
    
    def create(self, nombre: str, phone_id: str, token: str, tipo_negocio: str = 'restaurante'):
        tenant_id = f'tenant_{uuid.uuid4().hex[:8]}'
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO public.tenants (id, nombre, tipo_negocio, schema_name, phone_id, token)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (tenant_id, nombre, tipo_negocio, tenant_id, phone_id, token))
            conn.commit()
        logger.info(f'Tenant creado: {nombre} ({tenant_id})')
        return {'id': tenant_id, 'nombre': nombre, 'phone_id': phone_id, 'token': token}
    
    def update_ia_config(self, tenant_id: str, usar_ia: bool):
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE public.tenants SET usar_ia = %s WHERE id = %s', (usar_ia, tenant_id))
            conn.commit()

tenant_repo = TenantRepository()