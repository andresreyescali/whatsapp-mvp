
# =====================================================
# MIGRACIÓN PARA TENANTS EXISTENTES
# Ejecutar en la base de datos principal
# =====================================================

DO $$
DECLARE
    schema_record RECORD;
BEGIN
    FOR schema_record IN 
        SELECT schema_name 
        FROM public.tenants 
        WHERE activo = true AND schema_name IS NOT NULL
    LOOP
        BEGIN
            RAISE NOTICE 'Migrando schema: %', schema_record.schema_name;
            
            -- 1. Agregar columna es_base si no existe
            EXECUTE format('
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_schema = %L AND table_name = ''productos'' AND column_name = ''es_base''
                    ) THEN
                        ALTER TABLE %I.productos ADD COLUMN es_base BOOLEAN DEFAULT true;
                        CREATE INDEX IF NOT EXISTS idx_productos_es_base ON %I.productos(es_base);
                        RAISE NOTICE ''  ✅ Columna es_base agregada a %'', %L;
                    ELSE
                        RAISE NOTICE ''  ⏭️ Columna es_base ya existe en %'', %L;
                    END IF;
                END $$;
            ', schema_record.schema_name, schema_record.schema_name, schema_record.schema_name, schema_record.schema_name, schema_record.schema_name);
            
            -- 2. Agregar columna updated_at si no existe
            EXECUTE format('
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_schema = %L AND table_name = ''productos'' AND column_name = ''updated_at''
                    ) THEN
                        ALTER TABLE %I.productos ADD COLUMN updated_at TIMESTAMP DEFAULT NOW();
                        RAISE NOTICE ''  ✅ Columna updated_at agregada a %'', %L;
                    ELSE
                        RAISE NOTICE ''  ⏭️ Columna updated_at ya existe en %'', %L;
                    END IF;
                END $$;
            ', schema_record.schema_name, schema_record.schema_name, schema_record.schema_name, schema_record.schema_name);
            
            -- 3. Crear tabla producto_adicionales
            EXECUTE format('
                CREATE TABLE IF NOT EXISTS %I.producto_adicionales (
                    id SERIAL PRIMARY KEY,
                    producto_id UUID REFERENCES %I.productos(id) ON DELETE CASCADE,
                    adicional_id UUID REFERENCES %I.productos(id) ON DELETE CASCADE,
                    cantidad_maxima INTEGER DEFAULT 1,
                    cantidad_minima INTEGER DEFAULT 0,
                    predeterminado BOOLEAN DEFAULT false,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(producto_id, adicional_id)
                );
                CREATE INDEX IF NOT EXISTS idx_prod_adic_producto ON %I.producto_adicionales(producto_id);
                CREATE INDEX IF NOT EXISTS idx_prod_adic_adicional ON %I.producto_adicionales(adicional_id);
                RAISE NOTICE ''  ✅ Tabla producto_adicionales creada en %'', %L;
            ', schema_record.schema_name, schema_record.schema_name, schema_record.schema_name, schema_record.schema_name, schema_record.schema_name, schema_record.schema_name);
            
            -- 4. Crear tabla personalizaciones
            EXECUTE format('
                CREATE TABLE IF NOT EXISTS %I.personalizaciones (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    tipo TEXT DEFAULT ''texto'',
                    opciones JSONB,
                    requerido BOOLEAN DEFAULT false,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                RAISE NOTICE ''  ✅ Tabla personalizaciones creada en %'', %L;
            ', schema_record.schema_name, schema_record.schema_name);
            
            -- 5. Crear tabla producto_personalizaciones
            EXECUTE format('
                CREATE TABLE IF NOT EXISTS %I.producto_personalizaciones (
                    id SERIAL PRIMARY KEY,
                    producto_id UUID REFERENCES %I.productos(id) ON DELETE CASCADE,
                    personalizacion_id INTEGER REFERENCES %I.personalizaciones(id) ON DELETE CASCADE,
                    orden INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(producto_id, personalizacion_id)
                );
                CREATE INDEX IF NOT EXISTS idx_prod_perso_producto ON %I.producto_personalizaciones(producto_id);
                RAISE NOTICE ''  ✅ Tabla producto_personalizaciones creada en %'', %L;
            ', schema_record.schema_name, schema_record.schema_name, schema_record.schema_name, schema_record.schema_name, schema_record.schema_name);
            
            -- 6. Actualizar productos existentes para que sean es_base = true (por defecto)
            EXECUTE format('
                UPDATE %I.productos SET es_base = true WHERE es_base IS NULL;
                RAISE NOTICE ''  ✅ Productos actualizados como base en %'', %L;
            ', schema_record.schema_name, schema_record.schema_name);
            
            RAISE NOTICE '✅ Migración completada para schema: %', schema_record.schema_name;
            
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE '❌ Error en schema %: %', schema_record.schema_name, SQLERRM;
        END;
    END LOOP;
END;
$$;