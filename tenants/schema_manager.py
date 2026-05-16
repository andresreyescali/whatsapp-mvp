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
                
                # 1. Tabla de clientes
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS {tenant_id}.clientes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    numero_telefono TEXT UNIQUE NOT NULL,
                    nombre TEXT,
                    cc TEXT,
                    email TEXT,
                    direccion TEXT,
                    direccion_despacho TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    ultimo_pedido TIMESTAMP
                )
                ''')
                
                # 2. Tabla de productos (adaptable por tipo de negocio)
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
                
                # 3. Tabla de pedidos
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS {tenant_id}.pedidos (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    cliente_id UUID REFERENCES {tenant_id}.clientes(id) ON DELETE SET NULL,
                    numero_pedido TEXT UNIQUE,
                    items JSONB NOT NULL,
                    total INTEGER NOT NULL,
                    estado VARCHAR(50) DEFAULT 'nuevo',
                    direccion_entrega TEXT,
                    notas TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    pagado_at TIMESTAMP,
                    enviado_at TIMESTAMP,
                    cancelado_at TIMESTAMP
                )
                ''')
                
                # 4. Tabla de conversaciones
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS {tenant_id}.conversaciones (
                    id SERIAL PRIMARY KEY,
                    cliente_id UUID REFERENCES {tenant_id}.clientes(id) ON DELETE SET NULL,
                    cliente_numero TEXT NOT NULL,
                    mensaje TEXT NOT NULL,
                    respuesta TEXT,
                    tipo VARCHAR(20) DEFAULT 'cliente',
                    created_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 5. Tabla de carritos
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS {tenant_id}.carritos (
                    id SERIAL PRIMARY KEY,
                    cliente_id UUID REFERENCES {tenant_id}.clientes(id) ON DELETE SET NULL,
                    cliente_numero TEXT NOT NULL,
                    items JSONB DEFAULT '[]',
                    total INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 6. Índices
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_pedidos_cliente ON {tenant_id}.pedidos(cliente_id)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_pedidos_estado ON {tenant_id}.pedidos(estado)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_pedidos_created ON {tenant_id}.pedidos(created_at DESC)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_clientes_telefono ON {tenant_id}.clientes(numero_telefono)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_conversaciones_cliente ON {tenant_id}.conversaciones(cliente_numero)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_conversaciones_created ON {tenant_id}.conversaciones(created_at DESC)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_carritos_cliente ON {tenant_id}.carritos(cliente_numero)')
                
                # 7. Insertar menú/productos de ejemplo según el tipo de negocio
                self._insert_default_products(cur, tenant_id, tipo_negocio)
                
            conn.commit()
        
        logger.info(f'Schema creado exitosamente para {tenant_id}')
    
    def _insert_default_products(self, cursor, tenant_id: str, tipo_negocio: str):
        """Inserta productos de ejemplo según el tipo de negocio"""
        
        if tipo_negocio == "restaurante":
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Pizza Margarita', 'Salsa de tomate, mozzarella, albahaca fresca', 25000, 'pizzas'),
                ('Pizza Pepperoni', 'Pepperoni italiano, queso mozzarella', 32000, 'pizzas'),
                ('Hamburguesa Clásica', 'Carne de res, lechuga, tomate', 18000, 'hamburguesas'),
                ('Gaseosa', 'Bebida 500ml', 5000, 'bebidas')
            ''')
        
        elif tipo_negocio == "panaderia":
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Pan Francés', 'Pan crujiente recién horneado', 800, 'panes'),
                ('Croissant', 'Hojaldre de mantequilla', 2500, 'pastelería'),
                ('Pan de Queso', 'Bocadito de queso y almidón', 1500, 'panes')
            ''')
        
        elif tipo_negocio == "pasteleria":
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Torta de Chocolate', '3 capas de chocolate belga', 45000, 'tortas'),
                ('Cheesecake', 'Queso crema con frutos rojos', 12000, 'postres'),
                ('Galletas Artesanales', 'Surtido de 12 galletas', 8000, 'galletas')
            ''')
        
        elif tipo_negocio == "inmobiliaria":
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Apartamento 2 hab', 'Apartamento de 65m², 2 habitaciones, 1 baño, sala-comedor', 250000000, 'apartamentos'),
                ('Apartamento 3 hab', 'Apartamento de 85m², 3 habitaciones, 2 baños, balcón', 320000000, 'apartamentos'),
                ('Casa 4 hab', 'Casa de 150m², 4 habitaciones, 3 baños, jardín', 450000000, 'casas'),
                ('Oficina', 'Oficina de 40m² en zona comercial', 120000000, 'comercial'),
                ('Local Comercial', 'Local de 80m², excelente ubicación', 280000000, 'comercial')
            ''')
        
        elif tipo_negocio == "venta_autos":
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Sedán Económico', 'Auto nuevo, 4 puertas, aire acondicionado, dirección asistida', 45000000, 'sedanes'),
                ('SUV Familiar', 'SUV 5 puertas, 7 asientos, cámara reversa, sensor de parqueo', 85000000, 'suvs'),
                ('Camioneta 4x4', 'Camioneta doble cabina, 4x4, diesel', 120000000, 'camionetas'),
                ('Hatchback', 'Auto compacto, económico en combustible', 38000000, 'hatchbacks'),
                ('Deportivo', 'Auto deportivo, motor 2.0 turbo', 150000000, 'deportivos')
            ''')
        
        elif tipo_negocio == "venta_motos":
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Scooter 125cc', 'Moto automática, ideal para ciudad', 6500000, 'scooters'),
                ('Naked 200cc', 'Moto naked, diseño moderno, frenos ABS', 9500000, 'naked'),
                ('Enduro 250cc', 'Moto doble propósito, para ciudad y carretera', 12500000, 'enduro'),
                ('Deportiva 300cc', 'Moto deportiva, alta velocidad', 18000000, 'deportivas'),
                ('Scooter Eléctrica', 'Moto eléctrica, cero emisiones', 8500000, 'electricas')
            ''')
        
        else:  # otros
            cursor.execute(f'''
            INSERT INTO {tenant_id}.productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Producto 1', 'Descripción del producto 1', 10000, 'general'),
                ('Producto 2', 'Descripción del producto 2', 20000, 'general')
            ''')
    
    def get_menu(self, tenant_id: str):
        """Obtiene el menú completo del tenant"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT id, nombre, descripcion, precio, categoria, disponible FROM {tenant_id}.productos WHERE disponible = true ORDER BY categoria, nombre")
                    rows = cur.fetchall()
                    productos = []
                    for row in rows:
                        productos.append({
                            'id': row[0],
                            'nombre': row[1],
                            'descripcion': row[2] or '',
                            'precio': row[3],
                            'categoria': row[4] or 'general',
                            'disponible': row[5] if row[5] is not None else True
                        })
                    return productos
        except Exception as e:
            logger.error(f'Error obteniendo menú: {e}')
            return []
    
    def get_product(self, tenant_id: str, product_id: str):
        """Obtiene un producto específico por ID"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT * FROM {tenant_id}.productos WHERE id = %s", (product_id,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'id': row[0],
                            'nombre': row[1],
                            'descripcion': row[2],
                            'precio': row[3],
                            'categoria': row[4],
                            'disponible': row[5]
                        }
                    return None
        except Exception as e:
            logger.error(f'Error obteniendo producto {product_id}: {e}')
            return None
    
    def add_product(self, tenant_id: str, nombre: str, precio: int, descripcion: str = "", categoria: str = "general"):
        """Agrega un producto al menú"""
        try:
            product_id = str(uuid.uuid4())
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
            logger.error(f'Error agregando producto: {e}')
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

schema_manager = SchemaManager()