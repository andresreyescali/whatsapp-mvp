import uuid
import json
from core.database import db_manager
from core.logger import logger

class OrderRepository:
    """Gestión de pedidos por tenant"""
    
    def create(self, tenant_id: str, cliente_numero: str, producto_nombre: str, precio: int, cantidad: int = 1) -> dict:
        """Crea un nuevo pedido con número compuesto"""
        pedido_id = str(uuid.uuid4())
        
        # Asegurar que las columnas existen
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(f"ALTER TABLE {tenant_id}.pedidos ADD COLUMN IF NOT EXISTS numero_pedido TEXT")
                    cur.execute(f"ALTER TABLE {tenant_id}.pedidos ADD COLUMN IF NOT EXISTS secuencial INTEGER")
                    conn.commit()
                except Exception as e:
                    logger.warning(f'Error agregando columnas (puede que ya existan): {e}')
        
        # Obtener el siguiente secuencial
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COALESCE(MAX(secuencial), 0) + 1 FROM {tenant_id}.pedidos")
                secuencial = cur.fetchone()[0]
        
        # Generar número compuesto
        numero_pedido = db_manager.generar_numero_pedido(tenant_id, secuencial)
        
        items = [{"nombre": producto_nombre, "precio": precio, "cantidad": cantidad}]
        total = precio * cantidad
        
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO {tenant_id}.pedidos (id, cliente_numero, items, total, estado, numero_pedido, secuencial)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
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
            with conn.cursor() as cur:
                # Asegurar que la columna numero_pedido existe
                try:
                    cur.execute(f"ALTER TABLE {tenant_id}.pedidos ADD COLUMN IF NOT EXISTS numero_pedido TEXT")
                    cur.execute(f"ALTER TABLE {tenant_id}.pedidos ADD COLUMN IF NOT EXISTS secuencial INTEGER")
                    cur.execute(f"ALTER TABLE {tenant_id}.pedidos ADD COLUMN IF NOT EXISTS pagado_at TIMESTAMP")
                except Exception as e:
                    logger.warning(f"Error agregando columnas (puede que ya existan): {e}")
                
                # Obtener el pedido antes de actualizar
                cur.execute(f"""
                    SELECT numero_pedido FROM {tenant_id}.pedidos
                    WHERE cliente_numero = %s AND estado IN ('nuevo', 'pendiente_pago')
                    ORDER BY created_at DESC LIMIT 1
                """, (cliente_numero,))
                row = cur.fetchone()
                numero_pedido = row[0] if row else None
                
                cur.execute(f"""
                    UPDATE {tenant_id}.pedidos
                    SET estado = 'pagado', pagado_at = NOW()
                    WHERE cliente_numero = %s AND estado IN ('nuevo', 'pendiente_pago')
                """, (cliente_numero,))
                updated = cur.rowcount
            conn.commit()
        
        if updated > 0 and numero_pedido:
            self._enviar_email_actualizacion(tenant_id, numero_pedido, 'pagado')
            logger.info(f'{updated} pedido(s) marcado(s) como pagado para {cliente_numero}')
        return updated
    except Exception as e:
        logger.error(f'Error marcando pedido como pagado: {e}')
        raise
            
    def actualizar_estado(self, tenant_id: str, pedido_id: str, nuevo_estado: str) -> bool:
        """Actualiza el estado de un pedido específico y envía email"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Obtener número de pedido antes de actualizar
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

order_repo = OrderRepository()