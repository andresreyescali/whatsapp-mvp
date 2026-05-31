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
                
                # 2. Tabla de productos (productos base + adicionales)
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
                    es_base BOOLEAN DEFAULT true,
                    metadata JSONB DEFAULT '{{"personalizaciones": [], "adicionales": []}}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 3. Tabla de relación producto-adicionales (NUEVA)
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".producto_adicionales (
                    id SERIAL PRIMARY KEY,
                    producto_id UUID REFERENCES "{schema_name}".productos(id) ON DELETE CASCADE,
                    adicional_id UUID REFERENCES "{schema_name}".productos(id) ON DELETE CASCADE,
                    cantidad_maxima INTEGER DEFAULT 1,
                    cantidad_minima INTEGER DEFAULT 0,
                    predeterminado BOOLEAN DEFAULT false,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(producto_id, adicional_id)
                )
                ''')
                
                # 4. Tabla de personalizaciones globales (NUEVA)
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".personalizaciones (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    tipo TEXT DEFAULT 'texto',
                    opciones JSONB,
                    requerido BOOLEAN DEFAULT false,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 5. Tabla de relación producto-personalizaciones (NUEVA)
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".producto_personalizaciones (
                    id SERIAL PRIMARY KEY,
                    producto_id UUID REFERENCES "{schema_name}".productos(id) ON DELETE CASCADE,
                    personalizacion_id INTEGER REFERENCES "{schema_name}".personalizaciones(id) ON DELETE CASCADE,
                    orden INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(producto_id, personalizacion_id)
                )
                ''')
                
                # 6. Tabla de pedidos
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
                
                # 7. Tabla de conversaciones
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
                
                # 8. Tabla de carritos
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
                
                # 9. Tabla de reservas (específica para hotel y viajes)
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
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_es_base ON "{schema_name}".productos(es_base)')
                
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
                    self._add_new_tables(schema_name, cur)
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
        
        # Verificar y agregar columna metadata
        cur.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = %s AND table_name = 'productos' AND column_name = 'metadata'
        """, (schema_name,))
        if not cur.fetchone():
            logger.info(f"Agregando columna metadata a {schema_name}.productos")
            cur.execute(f'ALTER TABLE "{schema_name}".productos ADD COLUMN metadata JSONB DEFAULT \'{{"personalizaciones": [], "adicionales": []}}\'::jsonb')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_metadata ON "{schema_name}".productos USING gin(metadata)')
        
        # Verificar y agregar columna es_base
        cur.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = %s AND table_name = 'productos' AND column_name = 'es_base'
        """, (schema_name,))
        if not cur.fetchone():
            logger.info(f"Agregando columna es_base a {schema_name}.productos")
            cur.execute(f'ALTER TABLE "{schema_name}".productos ADD COLUMN es_base BOOLEAN DEFAULT true')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_es_base ON "{schema_name}".productos(es_base)')
        
        # Verificar y agregar columna updated_at
        cur.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = %s AND table_name = 'productos' AND column_name = 'updated_at'
        """, (schema_name,))
        if not cur.fetchone():
            logger.info(f"Agregando columna updated_at a {schema_name}.productos")
            cur.execute(f'ALTER TABLE "{schema_name}".productos ADD COLUMN updated_at TIMESTAMP DEFAULT NOW()')
    
    def _add_new_tables(self, schema_name: str, cur):
        """Agrega nuevas tablas si no existen (migración)"""
        
        # Tabla producto_adicionales
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema_name}".producto_adicionales (
                id SERIAL PRIMARY KEY,
                producto_id UUID REFERENCES "{schema_name}".productos(id) ON DELETE CASCADE,
                adicional_id UUID REFERENCES "{schema_name}".productos(id) ON DELETE CASCADE,
                cantidad_maxima INTEGER DEFAULT 1,
                cantidad_minima INTEGER DEFAULT 0,
                predeterminado BOOLEAN DEFAULT false,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(producto_id, adicional_id)
            )
        """)
        
        # Tabla personalizaciones
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema_name}".personalizaciones (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                tipo TEXT DEFAULT 'texto',
                opciones JSONB,
                requerido BOOLEAN DEFAULT false,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Tabla producto_personalizaciones
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema_name}".producto_personalizaciones (
                id SERIAL PRIMARY KEY,
                producto_id UUID REFERENCES "{schema_name}".productos(id) ON DELETE CASCADE,
                personalizacion_id INTEGER REFERENCES "{schema_name}".personalizaciones(id) ON DELETE CASCADE,
                orden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(producto_id, personalizacion_id)
            )
        """)
        
        # Índices para nuevas tablas
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_prod_adic_producto ON "{schema_name}".producto_adicionales(producto_id)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_prod_adic_adicional ON "{schema_name}".producto_adicionales(adicional_id)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_prod_perso_producto ON "{schema_name}".producto_personalizaciones(producto_id)')
    
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
            es_base BOOLEAN DEFAULT true,
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
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_productos_es_base ON "{schema_name}".productos(es_base)')
    
    def _insert_default_products(self, cursor, schema_name: str, tipo_negocio: str):
        """Inserta productos/servicios de ejemplo según el tipo de negocio"""
        
        cursor.execute(f'SELECT COUNT(*) FROM "{schema_name}".productos')
        count = cursor.fetchone()[0]
        if count > 0:
            logger.info(f"Ya existen {count} productos en {schema_name}, omitiendo inserción de productos de ejemplo")
            return
        
        if tipo_negocio == "pasteleria":
            # Productos base (tortas)
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (id, nombre, descripcion, precio, categoria, destacado, es_base, tiempo_preparacion, metadata) VALUES
                (gen_random_uuid(), 'Torta de Chocolate', 'Deliciosa torta de chocolate con cobertura', 45000, 'tortas', true, true, 120, '{{"personalizaciones": [], "adicionales": []}}'),
                (gen_random_uuid(), 'Torta de Vainilla', 'Torta esponjosa de vainilla', 40000, 'tortas', false, true, 90, '{{"personalizaciones": [], "adicionales": []}}'),
                (gen_random_uuid(), 'Torta Red Velvet', 'Torta de terciopelo rojo con queso crema', 55000, 'tortas', true, true, 120, '{{"personalizaciones": [], "adicionales": []}}')
            ''')
            
            # Adicionales
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (id, nombre, descripcion, precio, categoria, disponible, es_base, metadata) VALUES
                (gen_random_uuid(), 'Fondant', 'Cobertura de fondant', 15000, 'adicionales', true, false, '{{"personalizaciones": [], "adicionales": []}}'),
                (gen_random_uuid(), 'Número de cumpleaños', 'Número en dorado', 5000, 'adicionales', true, false, '{{"personalizaciones": [], "adicionales": []}}'),
                (gen_random_uuid(), 'Nombre en la base', 'Texto personalizado en la base', 8000, 'adicionales', true, false, '{{"personalizaciones": [], "adicionales": []}}'),
                (gen_random_uuid(), 'Caja Especial', 'Caja decorativa para torta', 12000, 'adicionales', true, false, '{{"personalizaciones": [], "adicionales": []}}'),
                (gen_random_uuid(), 'Velas', 'Set de velas de colores', 3000, 'adicionales', true, false, '{{"personalizaciones": [], "adicionales": []}}')
            ''')
            
            # Personalizaciones
            cursor.execute(f'''
            INSERT INTO "{schema_name}".personalizaciones (nombre, tipo, opciones, requerido) VALUES
                ('Color del fondant', 'select', '["Rojo","Azul","Verde","Rosado","Amarillo"]'::jsonb, false),
                ('Mensaje personalizado', 'texto', null, true),
                ('Tipo de letra', 'select', '["Cursiva","Redonda","Manuscrita","Impronta"]'::jsonb, false)
            ''')
            
            # Relaciones producto-adicional (obtener IDs dinámicamente)
            cursor.execute(f'''
            DO $$
            DECLARE
                torta_id UUID;
                adicional_fondant_id UUID;
                adicional_numero_id UUID;
                adicional_nombre_id UUID;
                adicional_caja_id UUID;
                adicional_velas_id UUID;
            BEGIN
                SELECT id INTO torta_id FROM "{schema_name}".productos WHERE nombre = 'Torta de Chocolate' LIMIT 1;
                SELECT id INTO adicional_fondant_id FROM "{schema_name}".productos WHERE nombre = 'Fondant' LIMIT 1;
                SELECT id INTO adicional_numero_id FROM "{schema_name}".productos WHERE nombre = 'Número de cumpleaños' LIMIT 1;
                SELECT id INTO adicional_nombre_id FROM "{schema_name}".productos WHERE nombre = 'Nombre en la base' LIMIT 1;
                SELECT id INTO adicional_caja_id FROM "{schema_name}".productos WHERE nombre = 'Caja Especial' LIMIT 1;
                SELECT id INTO adicional_velas_id FROM "{schema_name}".productos WHERE nombre = 'Velas' LIMIT 1;
                
                IF torta_id IS NOT NULL THEN
                    IF adicional_fondant_id IS NOT NULL THEN
                        INSERT INTO "{schema_name}".producto_adicionales (producto_id, adicional_id) VALUES (torta_id, adicional_fondant_id) ON CONFLICT DO NOTHING;
                    END IF;
                    IF adicional_numero_id IS NOT NULL THEN
                        INSERT INTO "{schema_name}".producto_adicionales (producto_id, adicional_id) VALUES (torta_id, adicional_numero_id) ON CONFLICT DO NOTHING;
                    END IF;
                    IF adicional_nombre_id IS NOT NULL THEN
                        INSERT INTO "{schema_name}".producto_adicionales (producto_id, adicional_id) VALUES (torta_id, adicional_nombre_id) ON CONFLICT DO NOTHING;
                    END IF;
                    IF adicional_caja_id IS NOT NULL THEN
                        INSERT INTO "{schema_name}".producto_adicionales (producto_id, adicional_id) VALUES (torta_id, adicional_caja_id) ON CONFLICT DO NOTHING;
                    END IF;
                    IF adicional_velas_id IS NOT NULL THEN
                        INSERT INTO "{schema_name}".producto_adicionales (producto_id, adicional_id, cantidad_maxima) VALUES (torta_id, adicional_velas_id, 10) ON CONFLICT DO NOTHING;
                    END IF;
                END IF;
            END $$;
            ''')
        
        elif tipo_negocio == "restaurante":
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria, destacado, tiempo_preparacion, es_base, metadata)
            VALUES 
                ('Pizza Margarita', 'Salsa de tomate, mozzarella, albahaca fresca', 25000, 'pizzas', true, 15, true, '{{"personalizaciones": [], "adicionales": []}}'),
                ('Pizza Pepperoni', 'Pepperoni italiano, queso mozzarella', 32000, 'pizzas', false, 15, true, '{{"personalizaciones": [], "adicionales": []}}'),
                ('Hamburguesa Clásica', 'Carne de res, lechuga, tomate', 18000, 'hamburguesas', true, 10, true, '{{"personalizaciones": [], "adicionales": []}}'),
                ('Gaseosa', 'Bebida 500ml', 5000, 'bebidas', false, 2, true, '{{"personalizaciones": [], "adicionales": []}}'),
                ('Queso extra', 'Porción de queso adicional', 3000, 'adicionales', true, 2, false, '{{"personalizaciones": [], "adicionales": []}}'),
                ('Tocineta', 'Tiras de tocineta crujiente', 2500, 'adicionales', true, 3, false, '{{"personalizaciones": [], "adicionales": []}}')
            ''')
        else:
            cursor.execute(f'''
            INSERT INTO "{schema_name}".productos (nombre, descripcion, precio, categoria, destacado, tiempo_preparacion, es_base, metadata)
            VALUES 
                ('Producto Base 1', 'Descripción del producto base', 10000, 'general', true, 10, true, '{{"personalizaciones": [], "adicionales": []}}'),
                ('Producto Base 2', 'Descripción del producto base', 20000, 'general', false, 15, true, '{{"personalizaciones": [], "adicionales": []}}'),
                ('Adicional 1', 'Complemento opcional', 1500, 'adicionales', false, 0, false, '{{"personalizaciones": [], "adicionales": []}}'),
                ('Adicional 2', 'Otro complemento', 2500, 'adicionales', false, 0, false, '{{"personalizaciones": [], "adicionales": []}}')
            ''')
    
    # ==================== MÉTODOS EXISTENTES (MANTENIDOS) ====================
    
    def get_menu(self, tenant_id: str):
        """Obtiene el menú completo del tenant con todos los campos incluyendo metadata"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible,
                               imagen_url, tiempo_preparacion, destacado, metadata, es_base, created_at
                        FROM "{schema_name}".productos 
                        ORDER BY es_base DESC, destacado DESC, disponible DESC, categoria, nombre
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
                            'es_base': row[10] if len(row) > 10 and row[10] is not None else True,
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
                            'es_base': row[10] if len(row) > 10 and row[10] is not None else True,
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
                    es_base: bool = True, personalizaciones: list = None, adicionales: list = None):
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
                                es_base = %s, disponible = true, metadata = %s, updated_at = NOW()
                            WHERE nombre ILIKE %s
                            RETURNING id
                        """, (nombre, descripcion, precio, categoria, imagen_url, tiempo_preparacion, destacado, es_base, metadata_json, nombre))
                        result_id = cur.fetchone()[0]
                        logger.info(f'Producto actualizado: {nombre}')
                    else:
                        # Insertar nuevo producto
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".productos 
                            (id, nombre, descripcion, precio, categoria, disponible, 
                             imagen_url, tiempo_preparacion, destacado, es_base, metadata)
                            VALUES (%s, %s, %s, %s, %s, true, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, (product_id, nombre, descripcion, precio, categoria, imagen_url, tiempo_preparacion, destacado, es_base, metadata_json))
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
                      es_base: bool = None, personalizaciones: list = None, adicionales: list = None):
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
            if es_base is not None:
                updates.append("es_base = %s")
                params.append(es_base)
            
            # Manejar metadata (personalizaciones y adicionales)
            if personalizaciones is not None or adicionales is not None:
                with db_manager.get_connection(tenant_id) as conn:
                    with conn.cursor() as cur2:
                        cur2.execute(f'SELECT metadata FROM "{schema_name}".productos WHERE id = %s', (product_id,))
                        row = cur2.fetchone()
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
                        WHERE destacado = true AND disponible = true AND es_base = true
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
    
    # ==================== NUEVOS MÉTODOS PARA ADICIONALES Y PERSONALIZACIONES ====================
    
    def get_productos_base(self, tenant_id: str):
        """Obtiene solo los productos base (no adicionales)"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, imagen_url, 
                               tiempo_preparacion, destacado, disponible
                        FROM "{schema_name}".productos 
                        WHERE es_base = true AND disponible = true
                        ORDER BY destacado DESC, nombre
                    """)
                    rows = cur.fetchall()
                    return [{
                        'id': str(row[0]),
                        'nombre': row[1],
                        'descripcion': row[2] or '',
                        'precio': row[3],
                        'categoria': row[4] or 'general',
                        'imagen_url': row[5],
                        'tiempo_preparacion': row[6],
                        'destacado': row[7] if row[7] else False,
                        'disponible': row[8]
                    } for row in rows]
        except Exception as e:
            logger.error(f'Error obteniendo productos base: {e}')
            return []
    
    def get_adicionales_producto(self, tenant_id: str, producto_id: str):
        """Obtiene los adicionales disponibles para un producto base"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT a.id, a.nombre, a.descripcion, a.precio, 
                               pa.cantidad_maxima, pa.cantidad_minima, pa.predeterminado
                        FROM "{schema_name}".producto_adicionales pa
                        JOIN "{schema_name}".productos a ON pa.adicional_id = a.id
                        WHERE pa.producto_id = %s AND a.disponible = true
                        ORDER BY a.nombre
                    """, (producto_id,))
                    rows = cur.fetchall()
                    return [{
                        'id': str(row[0]),
                        'nombre': row[1],
                        'descripcion': row[2] or '',
                        'precio': row[3],
                        'cantidad_maxima': row[4],
                        'cantidad_minima': row[5],
                        'predeterminado': row[6] if row[6] else False
                    } for row in rows]
        except Exception as e:
            logger.error(f'Error obteniendo adicionales: {e}')
            return []
    
    def get_personalizaciones_producto(self, tenant_id: str, producto_id: str):
        """Obtiene las personalizaciones requeridas para un producto base"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT p.id, p.nombre, p.tipo, p.opciones, p.requerido
                        FROM "{schema_name}".producto_personalizaciones pp
                        JOIN "{schema_name}".personalizaciones p ON pp.personalizacion_id = p.id
                        WHERE pp.producto_id = %s
                        ORDER BY pp.orden
                    """, (producto_id,))
                    rows = cur.fetchall()
                    return [{
                        'id': row[0],
                        'nombre': row[1],
                        'tipo': row[2],
                        'opciones': row[3] if row[3] else [],
                        'requerido': row[4] if row[4] else False
                    } for row in rows]
        except Exception as e:
            logger.error(f'Error obteniendo personalizaciones: {e}')
            return []
    
    def get_todos_adicionales(self, tenant_id: str):
        """Obtiene todos los adicionales disponibles (para administración)"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, disponible, categoria
                        FROM "{schema_name}".productos 
                        WHERE es_base = false
                        ORDER BY nombre
                    """)
                    rows = cur.fetchall()
                    return [{
                        'id': str(row[0]),
                        'nombre': row[1],
                        'descripcion': row[2] or '',
                        'precio': row[3],
                        'disponible': row[4],
                        'categoria': row[5] or 'adicionales'
                    } for row in rows]
        except Exception as e:
            logger.error(f'Error obteniendo adicionales: {e}')
            return []
    
    def calcular_precio_con_adicionales(self, tenant_id: str, producto_id: str, adicionales_ids: list, cantidades: dict = None):
        """Calcula el precio total de un producto base más sus adicionales"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            total = 0
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Precio del producto base
                    cur.execute(f'SELECT precio FROM "{schema_name}".productos WHERE id = %s', (producto_id,))
                    row = cur.fetchone()
                    if row:
                        total += row[0]
                    
                    # Precio de los adicionales
                    if adicionales_ids:
                        cur.execute(f"""
                            SELECT id, precio FROM "{schema_name}".productos 
                            WHERE id = ANY(%s) AND es_base = false
                        """, (adicionales_ids,))
                        for row in cur.fetchall():
                            adicional_id = str(row[0])
                            precio = row[1]
                            cantidad = cantidades.get(adicional_id, 1) if cantidades else 1
                            total += precio * cantidad
            
            return total
        except Exception as e:
            logger.error(f'Error calculando precio: {e}')
            return 0


# Instancia global
schema_manager = SchemaManager()