import uuid
import json
from core.database import db_manager

class OrderRepository:
    def create(self, tenant_id: str, cliente_numero: str, producto_nombre: str, precio: int):
        pedido_id = str(uuid.uuid4())
        items = [{'nombre': producto_nombre, 'precio': precio, 'cantidad': 1}]
        with db_manager.get_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(f'''
                    INSERT INTO {tenant_id}.pedidos (id, cliente_numero, items, total, estado)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (pedido_id, cliente_numero, json.dumps(items), precio, 'pendiente_pago'))
            conn.commit()
        return {'id': pedido_id, 'total': precio}

order_repo = OrderRepository()