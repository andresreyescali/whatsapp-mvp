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
                        SELECT id, nombre, tipo_negocio, schema_name, phone_id, token, usar_ia, activo, 
                               configuracion, created_at
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
                            'configuracion': row[8] if row[8] else {},
                            'created_at': row[9]
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
                        SELECT id, nombre, tipo_negocio, schema_name, phone_id, token, usar_ia, activo,
                               configuracion, created_at
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
                            'configuracion': row[8] if row[8] else {},
                            'created_at': row[9]
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
            
            # Configuración inicial por defecto
            configuracion_inicial = {
                'productos': {
                    'campos_personalizados': [],  # Lista de campos extra que el tenant puede agregar
                    'categorias_disponibles': [],
                    'unidades_medida': []  # unidades como 'unidad', 'kg', 'litro', etc.
                },
                'pedidos': {
                    'estados_personalizados': [],
                    'requiere_direccion': True,
                    'requiere_telefono': True
                },
                'apariencia': {
                    'tema': 'default',
                    'logo_url': None
                },
                'personalizacion': {
                    'habilitada': True,
                    'configuraciones': []  # IDs de configuraciones activas
                }
            }
            
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO public.tenants (
                            id, nombre, tipo_negocio, schema_name, phone_id, token, 
                            usar_ia, configuracion, created_at, activo
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                        RETURNING id
                    """, (tenant_id, nombre, tipo_negocio, schema_name, phone_id, token, usar_ia, json.dumps(configuracion_inicial), True))
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
    
    # ==================== MÉTODOS PARA CONFIGURACIÓN DEL TENANT ====================
    
    def get_configuracion(self, tenant_id: str) -> dict:
        """Obtiene la configuración completa del tenant"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT configuracion 
                        FROM public.tenants 
                        WHERE id = %s
                    """, (tenant_id,))
                    row = cur.fetchone()
                    if row and row[0]:
                        if isinstance(row[0], str):
                            return json.loads(row[0])
                        return row[0]
                    return {}
        except Exception as e:
            logger.error(f"Error obteniendo configuración de tenant {tenant_id}: {e}")
            return {}
    
    def update_configuracion(self, tenant_id: str, configuracion: dict) -> bool:
        """Actualiza la configuración completa del tenant"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE public.tenants 
                        SET configuracion = %s
                        WHERE id = %s
                    """, (json.dumps(configuracion), tenant_id))
                    conn.commit()
            
            # Limpiar caché
            db_manager.clear_tenant_cache(tenant_id)
            
            logger.info(f"Configuración actualizada para tenant {tenant_id}")
            return True
        except Exception as e:
            logger.error(f"Error actualizando configuración de tenant {tenant_id}: {e}")
            return False
    
    def agregar_campo_personalizado(self, tenant_id: str, campo: dict) -> dict:
        """
        Agrega un campo personalizado para los productos del tenant
        campo = {
            'nombre': 'talla',
            'tipo': 'text',  # text, number, select, boolean, date
            'requerido': False,
            'opciones': ['S', 'M', 'L', 'XL']  # solo para tipo 'select'
        }
        """
        try:
            config = self.get_configuracion(tenant_id)
            
            if 'productos' not in config:
                config['productos'] = {}
            if 'campos_personalizados' not in config['productos']:
                config['productos']['campos_personalizados'] = []
            
            # Verificar si ya existe un campo con el mismo nombre
            for existing in config['productos']['campos_personalizados']:
                if existing.get('nombre') == campo.get('nombre'):
                    # Actualizar campo existente
                    existing.update(campo)
                    self.update_configuracion(tenant_id, config)
                    logger.info(f"Campo personalizado actualizado: {campo.get('nombre')}")
                    return {'success': True, 'message': 'Campo actualizado', 'campo': existing}
            
            # Agregar nuevo campo
            config['productos']['campos_personalizados'].append(campo)
            self.update_configuracion(tenant_id, config)
            logger.info(f"Campo personalizado agregado: {campo.get('nombre')}")
            return {'success': True, 'message': 'Campo agregado', 'campo': campo}
        except Exception as e:
            logger.error(f"Error agregando campo personalizado: {e}")
            return {'success': False, 'error': str(e)}
    
    def eliminar_campo_personalizado(self, tenant_id: str, nombre_campo: str) -> dict:
        """Elimina un campo personalizado de los productos del tenant"""
        try:
            config = self.get_configuracion(tenant_id)
            
            if 'productos' not in config or 'campos_personalizados' not in config['productos']:
                return {'success': False, 'message': 'No hay campos personalizados configurados'}
            
            original_len = len(config['productos']['campos_personalizados'])
            config['productos']['campos_personalizados'] = [
                c for c in config['productos']['campos_personalizados'] 
                if c.get('nombre') != nombre_campo
            ]
            
            if len(config['productos']['campos_personalizados']) < original_len:
                self.update_configuracion(tenant_id, config)
                logger.info(f"Campo personalizado eliminado: {nombre_campo}")
                return {'success': True, 'message': 'Campo eliminado'}
            
            return {'success': False, 'message': 'Campo no encontrado'}
        except Exception as e:
            logger.error(f"Error eliminando campo personalizado: {e}")
            return {'success': False, 'error': str(e)}
    
    def obtener_campos_personalizados(self, tenant_id: str) -> list:
        """Obtiene la lista de campos personalizados configurados para el tenant"""
        config = self.get_configuracion(tenant_id)
        return config.get('productos', {}).get('campos_personalizados', [])
    
    def obtener_categorias(self, tenant_id: str) -> list:
        """Obtiene las categorías disponibles para el tenant"""
        config = self.get_configuracion(tenant_id)
        categorias = config.get('productos', {}).get('categorias_disponibles', [])
        
        # Si no hay categorías configuradas, devolver categorías por defecto según tipo de negocio
        if not categorias:
            tenant = self.find_by_id(tenant_id)
            if tenant:
                tipo = tenant.get('tipo_negocio')
                categorias_por_defecto = {
                    'restaurante': ['pizzas', 'hamburguesas', 'bebidas', 'postres', 'entradas'],
                    'panaderia': ['panes', 'pastelería', 'galletas', 'tortas'],
                    'pasteleria': ['tortas', 'postres', 'galletas', 'cupcakes'],
                    'inmobiliaria': ['apartamentos', 'casas', 'comercial', 'terrenos'],
                    'venta_autos': ['sedanes', 'suvs', 'camionetas', 'deportivos', 'hatchbacks'],
                    'venta_motos': ['scooters', 'naked', 'enduro', 'deportivas', 'electricas'],
                    'hotel': ['habitaciones', 'servicios', 'paquetes'],
                    'agencia_viajes': ['paquetes', 'servicios', 'tours', 'vuelos']
                }
                return categorias_por_defecto.get(tipo, ['general'])
        return categorias
    
    def actualizar_categorias(self, tenant_id: str, categorias: list) -> dict:
        """Actualiza la lista de categorías disponibles para el tenant"""
        try:
            config = self.get_configuracion(tenant_id)
            
            if 'productos' not in config:
                config['productos'] = {}
            
            config['productos']['categorias_disponibles'] = categorias
            self.update_configuracion(tenant_id, config)
            
            logger.info(f"Categorías actualizadas para tenant {tenant_id}: {categorias}")
            return {'success': True, 'message': 'Categorías actualizadas'}
        except Exception as e:
            logger.error(f"Error actualizando categorías: {e}")
            return {'success': False, 'error': str(e)}
    
    def actualizar_unidades_medida(self, tenant_id: str, unidades: list) -> dict:
        """Actualiza la lista de unidades de medida disponibles"""
        try:
            config = self.get_configuracion(tenant_id)
            
            if 'productos' not in config:
                config['productos'] = {}
            
            config['productos']['unidades_medida'] = unidades
            self.update_configuracion(tenant_id, config)
            
            logger.info(f"Unidades de medida actualizadas para tenant {tenant_id}: {unidades}")
            return {'success': True, 'message': 'Unidades de medida actualizadas'}
        except Exception as e:
            logger.error(f"Error actualizando unidades de medida: {e}")
            return {'success': False, 'error': str(e)}
    
    def obtener_configuracion_visual(self, tenant_id: str) -> dict:
        """Obtiene la configuración visual del tenant (tema, logo, etc.)"""
        config = self.get_configuracion(tenant_id)
        return config.get('apariencia', {
            'tema': 'default',
            'logo_url': None,
            'colores': {}
        })
    
    def actualizar_configuracion_visual(self, tenant_id: str, apariencia: dict) -> dict:
        """Actualiza la configuración visual del tenant"""
        try:
            config = self.get_configuracion(tenant_id)
            config['apariencia'] = apariencia
            self.update_configuracion(tenant_id, config)
            
            logger.info(f"Configuración visual actualizada para tenant {tenant_id}")
            return {'success': True, 'message': 'Configuración visual actualizada'}
        except Exception as e:
            logger.error(f"Error actualizando configuración visual: {e}")
            return {'success': False, 'error': str(e)}
    
    # ==================== MÉTODOS PARA MIGRACIÓN ====================
    
    def migrar_tenant_existente(self, tenant_id: str) -> dict:
        """Migra un tenant existente para agregar la columna configuracion si no existe"""
        try:
            # Verificar si la columna configuracion existe
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'tenants' AND column_name = 'configuracion'
                    """)
                    if not cur.fetchone():
                        # Agregar columna configuracion si no existe
                        cur.execute("""
                            ALTER TABLE public.tenants 
                            ADD COLUMN configuracion JSONB DEFAULT '{}'::jsonb
                        """)
                        conn.commit()
                        logger.info(f"Columna configuracion agregada a la tabla tenants")
            
            # Verificar si el tenant ya tiene configuración
            config = self.get_configuracion(tenant_id)
            if not config:
                # Crear configuración por defecto
                configuracion_por_defecto = {
                    'productos': {
                        'campos_personalizados': [],
                        'categorias_disponibles': [],
                        'unidades_medida': []
                    },
                    'pedidos': {
                        'estados_personalizados': [],
                        'requiere_direccion': True,
                        'requiere_telefono': True
                    },
                    'apariencia': {
                        'tema': 'default',
                        'logo_url': None
                    },
                    'personalizacion': {
                        'habilitada': True,
                        'configuraciones': []
                    }
                }
                self.update_configuracion(tenant_id, configuracion_por_defecto)
                logger.info(f"Configuración por defecto creada para tenant {tenant_id}")
            
            return {'success': True, 'message': 'Tenant migrado exitosamente'}
        except Exception as e:
            logger.error(f"Error migrando tenant {tenant_id}: {e}")
            return {'success': False, 'error': str(e)}
    
    # ==================== NUEVOS MÉTODOS PARA PERSONALIZACIÓN ====================
    
    def habilitar_personalizacion(self, tenant_id: str, habilitada: bool = True) -> dict:
        """Habilita o deshabilita la funcionalidad de personalización para el tenant"""
        try:
            config = self.get_configuracion(tenant_id)
            
            if 'personalizacion' not in config:
                config['personalizacion'] = {}
            
            config['personalizacion']['habilitada'] = habilitada
            self.update_configuracion(tenant_id, config)
            
            estado = "habilitada" if habilitada else "deshabilitada"
            logger.info(f"Personalización {estado} para tenant {tenant_id}")
            return {'success': True, 'message': f'Personalización {estado}'}
        except Exception as e:
            logger.error(f"Error cambiando estado de personalización: {e}")
            return {'success': False, 'error': str(e)}
    
    def obtener_configuraciones_personalizacion_activas(self, tenant_id: str) -> list:
        """Obtiene los IDs de las configuraciones de personalización activas para el tenant"""
        config = self.get_configuracion(tenant_id)
        return config.get('personalizacion', {}).get('configuraciones', [])
    
    def activar_configuracion_personalizacion(self, tenant_id: str, config_id: int) -> dict:
        """Activa una configuración de personalización para el tenant"""
        try:
            config = self.get_configuracion(tenant_id)
            
            if 'personalizacion' not in config:
                config['personalizacion'] = {}
            if 'configuraciones' not in config['personalizacion']:
                config['personalizacion']['configuraciones'] = []
            
            if config_id not in config['personalizacion']['configuraciones']:
                config['personalizacion']['configuraciones'].append(config_id)
                self.update_configuracion(tenant_id, config)
                logger.info(f"Configuración {config_id} activada para tenant {tenant_id}")
            
            return {'success': True, 'message': 'Configuración activada'}
        except Exception as e:
            logger.error(f"Error activando configuración: {e}")
            return {'success': False, 'error': str(e)}
    
    def desactivar_configuracion_personalizacion(self, tenant_id: str, config_id: int) -> dict:
        """Desactiva una configuración de personalización para el tenant"""
        try:
            config = self.get_configuracion(tenant_id)
            
            if 'personalizacion' not in config:
                config['personalizacion'] = {}
            if 'configuraciones' not in config['personalizacion']:
                config['personalizacion']['configuraciones'] = []
            
            if config_id in config['personalizacion']['configuraciones']:
                config['personalizacion']['configuraciones'].remove(config_id)
                self.update_configuracion(tenant_id, config)
                logger.info(f"Configuración {config_id} desactivada para tenant {tenant_id}")
            
            return {'success': True, 'message': 'Configuración desactivada'}
        except Exception as e:
            logger.error(f"Error desactivando configuración: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_personalizacion_habilitada(self, tenant_id: str) -> bool:
        """Verifica si la personalización está habilitada para el tenant"""
        config = self.get_configuracion(tenant_id)
        return config.get('personalizacion', {}).get('habilitada', True)


# ==================== INSTANCIA GLOBAL ====================

tenant_repo = TenantRepository()