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
                ('Hamburguesa BBQ', 'Carne de res, salsa BBQ, aros de cebolla, queso cheddar', 22000, 'hamburguesas'),
                ('Gaseosa', 'Bebida 500ml (Cola, Naranja, Limón)', 5000, 'bebidas'),
                ('Jugo Natural', 'Jugo de frutas naturales 500ml', 7000, 'bebidas'),
                ('Papas Fritas', 'Papas crujientes con salsa especial', 8000, 'acompañamientos'),
                ('Porción de Torta', 'Porción individual de torta', 9000, 'postres')
            ''')
        elif tipo_negocio == "panaderia":
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Pan Francés', 'Pan crujiente recién horneado', 800, 'panes'),
                ('Croissant', 'Hojaldre de mantequilla', 2500, 'pastelería'),
                ('Pan de Queso', 'Bocadito de queso y almidón', 1500, 'panes'),
                ('Pan Integral', 'Pan con semillas y granos', 1200, 'panes'),
                ('Pastel de Chocolate', 'Porción individual de pastel de chocolate', 3500, 'pastelería')
            ''')
        elif tipo_negocio == "pasteleria":
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Torta de Chocolate', '3 capas de chocolate belga con cobertura', 45000, 'tortas'),
                ('Cheesecake', 'Queso crema con frutos rojos', 12000, 'postres'),
                ('Galletas Artesanales', 'Surtido de 12 galletas', 8000, 'galletas'),
                ('Cupcakes', 'Pack de 6 cupcakes surtidos', 15000, 'cupcakes'),
                ('Brownies', 'Brownies de chocolate con nueces', 5000, 'postres')
            ''')
    
    def get_menu(self, tenant_id: str):
        """Obtiene el menú completo de un tenant"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(f"SELECT * FROM {tenant_id}.productos WHERE disponible = true ORDER BY categoria, nombre")
                    productos = cur.fetchall()
                    return [dict(p) for p in productos]
        except Exception as e:
            logger.error(f'Error obteniendo menú para {tenant_id}: {e}')
            return []
    
    def get_product(self, tenant_id: str, product_id: str):
        """Obtiene un producto específico por ID"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(f"SELECT * FROM {tenant_id}.productos WHERE id = %s", (product_id,))
                    product = cur.fetchone()
                    return dict(product) if product else None
        except Exception as e:
            logger.error(f'Error obteniendo producto {product_id}: {e}')
            return None
    
    def add_product(self, tenant_id: str, nombre: str, precio: int, descripcion: str = "", categoria: str = "general"):
        """Agrega un producto al menú del tenant"""
        try:
            product_id = str(uuid.uuid4())
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO {tenant_id}.productos (id, nombre, descripcion, precio, categoria)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                    """, (product_id, nombre, descripcion, precio, categoria))
                    result = cur.fetchone()
                    product_id = result[0]
                conn.commit()
            logger.info(f'Producto agregado: {nombre} (ID: {product_id}) para tenant {tenant_id}')
            return product_id
        except Exception as e:
            logger.error(f'Error agregando producto para {tenant_id}: {e}')
            raise
    
    def update_product(self, tenant_id: str, product_id: str, nombre: str = None, descripcion: str = None, 
                      precio: int = None, categoria: str = None, disponible: bool = None):
        """Actualiza un producto existente"""
        try:
            updates = []
            params = []
            
            if nombre is not None:
                updates.append("nombre = %s")
                params.append(nombre)
            if descripcion is not None:
                updates.append("descripcion = %s")
                params.append(descripcion)
            if precio is not None:
                updates.append("precio = %s")
                params.append(precio)
            if categoria is not None:
                updates.append("categoria = %s")
                params.append(categoria)
            if disponible is not None:
                updates.append("disponible = %s")
                params.append(disponible)
            
            if not updates:
                return False
            
            params.append(product_id)
            query = f"UPDATE {tenant_id}.productos SET {', '.join(updates)} WHERE id = %s"
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    updated = cur.rowcount
                conn.commit()
            
            logger.info(f'Producto {product_id} actualizado para tenant {tenant_id}')
            return updated > 0
        except Exception as e:
            logger.error(f'Error actualizando producto {product_id}: {e}')
            raise
    
    def delete_product(self, tenant_id: str, product_id: str):
        """Elimina un producto del menú (borrado físico)"""
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
    
    def disable_product(self, tenant_id: str, product_id: str):
        """Deshabilita un producto (borrado lógico)"""
        return self.update_product(tenant_id, product_id, disponible=False)
    
    def enable_product(self, tenant_id: str, product_id: str):
        """Habilita un producto"""
        return self.update_product(tenant_id, product_id, disponible=True)
    
    def get_products_by_category(self, tenant_id: str, categoria: str):
        """Obtiene productos por categoría"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(f"SELECT * FROM {tenant_id}.productos WHERE categoria = %s AND disponible = true", (categoria,))
                    return [dict(p) for p in cur.fetchall()]
        except Exception as e:
            logger.error(f'Error obteniendo productos por categoría: {e}')
            return []
    
    def search_products(self, tenant_id: str, query: str):
        """Busca productos por nombre o descripción"""
        try:
            search_term = f"%{query.lower()}%"
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(f"""
                        SELECT * FROM {tenant_id}.productos 
                        WHERE (LOWER(nombre) LIKE %s OR LOWER(descripcion) LIKE %s) 
                        AND disponible = true
                    """, (search_term, search_term))
                    return [dict(p) for p in cur.fetchall()]
        except Exception as e:
            logger.error(f'Error buscando productos: {e}')
            return []
    
    def get_pedidos(self, tenant_id: str, limit: int = 50):
        """Obtiene los pedidos del tenant"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(f"""
                        SELECT * FROM {tenant_id}.pedidos 
                        ORDER BY created_at DESC 
                        LIMIT %s
                    """, (limit,))
                    return [dict(p) for p in cur.fetchall()]
        except Exception as e:
            logger.error(f'Error obteniendo pedidos: {e}')
            return []
    
    def get_pedidos_pendientes(self, tenant_id: str, cliente_numero: str = None):
        """Obtiene pedidos pendientes de pago"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    if cliente_numero:
                        cur.execute(f"""
                            SELECT * FROM {tenant_id}.pedidos 
                            WHERE estado = 'pendiente_pago' AND cliente_numero = %s
                            ORDER BY created_at DESC
                        """, (cliente_numero,))
                    else:
                        cur.execute(f"""
                            SELECT * FROM {tenant_id}.pedidos 
                            WHERE estado = 'pendiente_pago'
                            ORDER BY created_at DESC
                        """)
                    return [dict(p) for p in cur.fetchall()]
        except Exception as e:
            logger.error(f'Error obteniendo pedidos pendientes: {e}')
            return []


# Instancia global
schema_manager = SchemaManager()