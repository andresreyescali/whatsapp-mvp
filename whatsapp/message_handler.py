import json
import re
import uuid
from datetime import datetime
from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from orders.repository import order_repo
from orders.payment import generar_link_pago
from whatsapp.client import whatsapp_client
from ai.client import ai_client
from core.logger import logger
from core.database import db_manager

class MessageHandler:
    """Procesa mensajes de WhatsApp usando IA para entender lenguaje natural"""
    
    def __init__(self):
        """Inicializa el manejador de mensajes"""
        self._datos_cliente = {}
    
    def _get_schema_name(self, tenant_id: str) -> str:
        tenant = tenant_repo.find_by_id(tenant_id)
        if tenant and tenant.get('schema_name'):
            return tenant['schema_name']
        return f"tenant_{tenant_id.replace('-', '_')}"
    
    def process(self, phone_id: str, numero: str, texto: str):
        logger.info(f'Procesando mensaje de {numero}: {texto}')
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'Tenant no encontrado para phone_id: {phone_id}')
            return
        
        schema_manager.ensure_schema(tenant['id'])
        menu = self._obtener_menu(tenant['id'])
        contexto = self._obtener_contexto_tenant(tenant['id'])
        
        respuesta = self._procesar_con_ia(texto, tenant, menu, numero, contexto)
        
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)

    def _obtener_menu(self, tenant_id: str) -> list:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible 
                        FROM "{schema_name}".productos 
                        ORDER BY categoria, nombre
                    """)
                    rows = cur.fetchall()
                    return [{
                        'id': str(row[0]),
                        'nombre': row[1],
                        'descripcion': row[2] or '',
                        'precio': row[3],
                        'categoria': row[4] or 'general',
                        'disponible': row[5]
                    } for row in rows]
        except Exception as e:
            logger.error(f'Error obteniendo menú: {e}')
            return []

    def _obtener_contexto_tenant(self, tenant_id: str) -> dict:
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        SELECT instrucciones, horario, ubicacion, politicas, prompt_personalizado 
                        FROM public.tenant_context WHERE tenant_id = %s
                    ''', (tenant_id,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'instrucciones': row[0] or '',
                            'horario': row[1] or '',
                            'ubicacion': row[2] or '',
                            'politicas': row[3] or '',
                            'prompt_personalizado': row[4] or ''
                        }
                    return {}
        except Exception as e:
            logger.error(f'Error obteniendo contexto: {e}')
            return {}
    
    def _guardar_conversacion(self, tenant_id: str, cliente_numero: str, mensaje: str, respuesta: str):
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO "{schema_name}".conversaciones (cliente_numero, mensaje, respuesta, tipo, created_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (cliente_numero, mensaje, respuesta, 'ia'))
                conn.commit()
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
    
    # ==================== MÉTODOS DEL CARRITO ====================

    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id FROM "{schema_name}".carritos WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    existing = cur.fetchone()
                    
                    if existing:
                        cur.execute(f"""
                            UPDATE "{schema_name}".carritos 
                            SET items = %s, total = %s, updated_at = NOW()
                            WHERE cliente_numero = %s
                        """, (json.dumps(items), total, cliente_numero))
                    else:
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".carritos (cliente_numero, items, total, created_at, updated_at)
                            VALUES (%s, %s, %s, NOW(), NOW())
                        """, (cliente_numero, json.dumps(items), total))
                    conn.commit()
        except Exception as e:
            logger.error(f'Error guardando carrito: {e}')

    def _cargar_carrito(self, tenant_id: str, cliente_numero: str) -> dict:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT items, total FROM "{schema_name}".carritos WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    row = cur.fetchone()
                    if row:
                        items = row[0] if isinstance(row[0], list) else json.loads(row[0]) if row[0] else []
                        return {'items': items, 'total': row[1] or 0}
                    return {'items': [], 'total': 0}
        except Exception as e:
            logger.error(f'Error cargando carrito: {e}')
            return {'items': [], 'total': 0}
        
    def _agregar_al_carrito(self, tenant_id: str, cliente_numero: str, productos: list):
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        for p in productos:
            encontrado = False
            for item in carrito['items']:
                if item.get('nombre') == p.get('nombre'):
                    item['cantidad'] = item.get('cantidad', 1) + p.get('cantidad', 1)
                    encontrado = True
                    break
            if not encontrado:
                carrito['items'].append({
                    'nombre': p.get('nombre'),
                    'precio': p.get('precio', 0),
                    'cantidad': p.get('cantidad', 1)
                })
            carrito['total'] += p.get('precio', 0) * p.get('cantidad', 1)
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
    
    # ==================== MÉTODOS DEL CLIENTE ====================
    
    def _obtener_cliente(self, tenant_id: str, cliente_numero: str) -> dict:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT nombre, cc, email, direccion, numero_telefono
                        FROM "{schema_name}".clientes WHERE numero_telefono = %s
                    """, (cliente_numero,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'nombre': row[0],
                            'cc': row[1],
                            'email': row[2],
                            'direccion': row[3],
                            'telefono': row[4]
                        }
                    return {}
        except Exception as e:
            logger.error(f'Error obteniendo cliente: {e}')
            return {}
    
    def _guardar_datos_cliente_en_bd(self, tenant_id: str, numero: str):
        if numero not in self._datos_cliente:
            return
        datos = self._datos_cliente[numero]
        if not any(datos.values()):
            return
        
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT id FROM "{schema_name}".clientes WHERE numero_telefono = %s', (numero,))
                    row = cur.fetchone()
                    
                    if row:
                        updates = []
                        params = []
                        if datos.get('nombre'):
                            updates.append("nombre = %s")
                            params.append(datos['nombre'])
                        if datos.get('cc'):
                            updates.append("cc = %s")
                            params.append(datos['cc'])
                        if datos.get('email'):
                            updates.append("email = %s")
                            params.append(datos['email'])
                        if datos.get('direccion'):
                            updates.append("direccion = %s")
                            params.append(datos['direccion'])
                        if updates:
                            params.append(row[0])
                            cur.execute(f'UPDATE "{schema_name}".clientes SET {", ".join(updates)}, updated_at = NOW() WHERE id = %s', params)
                    else:
                        cliente_id = str(uuid.uuid4())
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".clientes (id, numero_telefono, nombre, cc, email, direccion)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (cliente_id, numero, datos.get('nombre'), datos.get('cc'), datos.get('email'), datos.get('direccion')))
                    conn.commit()
        except Exception as e:
            logger.error(f'Error guardando cliente en BD: {e}')
    
    def _get_resumen_cliente(self, tenant_id: str, cliente_numero: str) -> str:
        cliente = self._obtener_cliente(tenant_id, cliente_numero)
        if cliente and any(cliente.values()):
            return f"""📋 DATOS DEL CLIENTE:
- Nombre: {cliente.get('nombre', 'N/A')}
- Cédula: {cliente.get('cc', 'N/A')}
- Teléfono: {cliente.get('telefono', 'N/A')}
- Email: {cliente.get('email', 'N/A')}
- Dirección: {cliente.get('direccion', 'N/A')}"""
        return "📋 DATOS DEL CLIENTE: No hay datos previos"
    
    def _get_carrito_info_para_prompt(self, tenant_id: str, cliente_numero: str) -> str:
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        if not carrito.get('items'):
            return "Carrito vacío"
        items_texto = "\n".join([f"- {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}" for item in carrito['items']])
        return f"📦 CARRITO ACTUAL:\n{items_texto}\n💰 Total: ${carrito.get('total', 0):,.0f}"
    
    def _formatear_datos_cliente(self, datos: dict) -> str:
        if not datos:
            return ""
        texto = ""
        if datos.get('nombre'):
            texto += f"\n📝 **Nombre:** {datos['nombre']}"
        if datos.get('cc'):
            texto += f"\n🆔 **Cédula:** {datos['cc']}"
        if datos.get('telefono'):
            texto += f"\n📞 **Teléfono:** {datos['telefono']}"
        if datos.get('email'):
            texto += f"\n📧 **Email:** {datos['email']}"
        if datos.get('direccion'):
            texto += f"\n📍 **Dirección:** {datos['direccion']}"
        if datos.get('fecha_entrega'):
            texto += f"\n📅 **Fecha:** {datos['fecha_entrega']}"
        if datos.get('hora_entrega'):
            texto += f"\n⏰ **Hora:** {datos['hora_entrega']}"
        if datos.get('recojo_en_tienda'):
            texto += f"\n🏪 **Recojo en tienda**"
        if datos.get('pago_contraentrega'):
            texto += f"\n💰 **Pago:** Contraentrega"
        return texto
    
    def _finalizar_pedido(self, tenant: dict, numero: str, carrito: dict) -> str:
        if not carrito or not carrito.get('items'):
            return "No hay productos en tu carrito. ¿Qué te gustaría ordenar?"
        
        datos_cliente = self._datos_cliente.get(numero, {})
        schema_name = self._get_schema_name(tenant['id'])
        
        contexto = self._obtener_contexto_tenant(tenant['id'])
        direccion_entrega = datos_cliente.get('direccion', '')
        if datos_cliente.get('recojo_en_tienda'):
            direccion_entrega = f"Recojo en tienda - {tenant.get('nombre')} - {contexto.get('ubicacion', '')}"
        
        cliente_id = self._obtener_o_crear_cliente(tenant['id'], numero, datos_cliente)
        if not cliente_id:
            return "❌ Hubo un error con tus datos. Por favor intenta de nuevo."
        
        pedido_id = str(uuid.uuid4())
        items = carrito['items']
        total = carrito['total']
        
        with db_manager.get_connection(tenant['id']) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COALESCE(MAX(secuencial), 0) + 1 FROM "{schema_name}".pedidos')
                secuencial = cur.fetchone()[0] or 1
        
        fecha_str = datetime.now().strftime('%Y%m%d%H%M%S')
        numero_pedido = f"{tenant['nombre'][:3].upper()}-{fecha_str}-{str(uuid.uuid4())[:4].upper()}"
        
        try:
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    # Verificar columnas
                    cur.execute(f"""
                        DO $$ 
                        BEGIN
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                        WHERE table_schema = '{schema_name}' AND table_name = 'pedidos' AND column_name = 'cliente_numero') THEN
                                ALTER TABLE "{schema_name}".pedidos ADD COLUMN cliente_numero TEXT;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                        WHERE table_schema = '{schema_name}' AND table_name = 'pedidos' AND column_name = 'secuencial') THEN
                                ALTER TABLE "{schema_name}".pedidos ADD COLUMN secuencial INTEGER;
                            END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                        WHERE table_schema = '{schema_name}' AND table_name = 'pedidos' AND column_name = 'numero_pedido') THEN
                                ALTER TABLE "{schema_name}".pedidos ADD COLUMN numero_pedido TEXT;
                            END IF;
                        END $$;
                    """)
                    conn.commit()
                    
                    cur.execute(f'INSERT INTO "{schema_name}".pedidos (id, cliente_id, cliente_numero, numero_pedido, secuencial, items, total, estado, direccion_entrega, notas) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)', (pedido_id, cliente_id, numero, numero_pedido, secuencial, json.dumps(items), total, 'nuevo', direccion_entrega, f"Fecha: {datos_cliente.get('fecha_entrega', '')} Hora: {datos_cliente.get('hora_entrega', '')}".strip()))
                conn.commit()
            
            self._guardar_carrito(tenant['id'], numero, [], 0)
            if numero in self._datos_cliente:
                del self._datos_cliente[numero]
            
            items_texto = "\n".join([f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}" for item in items])
            datos_texto = self._formatear_datos_cliente(datos_cliente)
            
            return f"""✅ **¡PEDIDO CONFIRMADO!**

📌 **Número de pedido:** *{numero_pedido}*
📝 *Guarda este número para hacer seguimiento*
{datos_texto}

📋 **Productos:**
{items_texto}
💰 **Total:** ${total:,.0f}

📦 **Entrega:** {direccion_entrega}

📌 *Cuando completes el pago, avísame para empezar a preparar tu pedido.*
📞 *Para consultar tu pedido, envía "estado {numero_pedido}"*"""
        except Exception as e:
            logger.error(f'Error creando pedido: {e}')
            return "❌ Hubo un error procesando tu solicitud. Por favor intenta de nuevo."
    
    def _obtener_o_crear_cliente(self, tenant_id: str, numero: str, datos_cliente: dict = None) -> str:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT id, nombre, cc, email, direccion FROM "{schema_name}".clientes WHERE numero_telefono = %s', (numero,))
                    row = cur.fetchone()
                    
                    if row:
                        cliente_id = row[0]
                        if datos_cliente:
                            updates, params = [], []
                            if datos_cliente.get('nombre') and not row[1]:
                                updates.append("nombre = %s")
                                params.append(datos_cliente['nombre'])
                            if datos_cliente.get('cc') and not row[2]:
                                updates.append("cc = %s")
                                params.append(datos_cliente['cc'])
                            if datos_cliente.get('email') and not row[3]:
                                updates.append("email = %s")
                                params.append(datos_cliente['email'])
                            if datos_cliente.get('direccion') and not row[4]:
                                updates.append("direccion = %s")
                                params.append(datos_cliente['direccion'])
                            if updates:
                                params.append(cliente_id)
                                cur.execute(f'UPDATE "{schema_name}".clientes SET {", ".join(updates)}, updated_at = NOW() WHERE id = %s', params)
                                conn.commit()
                        return cliente_id
                    else:
                        cliente_id = str(uuid.uuid4())
                        cur.execute(f'INSERT INTO "{schema_name}".clientes (id, numero_telefono, nombre, cc, email, direccion) VALUES (%s, %s, %s, %s, %s, %s)', (cliente_id, numero, datos_cliente.get('nombre') if datos_cliente else None, datos_cliente.get('cc') if datos_cliente else None, datos_cliente.get('email') if datos_cliente else None, datos_cliente.get('direccion') if datos_cliente else None))
                        conn.commit()
                        return cliente_id
        except Exception as e:
            logger.error(f'Error gestionando cliente: {e}')
            return None
    
    # ==================== HISTORIAL ====================
    
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 10) -> list:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT mensaje, respuesta FROM "{schema_name}".conversaciones 
                        WHERE cliente_numero = %s ORDER BY created_at ASC LIMIT %s
                    """, (cliente_numero, limit))
                    return cur.fetchall()
        except Exception as e:
            logger.error(f'Error obteniendo historial: {e}')
            return []
    
    def _formatear_historial_para_prompt(self, historial: list) -> str:
        if not historial:
            return ""
        texto = "\n📜 HISTORIAL DE LA CONVERSACIÓN:\n"
        for h in historial:
            texto += f"Cliente: {h[0]}\nAsistente: {h[1]}\n"
        return texto
    
    # ==================== EXTRACCIÓN DE PRODUCTOS DEL HISTORIAL ====================
    
    def _extraer_productos_del_historial(self, historial: list, menu: list) -> list:
        """Extrae productos mencionados en el historial de conversación"""
        if not historial or not menu:
            return []
        
        productos = []
        for h in historial[-6:]:
            mensaje = h[0]
            productos.extend(self._detectar_productos_simples(mensaje, menu))
        
        # Eliminar duplicados por nombre
        vistos = set()
        unicos = []
        for p in productos:
            if p['nombre'] not in vistos:
                vistos.add(p['nombre'])
                unicos.append(p)
        return unicos
    
    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _extraer_y_guardar_datos(self, texto: str, numero: str):
        if not ai_client.client:
            return
        
        prompt = f"""Extrae información del cliente del siguiente mensaje.
MENSAJE: "{texto}"
Devuelve SOLO un JSON: {{"nombre": "", "cc": "", "telefono": "", "email": "", "direccion": "", "fecha_entrega": "", "hora_entrega": "", "recojo_en_tienda": false, "pago_contraentrega": false}}"""
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300
            )
            contenido = response.choices[0].message.content
            contenido = contenido.replace('```json', '').replace('```', '').strip()
            datos = json.loads(contenido)
            
            if datos and any(datos.values()):
                if numero not in self._datos_cliente:
                    self._datos_cliente[numero] = {}
                for key, value in datos.items():
                    if value:
                        self._datos_cliente[numero][key] = value
                logger.info(f"Datos extraídos: {datos}")
        except Exception as e:
            logger.error(f'Error extrayendo datos: {e}')
    
    def _detectar_productos_simples(self, texto: str, menu: list) -> list:
        if not menu:
            return []
        texto_lower = texto.lower()
        productos = []
        for producto in menu:
            nombre = producto.get('nombre', '').lower()
            if nombre in texto_lower:
                cantidad = 1
                match = re.search(rf'(\d+)\s*{re.escape(nombre)}', texto_lower)
                if match:
                    cantidad = int(match.group(1))
                productos.append({
                    'nombre': producto['nombre'],
                    'precio': producto.get('precio', 0),
                    'cantidad': cantidad
                })
        return productos
    
    def _cliente_confirmo(self, texto: str) -> bool:
        confirmaciones = ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'confirmar', 'proceder', 'adelante', 'esta bien', 'está bien', 'confirmo pedido']
        palabras_pago = ['pague', 'pago', 'pagado', 'transferí', 'consigné', 'pagué', 'ya pague', 'listo el pago']
        texto_lower = texto.lower().strip()
        return texto_lower in confirmaciones or any(c in texto_lower for c in confirmaciones if len(c) > 2) or any(p in texto_lower for p in palabras_pago)
    
    def _mostrar_resumen_carrito(self, tenant: dict, numero: str, carrito: dict) -> str:
        if not carrito.get('items'):
            return "No tienes productos en tu carrito. ¿Qué te gustaría ordenar?"
        items_texto = "\n".join([f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}" for item in carrito['items']])
        return f"""📋 **Tu pedido actual:**
{items_texto}
**Total:** ${carrito.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido? (responde "confirmo")"""
    
    def _procesar_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, contexto: dict) -> str:
        """Procesa el mensaje usando IA para lenguaje natural"""
        
        if not ai_client.client:
            return self._respuesta_fallback(tenant, menu)
        
        carrito_actual = self._cargar_carrito(tenant['id'], numero)
        resumen_cliente = self._get_resumen_cliente(tenant['id'], numero)
        historial = self._get_historial_conversacion(tenant['id'], numero, 10)
        historial_texto = self._formatear_historial_para_prompt(historial)
        
        self._extraer_y_guardar_datos(texto, numero)
        if numero in self._datos_cliente and self._datos_cliente[numero].get('nombre'):
            self._guardar_datos_cliente_en_bd(tenant['id'], numero)
        
        texto_lower = texto.lower()
        
        # 1. Verificar pago
        if any(p in texto_lower for p in ['pague', 'pago', 'pagado', 'transferí', 'consigné', 'pagué', 'ya pague', 'listo el pago']):
            try:
                resultado = order_repo.marcar_pagado(tenant['id'], numero)
                if resultado > 0:
                    return "✅ ¡Pago confirmado! En breve comenzamos a preparar tu pedido."
                else:
                    schema_name = self._get_schema_name(tenant['id'])
                    with db_manager.get_connection(tenant['id']) as conn:
                        with conn.cursor() as cur:
                            cur.execute(f'UPDATE "{schema_name}".pedidos SET estado = "pagado", pagado_at = NOW() WHERE cliente_numero = %s AND estado = "nuevo" ORDER BY created_at DESC LIMIT 1', (numero,))
                            if cur.rowcount > 0:
                                return "✅ ¡Pago confirmado! En breve comenzamos a preparar tu pedido."
                    return "✅ ¡Gracias por confirmar el pago! Procesaremos tu pedido."
            except Exception as e:
                logger.error(f"Error procesando pago: {e}")
                return "✅ Gracias por confirmar. Procesaremos tu pedido."
        
        # 2. Verificar confirmación - CON RECUPERACIÓN DE PRODUCTOS DEL HISTORIAL
        if self._cliente_confirmo(texto):
            if carrito_actual.get('items'):
                self._guardar_datos_cliente_en_bd(tenant['id'], numero)
                return self._finalizar_pedido(tenant, numero, carrito_actual)
            else:
                # Intentar recuperar productos del historial
                productos_del_historial = self._extraer_productos_del_historial(historial, menu)
                if productos_del_historial:
                    self._agregar_al_carrito(tenant['id'], numero, productos_del_historial)
                    carrito_actual = self._cargar_carrito(tenant['id'], numero)
                    if carrito_actual.get('items'):
                        return self._finalizar_pedido(tenant, numero, carrito_actual)
                return "❌ No hay productos en tu carrito. Por favor, primero dime qué deseas ordenar y luego confirma.\n\nEjemplo: 'quiero 25 empanadas hawaianas'"
        
        # 3. Verificar consulta de carrito
        if any(p in texto_lower for p in ['qué pedí', 'mi pedido', 'ver carrito', 'que tengo']):
            return self._mostrar_resumen_carrito(tenant, numero, carrito_actual)
        
        # 4. Detectar productos en el mensaje actual
        productos_detectados = self._detectar_productos_simples(texto, menu)
        
        # 5. Si hay productos, agregar al carrito
        if productos_detectados:
            self._agregar_al_carrito(tenant['id'], numero, productos_detectados)
            nuevo_carrito = self._cargar_carrito(tenant['id'], numero)
            items_texto = "\n".join([f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}" for item in nuevo_carrito['items']])
            return f"""✅ **Agregado a tu pedido:**

{items_texto}
**Total:** ${nuevo_carrito.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido? (responde "confirmo" para finalizar)"""
        
        # 6. Si hay carrito, mostrar resumen
        if carrito_actual.get('items'):
            return self._mostrar_resumen_carrito(tenant, numero, carrito_actual)
        
        # 7. Si no hay carrito ni productos detectados, usar IA
        menu_simplificado = [{'nombre': p.get('nombre'), 'precio': p.get('precio')} for p in menu[:30]]
        
        system_prompt = f"""Eres un asistente de ventas conversacional para {tenant.get('nombre', 'Mi negocio')}.

🏪 INFORMACIÓN:
- Horario: {contexto.get('horario', 'No especificado')}
- Ubicación: {contexto.get('ubicacion', 'No especificada')}

📋 PRODUCTOS:
{json.dumps(menu_simplificado, indent=2, ensure_ascii=False)}

{resumen_cliente}
{historial_texto}

INSTRUCCIONES:
1. Responde de forma natural, cálida y conversacional en español.
2. Ayuda al cliente a elegir productos del catálogo.
3. Cuando el cliente pida algo, confirma y pregunta si desea agregar algo más.
4. Para finalizar, el cliente debe decir "confirmo" o "si".
5. NO generes números de pedido ni confirmes reservas sin tener productos en el carrito.
6. Sé breve y cálido.

RESPONDE en español."""
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Cliente: {texto}\n\nAsistente:"}
                ],
                temperature=0.7,
                max_tokens=500
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f'Error en IA: {e}')
            return self._respuesta_fallback(tenant, menu)
    
    def _respuesta_fallback(self, tenant: dict, menu: list) -> str:
        if menu:
            primeros = menu[:3]
            sugerencias = ", ".join([p['nombre'] for p in primeros])
            return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿Te gustaría ordenar {sugerencias}? Escríbeme lo que deseas."
        return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿En qué puedo ayudarte?"


# Instancia global
message_handler = MessageHandler()