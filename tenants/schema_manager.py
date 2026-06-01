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
                
                # 3. Tabla de relación producto-adicionales
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
                
                # 4. Tabla de personalizaciones globales
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
                
                # 5. Tabla de relación producto-personalizaciones
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
                
                # 6. TABLA DE CONFIGURACIÓN DE PERSONALIZACIÓN (NUEVA)
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".configuracion_personalizacion (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    activo BOOLEAN DEFAULT true,
                    instrucciones_ia TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 7. TABLA DE ATRIBUTOS PERSONALIZABLES (NUEVA)
                cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{schema_name}".atributos_personalizacion (
                    id SERIAL PRIMARY KEY,
                    config_id INTEGER REFERENCES "{schema_name}".configuracion_personalizacion(id) ON DELETE CASCADE,
                    nombre TEXT NOT NULL,
                    tipo TEXT NOT NULL CHECK (tipo IN ('select', 'texto', 'numero', 'si_no')),
                    opciones JSONB,
                    pregunta TEXT NOT NULL,
                    requerido BOOLEAN DEFAULT true,
                    precio_extra JSONB,
                    orden INTEGER DEFAULT 0,
                    activo BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                ''')
                
                # 8. Tabla de pedidos
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
                
                # 9. Tabla de conversaciones
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
                
                # 10. Tabla de carritos
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
                
                # 11. Tabla de reservas (específica para hotel y viajes)
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
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_config_activo ON "{schema_name}".configuracion_personalizacion(activo)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_atributos_config ON "{schema_name}".atributos_personalizacion(config_id)')
                
                if tipo_negocio in ['hotel', 'agencia_viajes']:
                    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_reservas_cliente ON "{schema_name}".reservas(cliente_id)')
                    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_reservas_fechas ON "{schema_name}".reservas(fecha_inicio, fecha_fin)')
                
                # Insertar productos de ejemplo
                self._insert_default_products(cur, schema_name, tipo_negocio)
                
                # Insertar configuraciones de ejemplo según tipo de negocio
                self._insert_default_personalizacion_configs(cur, schema_name, tipo_negocio)
                
            conn.commit()
        
        logger.info(f'Schema creado exitosamente para {tenant_id}')
    
    def _insert_default_personalizacion_configs(self, cursor, schema_name: str, tipo_negocio: str):
        """Inserta configuraciones de personalización de ejemplo según tipo de negocio"""
        
        cursor.execute(f'SELECT COUNT(*) FROM "{schema_name}".configuracion_personalizacion')
        count = cursor.fetchone()[0]
        if count > 0:
            logger.info(f"Ya existen {count} configuraciones en {schema_name}, omitiendo inserción")
            return
        
        if tipo_negocio == "pasteleria":
            # Configuración para tortas personalizadas
            cursor.execute(f'''
            INSERT INTO "{schema_name}".configuracion_personalizacion (nombre, descripcion, instrucciones_ia) VALUES (
                'tortas',
                'Personalización de tortas decoradas',
                'El cliente puede personalizar tortas eligiendo sabor, tamaño, tipo de base, letreros, caja y mensaje especial. Cada atributo puede tener precio extra.'
            ) RETURNING id
            ''')
            config_id = cursor.fetchone()[0]
            
            # Atributos para tortas
            cursor.execute(f'''
            INSERT INTO "{schema_name}".atributos_personalizacion (config_id, nombre, tipo, opciones, pregunta, requerido, precio_extra, orden) VALUES
                ({config_id}, 'sabor', 'select', '["Vainilla Arequipe", "Amapola", "Naranja-Vainilla", "Chocolate/Milky Way", "Red Velvet", "Ponque Tradicional", "Torta Negra", "Manzana y Nueces", "Cookies & Cream"]', '¿Qué sabor te gustaría?', true, '{{"Vainilla Arequipe": 13000, "Amapola": 14000, "Naranja-Vainilla": 12000, "Chocolate/Milky Way": 14000, "Red Velvet": 14000, "Ponque Tradicional": 17500, "Torta Negra": 19000, "Manzana y Nueces": 17500, "Cookies & Cream": 14000}}', 1),
                ({config_id}, 'tamanio', 'select', '["Porción", "Cuarto", "Media", "Libra"]', '¿De qué tamaño la quieres? (Porción, Cuarto, Media o Libra)', true, '{{"factor": true, "valores": {{"Porción": 1, "Cuarto": 2.65, "Media": 4.6, "Libra": 8.4}}}}', 2),
                ({config_id}, 'base', 'select', '["Glaze", "Dorada", "Fondant", "Drip colores", "Drip dorado"]', '¿Qué tipo de base prefieres?', false, '{{"Fondant": 15000, "Drip colores": 7000, "Drip dorado": 10000}}', 3),
                ({config_id}, 'letrero', 'si_no', NULL, '¿Quieres agregar un letrero personalizado? (costo extra $8,000)', false, '{{"si": 8000}}', 4),
                ({config_id}, 'caja', 'si_no', NULL, '¿Necesitas caja especial? (costo extra $12,000)', false, '{{"si": 12000}}', 5),
                ({config_id}, 'mensaje', 'texto', NULL, '¿Quieres agregar un mensaje escrito en la torta?', false, NULL, 6)
            ''')
        
        elif tipo_negocio == "restaurante":
            # Configuración para arepas personalizadas
            cursor.execute(f'''
            INSERT INTO "{schema_name}".configuracion_personalizacion (nombre, descripcion, instrucciones_ia) VALUES (
                'arepas',
                'Personalización de arepas',
                'El cliente puede personalizar arepas eligiendo tipo de masa, relleno, salsas y acompañamientos.'
            ) RETURNING id
            ''')
            config_id = cursor.fetchone()[0]
            
            cursor.execute(f'''
            INSERT INTO "{schema_name}".atributos_personalizacion (config_id, nombre, tipo, opciones, pregunta, requerido, precio_extra, orden) VALUES
                ({config_id}, 'masa', 'select', '["Blanca", "Maíz", "Integral", "Gofio"]', '¿Qué tipo de masa prefieres para tu arepa?', true, NULL, 1),
                ({config_id}, 'relleno', 'select', '["Queso", "Carne mechada", "Pollo", "Chócolo", "Champiñones", "Mixto"]', '¿Qué relleno quieres?', true, '{{"Carne mechada": 3000, "Pollo": 3000, "Mixto": 5000}}', 2),
                ({config_id}, 'salsas', 'select', '["Salsa de ajo", "Tártara", "Picante", "Rosada", "Sin salsa"]', '¿Qué salsa prefieres?', false, NULL, 3),
                ({config_id}, 'extra_queso', 'si_no', NULL, '¿Quieres queso extra? (+$2,000)', false, '{{"si": 2000}}', 4)
            ''')
        
        elif tipo_negocio == "venta_autos":
            # Configuración para autos personalizados
            cursor.execute(f'''
            INSERT INTO "{schema_name}".configuracion_personalizacion (nombre, descripcion, instrucciones_ia) VALUES (
                'carros',
                'Personalización de autos',
                'El cliente puede personalizar autos eligiendo modelo, color, llantas, asientos y accesorios.'
            ) RETURNING id
            ''')
            config_id = cursor.fetchone()[0]
            
            cursor.execute(f'''
            INSERT INTO "{schema_name}".atributos_personalizacion (config_id, nombre, tipo, opciones, pregunta, requerido, precio_extra, orden) VALUES
                ({config_id}, 'modelo', 'select', '["Sedán", "SUV", "Deportivo", "Camioneta", "Hatchback"]', '¿Qué modelo de auto te interesa?', true, '{{"Deportivo": 15000000, "SUV": 5000000}}', 1),
                ({config_id}, 'color', 'select', '["Rojo", "Azul", "Negro", "Blanco", "Plateado", "Gris"]', '¿De qué color lo quieres?', true, NULL, 2),
                ({config_id}, 'llantas', 'select', '["Acero", "Aluminio", "Deportivas", "Negras mate"]', '¿Qué tipo de llantas prefieres?', false, '{{"Deportivas": 2500000, "Aluminio": 1500000}}', 3),
                ({config_id}, 'asientos', 'select', '["Tela", "Cuero", "Deportivos", "Calefaccionados"]', '¿Qué tipo de asientos quieres?', false, '{{"Cuero": 3000000, "Calefaccionados": 2000000}}', 4)
            ''')
    
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
        
        # Tabla configuracion_personalizacion (NUEVA)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema_name}".configuracion_personalizacion (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                activo BOOLEAN DEFAULT true,
                instrucciones_ia TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Tabla atributos_personalizacion (NUEVA)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema_name}".atributos_personalizacion (
                id SERIAL PRIMARY KEY,
                config_id INTEGER REFERENCES "{schema_name}".configuracion_personalizacion(id) ON DELETE CASCADE,
                nombre TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('select', 'texto', 'numero', 'si_no')),
                opciones JSONB,
                pregunta TEXT NOT NULL,
                requerido BOOLEAN DEFAULT true,
                precio_extra JSONB,
                orden INTEGER DEFAULT 0,
                activo BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Índices para nuevas tablas
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_prod_adic_producto ON "{schema_name}".producto_adicionales(producto_id)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_prod_adic_adicional ON "{schema_name}".producto_adicionales(adicional_id)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_prod_perso_producto ON "{schema_name}".producto_personalizaciones(producto_id)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_config_activo ON "{schema_name}".configuracion_personalizacion(activo)')
        cur.execute(f'CREATE INDEX IF NOT EXISTS idx_atributos_config ON "{schema_name}".atributos_personalizacion(config_id)')
    
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
            
            # Relaciones producto-adicional
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
                    # Verificar si la columna es_base existe
                    cur.execute(f"""
                        SELECT column_name FROM information_schema.columns 
                        WHERE table_schema = %s AND table_name = 'productos' AND column_name = 'es_base'
                    """, (schema_name,))
                    tiene_es_base = cur.fetchone() is not None
                    
                    # Construir SELECT según columnas existentes
                    if tiene_es_base:
                        cur.execute(f"""
                            SELECT id, nombre, descripcion, precio, categoria, disponible,
                                imagen_url, tiempo_preparacion, destacado, metadata, es_base, created_at
                            FROM "{schema_name}".productos 
                            ORDER BY destacado DESC, disponible DESC, categoria, nombre
                        """)
                    else:
                        cur.execute(f"""
                            SELECT id, nombre, descripcion, precio, categoria, disponible,
                                imagen_url, tiempo_preparacion, destacado, metadata, created_at
                            FROM "{schema_name}".productos 
                            ORDER BY destacado DESC, disponible DESC, categoria, nombre
                        """)
                    
                    rows = cur.fetchall()
                    productos = []
                    for row in rows:
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
                        
                        producto = {
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
                        }
                        
                        # Agregar es_base solo si existe la columna
                        if tiene_es_base and len(row) > 10:
                            producto['es_base'] = row[10] if row[10] is not None else True
                        else:
                            producto['es_base'] = True
                        
                        productos.append(producto)
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
                    cur.execute(f'SELECT id FROM "{schema_name}".productos WHERE nombre ILIKE %s', (nombre,))
                    existing = cur.fetchone()
                    
                    if existing:
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
    
    # ==================== NUEVOS MÉTODOS PARA CONFIGURACIÓN DE PERSONALIZACIÓN ====================
    
    def get_configuraciones_personalizacion(self, tenant_id: str, solo_activos: bool = True) -> list:
        """Obtiene todas las configuraciones de personalización del tenant"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    where = "WHERE activo = true" if solo_activos else ""
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, activo, instrucciones_ia, created_at, updated_at
                        FROM "{schema_name}".configuracion_personalizacion
                        {where}
                        ORDER BY nombre
                    """)
                    rows = cur.fetchall()
                    return [{
                        'id': row[0],
                        'nombre': row[1],
                        'descripcion': row[2],
                        'activo': row[3],
                        'instrucciones_ia': row[4],
                        'created_at': row[5],
                        'updated_at': row[6]
                    } for row in rows]
        except Exception as e:
            logger.error(f'Error obteniendo configuraciones: {e}')
            return []
    
    def get_configuracion_personalizacion(self, tenant_id: str, config_id: int) -> dict:
        """Obtiene una configuración de personalización por ID"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, activo, instrucciones_ia, created_at, updated_at
                        FROM "{schema_name}".configuracion_personalizacion
                        WHERE id = %s
                    """, (config_id,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'id': row[0],
                            'nombre': row[1],
                            'descripcion': row[2],
                            'activo': row[3],
                            'instrucciones_ia': row[4],
                            'created_at': row[5],
                            'updated_at': row[6]
                        }
                    return None
        except Exception as e:
            logger.error(f'Error obteniendo configuración {config_id}: {e}')
            return None
    
    def create_configuracion_personalizacion(self, tenant_id: str, nombre: str, descripcion: str = None, 
                                              instrucciones_ia: str = None) -> int:
        """Crea una nueva configuración de personalización"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO "{schema_name}".configuracion_personalizacion 
                        (nombre, descripcion, instrucciones_ia, created_at, updated_at)
                        VALUES (%s, %s, %s, NOW(), NOW())
                        RETURNING id
                    """, (nombre, descripcion, instrucciones_ia))
                    config_id = cur.fetchone()[0]
                conn.commit()
                logger.info(f'Configuración de personalización creada: {nombre} (id: {config_id})')
                return config_id
        except Exception as e:
            logger.error(f'Error creando configuración: {e}')
            raise
    
    def update_configuracion_personalizacion(self, tenant_id: str, config_id: int, 
                                             nombre: str = None, descripcion: str = None,
                                             activo: bool = None, instrucciones_ia: str = None) -> bool:
        """Actualiza una configuración de personalización"""
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
            if activo is not None:
                updates.append("activo = %s")
                params.append(activo)
            if instrucciones_ia is not None:
                updates.append("instrucciones_ia = %s")
                params.append(instrucciones_ia)
            
            if not updates:
                return False
            
            updates.append("updated_at = NOW()")
            params.append(config_id)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        UPDATE "{schema_name}".configuracion_personalizacion
                        SET {', '.join(updates)}
                        WHERE id = %s
                    """, params)
                    updated = cur.rowcount
                conn.commit()
            
            return updated > 0
        except Exception as e:
            logger.error(f'Error actualizando configuración {config_id}: {e}')
            raise
    
    def delete_configuracion_personalizacion(self, tenant_id: str, config_id: int) -> bool:
        """Elimina una configuración de personalización (y sus atributos por CASCADE)"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        DELETE FROM "{schema_name}".configuracion_personalizacion
                        WHERE id = %s
                    """, (config_id,))
                    deleted = cur.rowcount
                conn.commit()
            
            if deleted > 0:
                logger.info(f'Configuración {config_id} eliminada')
            return deleted > 0
        except Exception as e:
            logger.error(f'Error eliminando configuración {config_id}: {e}')
            raise
    
    # ==================== NUEVOS MÉTODOS PARA ATRIBUTOS DE PERSONALIZACIÓN ====================
    
    def get_atributos_personalizacion(self, tenant_id: str, config_id: int = None, solo_activos: bool = True) -> list:
        """Obtiene los atributos de personalización, opcionalmente filtrados por config_id"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    if config_id:
                        where = f"WHERE config_id = %s"
                        if solo_activos:
                            where += " AND activo = true"
                        cur.execute(f"""
                            SELECT id, config_id, nombre, tipo, opciones, pregunta, 
                                   requerido, precio_extra, orden, activo, created_at, updated_at
                            FROM "{schema_name}".atributos_personalizacion
                            {where}
                            ORDER BY orden
                        """, (config_id,))
                    else:
                        where = "WHERE activo = true" if solo_activos else ""
                        cur.execute(f"""
                            SELECT id, config_id, nombre, tipo, opciones, pregunta, 
                                   requerido, precio_extra, orden, activo, created_at, updated_at
                            FROM "{schema_name}".atributos_personalizacion
                            {where}
                            ORDER BY config_id, orden
                        """)
                    rows = cur.fetchall()
                    return [{
                        'id': row[0],
                        'config_id': row[1],
                        'nombre': row[2],
                        'tipo': row[3],
                        'opciones': row[4] if row[4] else [],
                        'pregunta': row[5],
                        'requerido': row[6],
                        'precio_extra': row[7] if row[7] else {},
                        'orden': row[8],
                        'activo': row[9],
                        'created_at': row[10],
                        'updated_at': row[11]
                    } for row in rows]
        except Exception as e:
            logger.error(f'Error obteniendo atributos: {e}')
            return []
    
    def create_atributo_personalizacion(self, tenant_id: str, config_id: int, nombre: str, tipo: str,
                                        pregunta: str, opciones: list = None, requerido: bool = True,
                                        precio_extra: dict = None, orden: int = 0) -> int:
        """Crea un nuevo atributo de personalización"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO "{schema_name}".atributos_personalizacion 
                        (config_id, nombre, tipo, opciones, pregunta, requerido, precio_extra, orden, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                        RETURNING id
                    """, (config_id, nombre, tipo, json.dumps(opciones) if opciones else None, 
                          pregunta, requerido, json.dumps(precio_extra) if precio_extra else None, orden))
                    attr_id = cur.fetchone()[0]
                conn.commit()
                logger.info(f'Atributo creado: {nombre} (id: {attr_id})')
                return attr_id
        except Exception as e:
            logger.error(f'Error creando atributo: {e}')
            raise
    
    def update_atributo_personalizacion(self, tenant_id: str, attr_id: int, **kwargs) -> bool:
        """Actualiza un atributo de personalización"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            allowed_fields = ['nombre', 'tipo', 'opciones', 'pregunta', 'requerido', 'precio_extra', 'orden', 'activo']
            updates = []
            params = []
            
            for field, value in kwargs.items():
                if field in allowed_fields:
                    if field in ['opciones', 'precio_extra']:
                        value = json.dumps(value) if value else None
                    updates.append(f"{field} = %s")
                    params.append(value)
            
            if not updates:
                return False
            
            updates.append("updated_at = NOW()")
            params.append(attr_id)
            
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        UPDATE "{schema_name}".atributos_personalizacion
                        SET {', '.join(updates)}
                        WHERE id = %s
                    """, params)
                    updated = cur.rowcount
                conn.commit()
            
            return updated > 0
        except Exception as e:
            logger.error(f'Error actualizando atributo {attr_id}: {e}')
            raise
    
    def delete_atributo_personalizacion(self, tenant_id: str, attr_id: int) -> bool:
        """Elimina un atributo de personalización"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        DELETE FROM "{schema_name}".atributos_personalizacion
                        WHERE id = %s
                    """, (attr_id,))
                    deleted = cur.rowcount
                conn.commit()
            
            if deleted > 0:
                logger.info(f'Atributo {attr_id} eliminado')
            return deleted > 0
        except Exception as e:
            logger.error(f'Error eliminando atributo {attr_id}: {e}')
            raise
    
    def get_configuracion_completa(self, tenant_id: str, config_nombre: str) -> dict:
        """Obtiene una configuración completa con todos sus atributos"""
        try:
            configs = self.get_configuraciones_personalizacion(tenant_id, solo_activos=True)
            config = next((c for c in configs if c['nombre'].lower() == config_nombre.lower()), None)
            
            if not config:
                return None
            
            atributos = self.get_atributos_personalizacion(tenant_id, config['id'], solo_activos=True)
            config['atributos'] = atributos
            
            return config
        except Exception as e:
            logger.error(f'Error obteniendo configuración completa: {e}')
            return None


# Instancia global
schema_manager = SchemaManager()