import uuid
from core.database import db_manager
from core.logger import logger

class TenantRepository:
    """Repositorio para gestión de tenants"""
    
    def find_by_phone_id(self, phone_id: str):
        """Busca tenant por phone_id de WhatsApp"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'SELECT id, nombre, tipo_negocio, schema_name, phone_id, token, usar_ia, configuracion, created_at, activo '
                        'FROM public.tenants WHERE phone_id = %s AND activo = true',
                        (phone_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        columns = ['id', 'nombre', 'tipo_negocio', 'schema_name', 'phone_id', 
                                  'token', 'usar_ia', 'configuracion', 'created_at', 'activo']
                        return dict(zip(columns, row))
                    return None
        except Exception as e:
            logger.error(f'Error en find_by_phone_id: {e}')
            return None
    
    def find_by_id(self, tenant_id: str):
        """Busca tenant por ID"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'SELECT id, nombre, tipo_negocio, schema_name, phone_id, token, usar_ia, configuracion, created_at, activo '
                        'FROM public.tenants WHERE id = %s',
                        (tenant_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        columns = ['id', 'nombre', 'tipo_negocio', 'schema_name', 'phone_id', 
                                  'token', 'usar_ia', 'configuracion', 'created_at', 'activo']
                        return dict(zip(columns, row))
                    return None
        except Exception as e:
            logger.error(f'Error en find_by_id: {e}')
            return None
    
    def create(self, nombre: str, phone_id: str, token: str, tipo_negocio: str = 'restaurante'):
        """Crea un nuevo tenant"""
        tenant_id = f'tenant_{uuid.uuid4().hex[:8]}'
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        INSERT INTO public.tenants (id, nombre, tipo_negocio, schema_name, phone_id, token)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (tenant_id, nombre, tipo_negocio, tenant_id, phone_id, token))
                conn.commit()
            logger.info(f'Tenant creado: {nombre} ({tenant_id})')
            return {'id': tenant_id, 'nombre': nombre, 'phone_id': phone_id, 'token': token}
        except Exception as e:
            logger.error(f'Error creando tenant: {e}')
            raise
    
    def update_ia_config(self, tenant_id: str, usar_ia: bool):
        """Actualiza configuración de IA del tenant"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('UPDATE public.tenants SET usar_ia = %s WHERE id = %s', (usar_ia, tenant_id))
                conn.commit()
            logger.info(f'IA {"activada" if usar_ia else "desactivada"} para {tenant_id}')
        except Exception as e:
            logger.error(f'Error actualizando IA: {e}')
            raise
    
    def get_all(self):
        """Obtiene todos los tenants"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT id, nombre, phone_id, created_at FROM public.tenants ORDER BY created_at DESC')
                    rows = cur.fetchall()
                    columns = ['id', 'nombre', 'phone_id', 'created_at']
                    return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f'Error obteniendo tenants: {e}')
            return []
    
    def delete(self, tenant_id: str):
        """Elimina un tenant y todos sus datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    # Eliminar métricas
                    cur.execute("DELETE FROM public.metricas_tenants WHERE tenant_id = %s", (tenant_id,))
                    # Eliminar tenant de la tabla
                    cur.execute("DELETE FROM public.tenants WHERE id = %s", (tenant_id,))
                    # Eliminar el schema completo (todas las tablas del tenant)
                    cur.execute(f"DROP SCHEMA IF EXISTS {tenant_id} CASCADE")
                conn.commit()
            logger.info(f'Tenant {tenant_id} eliminado permanentemente')
            return True
        except Exception as e:
            logger.error(f'Error eliminando tenant {tenant_id}: {e}')
            raise

# Instancia global
tenant_repo = TenantRepository()