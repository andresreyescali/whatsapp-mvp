import uuid
import json
from core.database import db_manager
from core.logger import logger

class OrderRepository:
    """Gestión de pedidos por tenant"""
    
    def create(self, tenant_id: str, cliente_numero: str, producto_nombre: str, precio: int) -> dict:
        """Crea un nuevo pedido"""
        pedido_id = str(uuid.uuid4())
        
        items = [{"nombre": producto_nombre, "precio": precio, "cantidad": 1}]
        total = precio
        
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO {tenant_id}.pedidos (id, cliente_numero, items, total, estado)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (pedido_id, cliente_numero, json.dumps(items), total, "pendiente_pago"))
                conn.commit()
            
            logger.info(f'Pedido creado: {pedido_id} para {cliente_numero} en tenant {tenant_id}')
            
            return {
                "id": pedido_id,
                "cliente_numero": cliente_numero,
                "items": items,
                "total": total,
                "estado": "pendiente_pago"
            }
        except Exception as e:
            logger.error(f'Error creando pedido: {e}')
            raise
    
    def marcar_pagado(self, tenant_id: str, cliente_numero: str) -> int:
        """Marca pedidos como pagados"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        UPDATE {tenant_id}.pedidos
                        SET estado = 'pagado'
                        WHERE cliente_numero = %s AND estado = 'pendiente_pago'
                    """, (cliente_numero,))
                    updated = cur.rowcount
                conn.commit()
            
            if updated > 0:
                logger.info(f'{updated} pedido(s) marcado(s) como pagado para {cliente_numero}')
            return updated
        except Exception as e:
            logger.error(f'Error marcando pedido como pagado: {e}')
            raise
    
    def get_pendientes(self, tenant_id: str, cliente_numero: str):
        """Obtiene pedidos pendientes del cliente"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT * FROM {tenant_id}.pedidos
                        WHERE cliente_numero = %s AND estado = 'pendiente_pago'
                        ORDER BY created_at DESC
                    """, (cliente_numero,))
                    rows = cur.fetchall()
                    
                    # Obtener columnas
                    columns = [desc[0] for desc in cur.description]
                    pedidos = []
                    for row in rows:
                        pedido = dict(zip(columns, row))
                        # Convertir items JSON si es necesario
                        if pedido.get('items') and isinstance(pedido['items'], str):
                            pedido['items'] = json.loads(pedido['items'])
                        pedidos.append(pedido)
                    
                    return pedidos
        except Exception as e:
            logger.error(f'Error obteniendo pedidos pendientes: {e}')
            return []
    
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
                            pedido['items'] = json.loads(pedido['items'])
                        pedidos.append(pedido)
                    
                    return pedidos
        except Exception as e:
            logger.error(f'Error obteniendo pedidos: {e}')
            return []

# Instancia global
order_repo = OrderRepository()