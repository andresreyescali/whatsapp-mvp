from core.database import db_manager
from core.logger import logger
import uuid

class SchemaManager:
    """Gestiona esquemas y tablas de tenants"""
    
    def create_tenant_schema(self, tenant_id: str, tipo_negocio: str):
        """Crea schema y tablas para un nuevo tenant"""
        logger.info(f'Creando schema para tenant {tenant_id} (tipo: {tipo_negocio})')
        
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                # Crear schema
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS {tenant_id}')
                
                # Tabla de productos
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS {tenant_id}.productos (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    precio INTEGER NOT NULL,
                    categoria TEXT,
                    disponible BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # Tabla de pedidos
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
                
                # Insertar menú de ejemplo
                self._insert_default_menu(cur, tenant_id, tipo_negocio)
                
            conn.commit()
        
        logger.info(f'Schema creado exitosamente para {tenant_id}')
    
    def _insert_default_menu(self, cursor, tenant_id: str, tipo_negocio: str):
        """Inserta menú de ejemplo según tipo de negocio"""
        
        if tipo_negocio == "restaurante":
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Pizza Margarita', 'Salsa de tomate, mozzarella, albahaca fresca', 25000, 'pizzas'),
                ('Pizza Pepperoni', 'Pepperoni italiano, queso mozzarella, salsa de tomate', 32000, 'pizzas'),
                ('Hamburguesa Clásica', 'Carne de res, lechuga, tomate, cebolla, salsa especial', 18000, 'hamburguesas'),
                ('Gaseosa', 'Bebida 500ml (Cola, Naranja, Limón)', 5000, 'bebidas')
            ''')
    
    def get_menu(self, tenant_id: str):
        """Obtiene el menú completo de un tenant - Sin dict_row"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT id, nombre, descripcion, precio, categoria, disponible FROM {tenant_id}.productos WHERE disponible = true ORDER BY categoria, nombre")
                    rows = cur.fetchall()
                    # Convertir manualmente a lista de diccionarios
                    productos = []
                    for row in rows:
                        productos.append({
                            'id': row[0],
                            'nombre': row[1],
                            'descripcion': row[2],
                            'precio': row[3],
                            'categoria': row[4],
                            'disponible': row[5]
                        })
                    return productos
        except Exception as e:
            logger.error(f'Error obteniendo menú para {tenant_id}: {e}')
            return []
    
    def add_product(self, tenant_id: str, nombre: str, precio: int, descripcion: str = "", categoria: str = "general"):
        """Agrega un producto al menú del tenant"""
        try:
            product_id = str(uuid.uuid4())
            logger.info(f'Conectando a tenant {tenant_id} para agregar producto')
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO {tenant_id}.productos (id, nombre, descripcion, precio, categoria)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (product_id, nombre, descripcion, precio, categoria))
                conn.commit()
            
            logger.info(f'Producto agregado: {nombre} (ID: {product_id}) para tenant {tenant_id}')
            return product_id
        except Exception as e:
            logger.error(f'Error agregando producto para {tenant_id}: {e}')
            raise
    
    def delete_product(self, tenant_id: str, product_id: str):
        """Elimina un producto del menú"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"DELETE FROM {tenant_id}.productos WHERE id = %s", (product_id,))
                    deleted = cur.rowcount
                conn.commit()
            
            if deleted > 0:
                logger.info(f'Producto {product_id} eliminado para tenant {tenant_id}')
            return deleted > 0
        except Exception as e:
            logger.error(f'Error eliminando producto {product_id}: {e}')
            raise

# Instancia global
schema_manager = SchemaManager()