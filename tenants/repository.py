import uuid
import json
import re
from core.database import db_manager
from core.logger import logger


class TenantRepository:
    """Repositorio para operaciones con tenants"""
    
    def find_by_phone_id(self, phone_id: str) -> dict:
        """Busca un tenant por phone_id en public.tenants"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, nombre, tipo_negocio, schema_name, phone_id, token, usar_ia, activo, created_at
                        FROM public.tenants
                        WHERE phone_id = %s AND activo = true
                    """, (phone_id,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'id': row[0],
                            'nombre': row[1],
                            'tipo_negocio': row[2],
                            'schema_name': row[3],
                            'phone_id': row[4],
                            'token': row[5],
                            'usar_ia': row[6],
                            'activo': row[7],
                            'created_at': row[8]
                        }
                    return None
        except Exception as e:
            logger.error(f"Error buscando tenant por phone_id {phone_id}: {e}")
            return None
    
    def find_by_id(self, tenant_id: str) -> dict:
        """Busca un tenant por ID"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, nombre, tipo_negocio, schema_name, phone_id, token, usar_ia, activo, created_at
                        FROM public.tenants
                        WHERE id = %s AND activo = true
                    """, (tenant_id,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'id': row[0],
                            'nombre': row[1],
                            'tipo_negocio': row[2],
                            'schema_name': row[3],
                            'phone_id': row[4],
                            'token': row[5],
                            'usar_ia': row[6],
                            'activo': row[7],
                            'created_at': row[8]
                        }
                    return None
        except Exception as e:
            logger.error(f"Error buscando tenant por ID {tenant_id}: {e}")
            return None
    
    def create(self, nombre: str, phone_id: str, token: str = None, tipo_negocio: str = None, usar_ia: bool = True) -> dict:
        """Crea un nuevo tenant"""
        try:
            tenant_id = str(uuid.uuid4())
            # Crear schema_name válido (reemplazar guiones por guiones bajos)
            schema_name = f"tenant_{tenant_id.replace('-', '_')}"
            
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO public.tenants (
                            id, nombre, tipo_negocio, schema_name, phone_id, token, 
                            usar_ia, configuracion, created_at, activo
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                        RETURNING id
                    """, (tenant_id, nombre, tipo_negocio, schema_name, phone_id, token, usar_ia, '{}', True))
                    result = cur.fetchone()
                    conn.commit()
                    
                    if result:
                        # Crear esquema para el tenant (escapado con comillas dobles)
                        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
                        conn.commit()
                        
                        logger.info(f"Tenant creado: {tenant_id} - {nombre} (schema: {schema_name})")
                        return self.find_by_id(tenant_id)
                    return None
        except Exception as e:
            logger.error(f"Error creando tenant: {e}")
            raise
    
    def update(self, tenant_id: str, **kwargs) -> bool:
        """Actualiza un tenant"""
        try:
            allowed_fields = ['nombre', 'tipo_negocio', 'phone_id', 'token', 'usar_ia', 'activo']
            updates = []
            values = []
            
            for field, value in kwargs.items():
                if field in allowed_fields:
                    updates.append(f"{field} = %s")
                    values.append(value)
            
            if not updates:
                return False
            
            values.append(tenant_id)
            
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        UPDATE public.tenants
                        SET {', '.join(updates)}
                        WHERE id = %s
                    """, values)
                    conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Error actualizando tenant {tenant_id}: {e}")
            return False

    def guardar_configuracion_ia(self, tenant_id: str, usar_ia: bool) -> dict:
        """Guarda la configuración de IA del tenant"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE public.tenants 
                        SET usar_ia = %s
                        WHERE id = %s
                    """, (usar_ia, tenant_id))
                    conn.commit()
            
            # Limpiar caché
            db_manager.clear_tenant_cache(tenant_id)
            
            logger.info(f"Configuración IA actualizada: tenant={tenant_id}, usar_ia={usar_ia}")
            return {'success': True, 'message': f'IA {"habilitada" if usar_ia else "deshabilitada"}'}
        except Exception as e:
            logger.error(f"Error guardando configuración IA: {e}")
            return {'success': False, 'error': str(e)}

    def update_ia_config(self, tenant_id: str, usar_ia: bool) -> bool:
        """Actualiza solo la configuración de IA del tenant"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE public.tenants 
                        SET usar_ia = %s
                        WHERE id = %s
                    """, (usar_ia, tenant_id))
                    conn.commit()
            
            # Limpiar caché
            db_manager.clear_tenant_cache(tenant_id)
            
            logger.info(f"IA configurada: tenant={tenant_id}, usar_ia={usar_ia}")
            return True
        except Exception as e:
            logger.error(f"Error actualizando IA config: {e}")
            return False
    
    def get_all(self) -> list:
        """Obtiene todos los tenants"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, nombre, tipo_negocio, schema_name, phone_id, token, usar_ia, activo, created_at
                        FROM public.tenants
                        WHERE activo = true
                        ORDER BY created_at DESC
                    """)
                    rows = cur.fetchall()
                    tenants = []
                    for row in rows:
                        tenants.append({
                            'id': row[0],
                            'nombre': row[1],
                            'tipo_negocio': row[2],
                            'schema_name': row[3],
                            'phone_id': row[4],
                            'token': row[5],
                            'usar_ia': row[6],
                            'activo': row[7],
                            'created_at': row[8]
                        })
                    return tenants
        except Exception as e:
            logger.error(f"Error obteniendo tenants: {e}")
            return []


# ==================== INSTANCIA GLOBAL ====================

tenant_repo = TenantRepository()