import uuid
import json
from core.database import db_manager
from core.logger import logger

class OrderRepository:
    """Gestión de pedidos por tenant"""
    
    def _verificar_columnas_pedidos(self, tenant_id: str, conn):
        """Verifica y crea las columnas necesarias en la tabla pedidos"""
        try:
            with conn.cursor() as cur:
                # Verificar/crear columna cliente_numero
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'cliente_numero') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN cliente_numero TEXT;
                        END IF;
                    END $$;
                """)
                
                # Verificar/crear columna numero_pedido
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'numero_pedido') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN numero_pedido TEXT;
                        END IF;
                    END $$;
                """)
                
                # Verificar/crear columna secuencial
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'secuencial') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN secuencial INTEGER;
                        END IF;
                    END $$;
                """)
                
                # Verificar/crear columna items
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'items') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN items JSONB;
                        END IF;
                    END $$;
                """)
                
                # Verificar/crear columna pagado_at
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'pagado_at') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN pagado_at TIMESTAMP;
                        END IF;
                    END $$;
                """)
                
                # Verificar/crear columna enviado_at
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'enviado_at') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN enviado_at TIMESTAMP;
                        END IF;
                    END $$;
                """)
                
                # Verificar/crear columna cancelado_at
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'cancelado_at') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN cancelado_at TIMESTAMP;
                        END IF;
                    END $$;
                """)
                
                # Verificar/crear columna updated_at
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'updated_at') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN updated_at TIMESTAMP DEFAULT NOW();
                        END IF;
                    END $$;
                """)
                
                # Verificar/crear columna direccion_entrega
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'direccion_entrega') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN direccion_entrega TEXT;
                        END IF;
                    END $$;
                """)
                
                # Verificar/crear columna notas
                cur.execute(f"""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                       WHERE table_schema = '{tenant_id}' 
                                       AND table_name = 'pedidos' 
                                       AND column_name = 'notas') THEN
                            ALTER TABLE {tenant_id}.pedidos ADD COLUMN notas TEXT;
                        END IF;
                    END $$;
                """)
                
                conn.commit()
                logger.info(f"Columnas verificadas/creadas para tabla pedidos en {tenant_id}")
        except Exception as e:
            logger.warning(f'Error verificando/creando columnas (puede que ya existan): {e}')
    
    def create(self, tenant_id: str, cliente_numero: str, producto_nombre: str, precio: int, cantidad: int = 1) -> dict:
        """Crea un nuevo pedido con número compuesto"""
        pedido_id = str(uuid.uuid4())
        
        # Verificar que las columnas existen
        with db_manager.get_connection(tenant_id) as conn:
            self._verificar_columnas_pedidos(tenant_id, conn)
        
        # Obtener el siguiente secuencial
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COALESCE(MAX(secuencial), 0) + 1 FROM {tenant_id}.pedidos")
                row = cur.fetchone()
                secuencial = row[0] if row else 1
        
        # Generar número compuesto
        numero_pedido = db_manager.generar_numero_pedido(tenant_id, secuencial)
        
        items = [{"nombre": producto_nombre, "precio": precio, "cantidad": cantidad}]
        total = precio * cantidad
        
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO {tenant_id}.pedidos 
                        (id, cliente_numero, items, total, estado, numero_pedido, secuencial, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """, (pedido_id, cliente_numero, json.dumps(items), total, "nuevo", numero_pedido, secuencial))
                conn.commit()
            
            logger.info(f'Pedido {numero_pedido} creado para {cliente_numero} en tenant {tenant_id}')
            
            # Enviar email de confirmación
            self._enviar_email_confirmacion(tenant_id, numero_pedido, items, total, cliente_numero)
            
            return {
                "id": pedido_id,
                "numero_pedido": numero_pedido,
                "secuencial": secuencial,
                "cliente_numero": cliente_numero,
                "items": items,
                "total": total,
                "estado": "nuevo"
            }
        except Exception as e:
            logger.error(f'Error creando pedido: {e}')
            raise
    
    def _enviar_email_confirmacion(self, tenant_id: str, numero_pedido: str, items: list, total: int, cliente_numero: str):
        """Envía email de confirmación al dueño del negocio"""
        try:
            from utils.email_brevo import email_sender
            from tenants.repository import tenant_repo
            
            tenant = tenant_repo.find_by_id(tenant_id)
            if not tenant:
                logger.error(f"Tenant no encontrado: {tenant_id}")
                return
            
            # Obtener email del dueño del negocio
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT u.email FROM public.usuarios u
                        JOIN public.usuario_negocio un ON u.id = un.usuario_id
                        WHERE un.tenant_id = %s AND un.rol_id = 1
                    """, (tenant_id,))
                    row = cur.fetchone()
                    if row:
                        email_to = row[0]
                        logger.info(f"Enviando email de confirmación a {email_to} para pedido {numero_pedido}")
                        email_sender.enviar_confirmacion_pedido(email_to, tenant['nombre'], numero_pedido, items, total, cliente_numero)
                    else:
                        logger.error(f"No se encontró email del dueño para tenant {tenant_id}")
        except Exception as e:
            logger.error(f'Error enviando email de confirmación: {e}')
    
    def _enviar_email_actualizacion(self, tenant_id: str, numero_pedido: str, estado: str):
        """Envía email de actualización de pedido"""
        try:
            from utils.email_brevo import email_sender
            from tenants.repository import tenant_repo
            
            tenant = tenant_repo.find_by_id(tenant_id)
            if not tenant:
                return
            
            # Obtener email del dueño del negocio
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT u.email FROM public.usuarios u
                        JOIN public.usuario_negocio un ON u.id = un.usuario_id
                        WHERE un.tenant_id = %s AND un.rol_id = 1
                    """, (tenant_id,))
                    row = cur.fetchone()
                    if row:
                        email_to = row[0]
                        email_sender.enviar_actualizacion_pedido(email_to, tenant['nombre'], numero_pedido, estado)
        except Exception as e:
            logger.error(f'Error enviando email de actualización: {e}')
    
    def get_pendientes(self, tenant_id: str, cliente_numero: str):
        """Obtiene pedidos pendientes del cliente (nuevos o pendiente_pago)"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                self._verificar_columnas_pedidos(tenant_id, conn)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT * FROM {tenant_id}.pedidos
                        WHERE cliente_numero = %s AND estado IN ('nuevo', 'pendiente_pago')
                        ORDER BY created_at DESC
                    """, (cliente_numero,))
                    rows = cur.fetchall()
                    columns = [desc[0] for desc in cur.description]
                    pedidos = []
                    for row in rows:
                        pedido = dict(zip(columns, row))
                        if pedido.get('items') and isinstance(pedido['items'], str):
                            try:
                                pedido['items'] = json.loads(pedido['items'])
                            except:
                                pedido['items'] = []
                        pedidos.append(pedido)
                    return pedidos
        except Exception as e:
            logger.error(f'Error obteniendo pedidos pendientes: {e}')
            return []
    
    def marcar_pagado(self, tenant_id: str, cliente_numero: str) -> int:
        """Marca pedidos como pagados y envía email"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                self._verificar_columnas_pedidos(tenant_id, conn)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT numero_pedido FROM {tenant_id}.pedidos
                        WHERE cliente_numero = %s AND estado IN ('nuevo', 'pendiente_pago')
                        ORDER BY created_at DESC LIMIT 1
                    """, (cliente_numero,))
                    row = cur.fetchone()
                    numero_pedido = row[0] if row else None
                    
                    cur.execute(f"""
                        UPDATE {tenant_id}.pedidos
                        SET estado = 'pagado', pagado_at = NOW(), updated_at = NOW()
                        WHERE cliente_numero = %s AND estado IN ('nuevo', 'pendiente_pago')
                    """, (cliente_numero,))
                    updated = cur.rowcount
                
                conn.commit()
            
            if updated > 0 and numero_pedido:
                self._enviar_email_actualizacion(tenant_id, numero_pedido, 'pagado')
                logger.info(f'{updated} pedido(s) marcado(s) como pagado para {cliente_numero}')
            elif updated > 0:
                logger.info(f'{updated} pedido(s) marcado(s) como pagado para {cliente_numero} (sin número de pedido)')
            
            return updated
            
        except Exception as e:
            logger.error(f'Error marcando pedido como pagado: {e}')
            raise
    
    def actualizar_estado(self, tenant_id: str, pedido_id: str, nuevo_estado: str) -> bool:
        """Actualiza el estado de un pedido específico y envía email"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                self._verificar_columnas_pedidos(tenant_id, conn)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT numero_pedido FROM {tenant_id}.pedidos WHERE id = %s", (pedido_id,))
                    row = cur.fetchone()
                    numero_pedido = row[0] if row else None
                    
                    fecha_campo = {
                        'pagado': 'pagado_at',
                        'enviado': 'enviado_at',
                        'cancelado': 'cancelado_at'
                    }.get(nuevo_estado)
                    
                    if fecha_campo:
                        cur.execute(f"""
                            UPDATE {tenant_id}.pedidos 
                            SET estado = %s, updated_at = NOW(), {fecha_campo} = NOW()
                            WHERE id = %s
                        """, (nuevo_estado, pedido_id))
                    else:
                        cur.execute(f"""
                            UPDATE {tenant_id}.pedidos 
                            SET estado = %s, updated_at = NOW()
                            WHERE id = %s
                        """, (nuevo_estado, pedido_id))
                    
                    updated = cur.rowcount
                conn.commit()
            
            if updated > 0 and numero_pedido:
                self._enviar_email_actualizacion(tenant_id, numero_pedido, nuevo_estado)
            
            return updated > 0
        except Exception as e:
            logger.error(f'Error actualizando estado del pedido: {e}')
            raise
    
    def get_all(self, tenant_id: str, limit: int = 100):
        """Obtiene todos los pedidos del tenant"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT * FROM {tenant_id}.pedidos
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))
                    rows = cur.fetchall()
                    columns = [desc[0] for desc in cur.description]
                    pedidos = []
                    for row in rows:
                        pedido = dict(zip(columns, row))
                        if pedido.get('items') and isinstance(pedido['items'], str):
                            try:
                                pedido['items'] = json.loads(pedido['items'])
                            except:
                                pedido['items'] = []
                        pedidos.append(pedido)
                    return pedidos
        except Exception as e:
            logger.error(f'Error obteniendo pedidos: {e}')
            return []

    def get_by_numero(self, tenant_id: str, numero_pedido: str) -> dict:
        """Obtiene un pedido por su número"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT * FROM {tenant_id}.pedidos
                        WHERE numero_pedido = %s
                        LIMIT 1
                    """, (numero_pedido,))
                    row = cur.fetchone()
                    if row:
                        columns = [desc[0] for desc in cur.description]
                        pedido = dict(zip(columns, row))
                        if pedido.get('items') and isinstance(pedido['items'], str):
                            try:
                                pedido['items'] = json.loads(pedido['items'])
                            except:
                                pedido['items'] = []
                        return pedido
                    return None
        except Exception as e:
            logger.error(f'Error obteniendo pedido por número: {e}')
            return None


# ==================== TENANT REPOSITORY ====================

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
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    # Insertar con todos los campos requeridos
                    cur.execute("""
                        INSERT INTO public.tenants (
                            id, nombre, tipo_negocio, schema_name, phone_id, token, 
                            usar_ia, configuracion, created_at, activo
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                        RETURNING id
                    """, (tenant_id, nombre, tipo_negocio, tenant_id, phone_id, token, usar_ia, '{}', True))
                    result = cur.fetchone()
                    conn.commit()
                    
                    if result:
                        # Crear esquema para el tenant
                        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {tenant_id}")
                        conn.commit()
                        
                        logger.info(f"Tenant creado: {tenant_id} - {nombre}")
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


# ==================== INSTANCIAS GLOBALES ====================

order_repo = OrderRepository()
tenant_repo = TenantRepository()