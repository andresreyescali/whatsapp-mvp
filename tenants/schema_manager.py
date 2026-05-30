from core.database import db_manager
from core.logger import logger
import uuid
import json

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
                
                # 2. Tabla de productos/servicios (ACTUALIZADA con metadata)
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".productos (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    precio INTEGER NOT NULL,
                    categoria TEXT,
                    disponible BOOLEAN DEFAULT true,
                    imagen_url TEXT,
                    tiempo_preparacion INTEGER,
                    destacado BOOLEAN DEFAULT false,
                    metadata JSONB DEFAULT '{{"personalizaciones": [], "adicionales": []}}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 3. Tabla de pedidos
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
                
                # 5. Tabla de carritos
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
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_destacado ON "{schema_name}".productos(destacado) WHERE destacado = true')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_metadata ON "{schema_name}".productos USING gin(metadata)')
                
                if tipo_negocio in ['hotel', 'agencia_viajes']:
                    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_reservas_cliente ON "{schema_name}".reservas(cliente_id)')
                    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_reservas_fechas ON "{schema_name}".reservas(fecha_inicio, fecha_fin)')
                
                # Insertar productos de ejemplo
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
                    self._add_missing_columns(schema_name, cur)
                    conn.commit()
                    logger.info(f"Esquema asegurado para tenant {tenant_id} (schema: {schema_name})")
        except Exception as e:
            logger.error(f"Error asegurando esquema para {tenant_id}: {e}")
            raise
    
    def _add_missing_columns(self, schema_name: str, cur):
        """Agrega columnas faltantes a la tabla productos si es necesario (migración)"""
        # Verificar y agregar columna imagen_url
        cur.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = %s AND table_name = 'productos' AND column_name = 'imagen_url'
        """, (schema_name,))
        if not cur.fetchone():
            logger.info(f"Agregando columna imagen_url a {schema_name}.productos")
            cur.execute(f'ALTER TABLE "{schema_name}".productos ADD COLUMN imagen_url TEXT')
        
        # Verificar y agregar columna tiempo_preparacion
        cur.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = %s AND table_name = 'productos' AND column_name = 'tiempo_preparacion'
        """, (schema_name,))
        if not cur.fetchone():
            logger.info(f"Agregando columna tiempo_preparacion a {schema_name}.productos")
            cur.execute(f'ALTER TABLE "{schema_name}".productos ADD COLUMN tiempo_preparacion INTEGER')
        
        # Verificar y agregar columna destacado
        cur.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = %s AND table_name = 'productos' AND column_name = 'destacado'
        """, (schema_name,))
        if not cur.fetchone():
            logger.info(f"Agregando columna destacado a {schema_name}.productos")
            cur.execute(f'ALTER TABLE "{schema_name}".productos ADD COLUMN destacado BOOLEAN DEFAULT false')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_destacado ON "{schema_name}".productos(destacado) WHERE destacado = true')
        
        # Verificar y agregar columna metadata (JSONB para personalizaciones y adicionales)
        cur.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = %s AND table_name = 'productos' AND column_name = 'metadata'
        """, (schema_name,))
        if not cur.fetchone():
            logger.info(f"Agregando columna metadata a {schema_name}.productos")
            cur.execute(f'ALTER TABLE "{schema_name}".productos ADD COLUMN metadata JSONB DEFAULT \'{{"personalizaciones": [], "adicionales": []}}\'::jsonb')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_metadata ON "{schema_name}".productos USING gin(metadata)')
        
        # Verificar y agregar columna updated_at
        cur.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = %s AND table_name = 'productos' AND column_name = 'updated_at'
        """, (schema_name,))
        if not cur.fetchone():
            logger.info(f"Agregando columna updated_at a {schema_name}.productos")
            cur.execute(f'ALTER TABLE "{schema_name}".productos ADD COLUMN updated_at TIMESTAMP DEFAULT NOW()')
    
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
            imagen_url TEXT,
            tiempo_preparacion INTEGER,
            destacado BOOLEAN DEFAULT false,
            metadata JSONB DEFAULT '{{"personalizaciones": [], "adicionales": []}}'::jsonb,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
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
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_destacado ON "{schema_name}".productos(destacado) WHERE destacado = true')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_metadata ON "{schema_name}".productos USING gin(metadata)')
    
    def _insert_default_products(self, cursor, schema_name: str, tipo_negocio: str):
        """Inserta productos/servicios de ejemplo según el tipo de negocio"""
        
        cursor.execute(f'SELECT COUNT(*) FROM "{schema_name}".productos')
        count = cursor.fetchone()[0]
        if count > 0:
            logger.info(f"Ya existen {count} productos en {schema_name}, omitiendo inserción de productos de ejemplo")
            return
        
        # Productos por defecto con metadata de ejemplo
        if tipo_negocio == "restaurante":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria, destacado, tiempo_preparacion, metadata)
            VALUES 
                ('Pizza Margarita', 'Salsa de tomate, mozzarella, albahaca fresca', 25000, 'pizzas', true, 15, '{{"personalizaciones": [{{"nombre": "Tamaño", "opciones": ["Pequeño", "Mediano", "Grande"], "requerido": true, "multiple": false}}], "adicionales": [{{"nombre": "Queso extra", "precio_extra": 3000, "multiple": false}}, {{"nombre": "Pepperoni", "precio_extra": 4000, "multiple": false}}]}}'),
                ('Pizza Pepperoni', 'Pepperoni italiano, queso mozzarella', 32000, 'pizzas', false, 15, '{{"personalizaciones": [{{"nombre": "Tamaño", "opciones": ["Pequeño", "Mediano", "Grande"], "requerido": true, "multiple": false}}], "adicionales": [{{"nombre": "Queso extra", "precio_extra": 3000, "multiple": false}}]}}'),
                ('Hamburguesa Clásica', 'Carne de res, lechuga, tomate', 18000, 'hamburguesas', true, 10, '{{"personalizaciones": [{{"nombre": "Tipo de carne", "opciones": ["Res", "Pollo", "Vegetariana"], "requerido": true, "multiple": false}}, {{"nombre": "Salsa", "opciones": ["Mayonesa", "Ketchup", "Mostaza", "BBQ"], "requerido": false, "multiple": true}}], "adicionales": [{{"nombre": "Tocineta", "precio_extra": 2500, "multiple": false}}, {{"nombre": "Huevo", "precio_extra": 2000, "multiple": false}}]}}'),
                ('Gaseosa', 'Bebida 500ml', 5000, 'bebidas', false, 2, '{{"personalizaciones": [{{"nombre": "Sabor", "opciones": ["Cola", "Naranja", "Lima"], "requerido": true, "multiple": false}}], "adicionales": []}}')
            ''')
        else:
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria, destacado, tiempo_preparacion, metadata)
            VALUES 
                ('Producto 1', 'Descripción del producto 1', 10000, 'general', true, 10, '{{"personalizaciones": [], "adicionales": []}}'),
                ('Producto 2', 'Descripción del producto 2', 20000, 'general', false, 15, '{{"personalizaciones": [], "adicionales": []}}')
            ''')
    
    def get_menu(self, tenant_id: str):
        """Obtiene el menú completo del tenant con todos los campos incluyendo metadata"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible,
                               imagen_url, tiempo_preparacion, destacado, metadata, created_at
                        FROM "{schema_name}".productos 
                        ORDER BY destacado DESC, disponible DESC, categoria, nombre
                    """)
                    rows = cur.fetchall()
                    productos = []
                    for row in rows:
                        metadata = row[9] if row[9] else {}
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except:
                                metadata = {}
                        if not metadata.get('personalizaciones'):
                            metadata['personalizaciones'] = []
                        if not metadata.get('adicionales'):
                            metadata['adicionales'] = []
                        
                        productos.append({
                            'id': str(row[0]),
                            'nombre': row[1],
                            'descripcion': row[2] or '',
                            'precio': row[3],
                            'categoria': row[4] or 'general',
                            'disponible': row[5],
                            'imagen_url': row[6],
                            'tiempo_preparacion': row[7],
                            'destacado': row[8] if row[8] is not None else False,
                            'personalizaciones': metadata.get('personalizaciones', []),
                            'adicionales': metadata.get('adicionales', [])
                        })
                    return productos
        except Exception as e:
            logger.error(f'Error obteniendo menú: {e}')
            return []
    
    def get_product(self, tenant_id: str, product_id: str):
        """Obtiene un producto específico por ID con todos los campos incluyendo metadata"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT * FROM "{schema_name}".productos WHERE id = %s', (product_id,))
                    row = cur.fetchone()
                    if row:
                        metadata = row[9] if len(row) > 9 and row[9] else {}
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except:
                                metadata = {}
                        if not metadata.get('personalizaciones'):
                            metadata['personalizaciones'] = []
                        if not metadata.get('adicionales'):
                            metadata['adicionales'] = []
                        
                        return {
                            'id': str(row[0]),
                            'nombre': row[1],
                            'descripcion': row[2],
                            'precio': row[3],
                            'categoria': row[4],
                            'disponible': row[5],
                            'imagen_url': row[6],
                            'tiempo_preparacion': row[7],
                            'destacado': row[8] if row[8] is not None else False,
                            'personalizaciones': metadata.get('personalizaciones', []),
                            'adicionales': metadata.get('adicionales', [])
                        }
                    return None
        except Exception as e:
            logger.error(f'Error obteniendo producto {product_id}: {e}')
            return None
    
    def add_product(self, tenant_id: str, nombre: str, precio: int, descripcion: str = "", 
                    categoria: str = "general", imagen_url: str = None, 
                    tiempo_preparacion: int = None, destacado: bool = False,
                    personalizaciones: list = None, adicionales: list = None):
        """Agrega un producto al menú con personalizaciones y adicionales"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            product_id = str(uuid.uuid4())
            
            metadata = {
                'personalizaciones': personalizaciones or [],
                'adicionales': adicionales or []
            }
            metadata_json = json.dumps(metadata)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Verificar si ya existe un producto con el mismo nombre
                    cur.execute(f'SELECT id FROM "{schema_name}".productos WHERE nombre ILIKE %s', (nombre,))
                    existing = cur.fetchone()
                    
                    if existing:
                        # Actualizar producto existente
                        cur.execute(f"""
                            UPDATE "{schema_name}".productos 
                            SET nombre = %s, descripcion = %s, precio = %s, categoria = %s, 
                                imagen_url = %s, tiempo_preparacion = %s, destacado = %s,
                                disponible = true, metadata = %s, updated_at = NOW()
                            WHERE nombre ILIKE %s
                            RETURNING id
                        """, (nombre, descripcion, precio, categoria, imagen_url, tiempo_preparacion, destacado, metadata_json, nombre))
                        result_id = cur.fetchone()[0]
                        logger.info(f'Producto actualizado: {nombre}')
                    else:
                        # Insertar nuevo producto
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".productos 
                            (id, nombre, descripcion, precio, categoria, disponible, 
                             imagen_url, tiempo_preparacion, destacado, metadata)
                            VALUES (%s, %s, %s, %s, %s, true, %s, %s, %s, %s)
                            RETURNING id
                        """, (product_id, nombre, descripcion, precio, categoria, imagen_url, tiempo_preparacion, destacado, metadata_json))
                        result_id = cur.fetchone()[0]
                        logger.info(f'Producto agregado: {nombre}')
                    
                    conn.commit()
                    return result_id
        except Exception as e:
            logger.error(f'Error agregando producto: {e}')
            raise
        
    def update_product(self, tenant_id: str, product_id: str, nombre: str = None, descripcion: str = None, 
                      precio: int = None, categoria: str = None, disponible: bool = None,
                      imagen_url: str = None, tiempo_preparacion: int = None, destacado: bool = None,
                      personalizaciones: list = None, adicionales: list = None):
        """Actualiza un producto existente con todos los campos incluyendo metadata"""
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
            if imagen_url is not None:
                updates.append("imagen_url = %s")
                params.append(imagen_url)
            if tiempo_preparacion is not None:
                updates.append("tiempo_preparacion = %s")
                params.append(tiempo_preparacion)
            if destacado is not None:
                updates.append("destacado = %s")
                params.append(destacado)
            
            # Manejar metadata (personalizaciones y adicionales)
            if personalizaciones is not None or adicionales is not None:
                # Obtener metadata actual para preservar lo que no se está actualizando
                cur.execute(f'SELECT metadata FROM "{schema_name}".productos WHERE id = %s', (product_id,))
                row = cur.fetchone()
                current_metadata = row[0] if row and row[0] else {}
                if isinstance(current_metadata, str):
                    try:
                        current_metadata = json.loads(current_metadata)
                    except:
                        current_metadata = {}
                
                if personalizaciones is not None:
                    current_metadata['personalizaciones'] = personalizaciones
                if adicionales is not None:
                    current_metadata['adicionales'] = adicionales
                
                updates.append("metadata = %s")
                params.append(json.dumps(current_metadata))
            
            if not updates:
                return False
            
            updates.append("updated_at = NOW()")
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
    
    def get_featured_products(self, tenant_id: str, limit: int = 10):
        """Obtiene los productos destacados del tenant"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, imagen_url, 
                               tiempo_preparacion, destacado, metadata
                        FROM "{schema_name}".productos 
                        WHERE destacado = true AND disponible = true
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))
                    rows = cur.fetchall()
                    productos = []
                    for row in rows:
                        metadata = row[8] if row[8] else {}
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except:
                                metadata = {}
                        
                        productos.append({
                            'id': str(row[0]),
                            'nombre': row[1],
                            'descripcion': row[2] or '',
                            'precio': row[3],
                            'categoria': row[4] or 'general',
                            'imagen_url': row[5],
                            'tiempo_preparacion': row[6],
                            'destacado': row[7],
                            'personalizaciones': metadata.get('personalizaciones', []),
                            'adicionales': metadata.get('adicionales', [])
                        })
                    return productos
        except Exception as e:
            logger.error(f'Error obteniendo productos destacados: {e}')
            return []


# Instancia global
schema_manager = SchemaManager()