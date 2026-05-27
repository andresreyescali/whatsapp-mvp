from core.database import db_manager
from core.logger import logger
import uuid

class SchemaManager:
    """Gestiona esquemas y tablas de tenants"""
    
    def _get_schema_name(self, tenant_id: str) -> str:
        """Obtiene el schema_name de un tenant"""
        try:
            from tenants.repository import tenant_repo
            tenant = tenant_repo.find_by_id(tenant_id)
            if tenant and tenant.get('schema_name'):
                return tenant['schema_name']
        except Exception as e:
            logger.error(f"Error obteniendo schema_name: {e}")
        return f"tenant_{tenant_id.replace('-', '_')}"
    
    def create_tenant_schema(self, tenant_id: str, tipo_negocio: str):
        """Crea schema y tablas para un nuevo tenant"""
        logger.info(f'Creando schema para tenant {tenant_id} (tipo: {tipo_negocio})')
        
        schema_name = self._get_schema_name(tenant_id)
        
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
                
                # 1. Tabla de clientes
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".clientes (
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
                
                # 2. Tabla de productos/servicios
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".productos (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    precio INTEGER NOT NULL,
                    categoria TEXT,
                    disponible BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 3. Tabla de pedidos (CORREGIDA - con secuencial)
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".pedidos (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    cliente_id UUID REFERENCES "{schema_name}".clientes(id) ON DELETE SET NULL,
                    cliente_numero TEXT NOT NULL,
                    numero_pedido TEXT UNIQUE,
                    secuencial INTEGER,
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
                CREATE TABLE IF NOT EXISTS "{schema_name}".conversaciones (
                    id SERIAL PRIMARY KEY,
                    cliente_id UUID REFERENCES "{schema_name}".clientes(id) ON DELETE SET NULL,
                    cliente_numero TEXT NOT NULL,
                    mensaje TEXT NOT NULL,
                    respuesta TEXT,
                    tipo VARCHAR(20) DEFAULT 'cliente',
                    created_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 5. Tabla de carritos (CORREGIDA - con UNIQUE constraint)
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".carritos (
                    id SERIAL PRIMARY KEY,
                    cliente_numero TEXT NOT NULL UNIQUE,
                    items JSONB NOT NULL DEFAULT '[]',
                    total INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 6. Tabla de reservas (específica para hotel y viajes)
                if tipo_negocio in ['hotel', 'agencia_viajes']:
                    cur.execute(f'''
                    CREATE TABLE IF NOT EXISTS "{schema_name}".reservas (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        cliente_id UUID REFERENCES "{schema_name}".clientes(id) ON DELETE SET NULL,
                        cliente_numero TEXT NOT NULL,
                        servicio TEXT NOT NULL,
                        fecha_inicio DATE NOT NULL,
                        fecha_fin DATE,
                        personas INTEGER DEFAULT 1,
                        habitaciones INTEGER DEFAULT 1,
                        destino TEXT,
                        total INTEGER NOT NULL,
                        estado VARCHAR(50) DEFAULT 'pendiente',
                        notas TEXT,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                    ''')
                
                # Índices
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_pedidos_cliente ON "{schema_name}".pedidos(cliente_id)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_pedidos_estado ON "{schema_name}".pedidos(estado)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_pedidos_numero ON "{schema_name}".pedidos(numero_pedido)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_clientes_telefono ON "{schema_name}".clientes(numero_telefono)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_conversaciones_cliente ON "{schema_name}".conversaciones(cliente_numero)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_carritos_cliente ON "{schema_name}".carritos(cliente_numero)')
                
                if tipo_negocio in ['hotel', 'agencia_viajes']:
                    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_reservas_cliente ON "{schema_name}".reservas(cliente_id)')
                    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_reservas_fechas ON "{schema_name}".reservas(fecha_inicio, fecha_fin)')
                
                # Insertar productos/servicios de ejemplo según el tipo de negocio
                self._insert_default_products(cur, schema_name, tipo_negocio)
                
            conn.commit()
        
        logger.info(f'Schema creado exitosamente para {tenant_id}')
    
    def ensure_schema(self, tenant_id: str):
        """Asegura que el esquema del tenant existe y tiene todas las tablas necesarias"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
                    self._ensure_tables_exist(schema_name, cur)
                    conn.commit()
                    logger.info(f"Esquema asegurado para tenant {tenant_id} (schema: {schema_name})")
        except Exception as e:
            logger.error(f"Error asegurando esquema para {tenant_id}: {e}")
            raise
            
    def _ensure_tables_exist(self, schema_name: str, cur):
        """Verifica y crea las tablas necesarias si no existen"""
        
        cur.execute(f'''
        CREATE TABLE IF NOT EXISTS "{schema_name}".clientes (
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
        
        cur.execute(f'''
        CREATE TABLE IF NOT EXISTS "{schema_name}".productos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            nombre TEXT NOT NULL,
            descripcion TEXT,
            precio INTEGER NOT NULL,
            categoria TEXT,
            disponible BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT NOW()
        )
        ''')
        
        cur.execute(f'''
        CREATE TABLE IF NOT EXISTS "{schema_name}".pedidos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cliente_id UUID REFERENCES "{schema_name}".clientes(id) ON DELETE SET NULL,
            cliente_numero TEXT NOT NULL,
            numero_pedido TEXT UNIQUE,
            secuencial INTEGER,
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
        
        cur.execute(f'''
        CREATE TABLE IF NOT EXISTS "{schema_name}".conversaciones (
            id SERIAL PRIMARY KEY,
            cliente_id UUID REFERENCES "{schema_name}".clientes(id) ON DELETE SET NULL,
            cliente_numero TEXT NOT NULL,
            mensaje TEXT NOT NULL,
            respuesta TEXT,
            tipo VARCHAR(20) DEFAULT 'cliente',
            created_at TIMESTAMP DEFAULT NOW()
        )
        ''')
        
        cur.execute(f'''
        CREATE TABLE IF NOT EXISTS "{schema_name}".carritos (
            id SERIAL PRIMARY KEY,
            cliente_numero TEXT NOT NULL UNIQUE,
            items JSONB NOT NULL DEFAULT '[]',
            total INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        ''')
        
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_pedidos_cliente ON "{schema_name}".pedidos(cliente_id)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_pedidos_estado ON "{schema_name}".pedidos(estado)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_pedidos_numero ON "{schema_name}".pedidos(numero_pedido)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_clientes_telefono ON "{schema_name}".clientes(numero_telefono)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_conversaciones_cliente ON "{schema_name}".conversaciones(cliente_numero)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_carritos_cliente ON "{schema_name}".carritos(cliente_numero)')
    
    def _insert_default_products(self, cursor, schema_name: str, tipo_negocio: str):
        """Inserta productos/servicios de ejemplo según el tipo de negocio"""
        
        cursor.execute(f'SELECT COUNT(*) FROM "{schema_name}".productos')
        count = cursor.fetchone()[0]
        if count > 0:
            logger.info(f"Ya existen {count} productos en {schema_name}, omitiendo inserción de productos de ejemplo")
            return
        
        if tipo_negocio == "restaurante":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Pizza Margarita', 'Salsa de tomate, mozzarella, albahaca fresca', 25000, 'pizzas'),
                ('Pizza Pepperoni', 'Pepperoni italiano, queso mozzarella', 32000, 'pizzas'),
                ('Hamburguesa Clásica', 'Carne de res, lechuga, tomate', 18000, 'hamburguesas'),
                ('Gaseosa', 'Bebida 500ml', 5000, 'bebidas')
            ''')
        
        elif tipo_negocio == "panaderia":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Pan Francés', 'Pan crujiente recién horneado', 800, 'panes'),
                ('Croissant', 'Hojaldre de mantequilla', 2500, 'pastelería'),
                ('Pan de Queso', 'Bocadito de queso y almidón', 1500, 'panes')
            ''')
        
        elif tipo_negocio == "pasteleria":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Torta de Chocolate', '3 capas de chocolate belga', 45000, 'tortas'),
                ('Cheesecake', 'Queso crema con frutos rojos', 12000, 'postres'),
                ('Galletas Artesanales', 'Surtido de 12 galletas', 8000, 'galletas')
            ''')
        
        elif tipo_negocio == "inmobiliaria":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Apartamento 2 hab', 'Apartamento de 65m², 2 habitaciones, 1 baño, sala-comedor', 250000000, 'apartamentos'),
                ('Apartamento 3 hab', 'Apartamento de 85m², 3 habitaciones, 2 baños, balcón', 320000000, 'apartamentos'),
                ('Casa 4 hab', 'Casa de 150m², 4 habitaciones, 3 baños, jardín', 450000000, 'casas'),
                ('Oficina', 'Oficina de 40m² en zona comercial', 120000000, 'comercial'),
                ('Local Comercial', 'Local de 80m², excelente ubicación', 280000000, 'comercial')
            ''')
        
        elif tipo_negocio == "venta_autos":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Sedán Económico', 'Auto nuevo, 4 puertas, aire acondicionado, dirección asistida', 45000000, 'sedanes'),
                ('SUV Familiar', 'SUV 5 puertas, 7 asientos, cámara reversa, sensor de parqueo', 85000000, 'suvs'),
                ('Camioneta 4x4', 'Camioneta doble cabina, 4x4, diesel', 120000000, 'camionetas'),
                ('Hatchback', 'Auto compacto, económico en combustible', 38000000, 'hatchbacks'),
                ('Deportivo', 'Auto deportivo, motor 2.0 turbo', 150000000, 'deportivos')
            ''')
        
        elif tipo_negocio == "venta_motos":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Scooter 125cc', 'Moto automática, ideal para ciudad', 6500000, 'scooters'),
                ('Naked 200cc', 'Moto naked, diseño moderno, frenos ABS', 9500000, 'naked'),
                ('Enduro 250cc', 'Moto doble propósito, para ciudad y carretera', 12500000, 'enduro'),
                ('Deportiva 300cc', 'Moto deportiva, alta velocidad', 18000000, 'deportivas'),
                ('Scooter Eléctrica', 'Moto eléctrica, cero emisiones', 8500000, 'electricas')
            ''')
        
        elif tipo_negocio == "hotel":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Habitación Simple', 'Habitación individual, baño privado, WiFi', 150000, 'habitaciones'),
                ('Habitación Doble', 'Habitación para 2 personas, cama queen, baño privado', 200000, 'habitaciones'),
                ('Habitación Suite', 'Suite de lujo, jacuzzi, vista panorámica', 350000, 'habitaciones'),
                ('Desayuno Buffet', 'Desayuno americano incluido', 25000, 'servicios'),
                ('Lavandería', 'Servicio de lavandería por kilo', 15000, 'servicios'),
                ('Traslado Aeropuerto', 'Transporte ida y vuelta', 80000, 'servicios'),
                ('Spa y Masajes', 'Acceso a spa y masaje relajante', 120000, 'servicios')
            ''')
        
        elif tipo_negocio == "agencia_viajes":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Paquete Cartagena', '3 noches en Cartagena, hotel playa, desayuno incluido', 850000, 'paquetes'),
                ('Paquete Santa Marta', '4 noches en Santa Marta, visita Tayrona', 950000, 'paquetes'),
                ('Paquete Medellín', '3 noches en Medellín, tour ciudad', 650000, 'paquetes'),
                ('Paquete San Andrés', '5 noches en San Andrés, todo incluido', 1500000, 'paquetes'),
                ('Seguro de Viaje', 'Asistencia médica y cancelación', 120000, 'servicios'),
                ('Alquiler de Auto', 'Auto compacto por día', 180000, 'servicios'),
                ('Tour Ciudad', 'Tour guiado por la ciudad', 80000, 'tours')
            ''')
        
        else:
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria)
            VALUES 
                ('Producto 1', 'Descripción del producto 1', 10000, 'general'),
                ('Producto 2', 'Descripción del producto 2', 20000, 'general')
            ''')
    
    def get_menu(self, tenant_id: str):
        """Obtiene el menú completo del tenant"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible 
                        FROM "{schema_name}".productos 
                        ORDER BY disponible DESC, categoria, nombre
                    """)
                    rows = cur.fetchall()
                    productos = []
                    for row in rows:
                        productos.append({
                            'id': str(row[0]),
                            'nombre': row[1],
                            'descripcion': row[2] or '',
                            'precio': row[3],
                            'categoria': row[4] or 'general',
                            'disponible': row[5]
                        })
                    return productos
        except Exception as e:
            logger.error(f'Error obteniendo menú: {e}')
            return []
    
    def get_product(self, tenant_id: str, product_id: str):
        """Obtiene un producto específico por ID"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT * FROM "{schema_name}".productos WHERE id = %s', (product_id,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'id': str(row[0]),
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
        """Agrega un producto al menú (evita duplicados usando UNIQUE constraint)"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            product_id = str(uuid.uuid4())
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Verificar si ya existe un producto con el mismo nombre
                    cur.execute(f'SELECT id FROM "{schema_name}".productos WHERE nombre ILIKE %s', (nombre,))
                    existing = cur.fetchone()
                    
                    if existing:
                        # Actualizar producto existente
                        cur.execute(f"""
                            UPDATE "{schema_name}".productos 
                            SET precio = %s, descripcion = %s, categoria = %s, disponible = true, updated_at = NOW()
                            WHERE nombre ILIKE %s
                            RETURNING id
                        """, (precio, descripcion, categoria, nombre))
                        result_id = cur.fetchone()[0]
                        logger.info(f'Producto actualizado: {nombre}')
                    else:
                        # Insertar nuevo producto
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".productos (id, nombre, descripcion, precio, categoria, disponible)
                            VALUES (%s, %s, %s, %s, %s, true)
                            RETURNING id
                        """, (product_id, nombre, descripcion, precio, categoria))
                        result_id = cur.fetchone()[0]
                        logger.info(f'Producto agregado: {nombre}')
                    
                    conn.commit()
                    return result_id
        except Exception as e:
            logger.error(f'Error agregando producto: {e}')
            raise
        
    def update_product(self, tenant_id: str, product_id: str, nombre: str = None, descripcion: str = None, 
                      precio: int = None, categoria: str = None, disponible: bool = None):
        """Actualiza un producto existente"""
        try:
            schema_name = self._get_schema_name(tenant_id)
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
            query = f'UPDATE "{schema_name}".productos SET {", ".join(updates)} WHERE id = %s'
            
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
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'DELETE FROM "{schema_name}".productos WHERE id = %s', (product_id,))
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