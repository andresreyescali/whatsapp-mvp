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
        self._datos_cliente = {}  # Almacena datos de clientes por número (temporales)
    
    def _get_schema_name(self, tenant_id: str) -> str:
        """Obtiene el schema_name de un tenant"""
        tenant = tenant_repo.find_by_id(tenant_id)
        if tenant and tenant.get('schema_name'):
            return tenant['schema_name']
        return f"tenant_{tenant_id.replace('-', '_')}"
    
    def process(self, phone_id: str, numero: str, texto: str):
        """Procesa mensaje entrante y envía respuesta"""
        logger.info(f'Procesando mensaje de {numero}: {texto}')
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'Tenant no encontrado para phone_id: {phone_id}')
            return
        
        # Asegurar que el esquema del tenant existe
        schema_manager.ensure_schema(tenant['id'])
        
        menu = self._obtener_menu(tenant['id'])
        contexto = self._obtener_contexto_tenant(tenant['id'])
        
        respuesta = self._procesar_con_ia(texto, tenant, menu, numero, contexto)
        
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)

    def _obtener_menu(self, tenant_id: str) -> list:
        """Obtiene el menú del tenant desde la base de datos"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible 
                        FROM "{schema_name}".productos 
                        WHERE disponible = true 
                        ORDER BY categoria, nombre
                    """)
                    rows = cur.fetchall()
                    productos = []
                    for row in rows:
                        productos.append({
                            'id': str(row[0]),  # Convertir UUID a string
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

    def _obtener_contexto_tenant(self, tenant_id: str) -> dict:
        """Obtiene el contexto personalizado del tenant"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        SELECT instrucciones, horario, ubicacion, politicas, prompt_personalizado 
                        FROM public.tenant_context 
                        WHERE tenant_id = %s
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
        """Guarda la conversación en el esquema del tenant"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO "{schema_name}".conversaciones (cliente_numero, mensaje, respuesta, tipo, created_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (cliente_numero, mensaje, respuesta, 'ia'))
                conn.commit()
                logger.info(f"Conversación guardada para {cliente_numero}")
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
    
    # ==================== MÉTODOS DEL HISTORIAL ====================
    
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 10) -> list:
        """Obtiene el historial de conversación desde el esquema del tenant"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT mensaje, respuesta, created_at 
                        FROM "{schema_name}".conversaciones 
                        WHERE cliente_numero = %s 
                        ORDER BY created_at ASC 
                        LIMIT %s
                    """, (cliente_numero, limit))
                    rows = cur.fetchall()
                    logger.info(f"Historial obtenido para {cliente_numero}: {len(rows)} mensajes")
                    return rows if rows else []
        except Exception as e:
            logger.error(f'Error obteniendo historial: {e}')
            return []
    
    def _formatear_historial_para_prompt(self, historial: list) -> str:
        """Formatea el historial para incluirlo en el prompt de IA"""
        if not historial:
            return ""
        
        texto = "\n📜 HISTORIAL DE LA CONVERSACIÓN:\n"
        for h in historial:
            texto += f"Cliente: {h[0]}\n"
            texto += f"Asistente: {h[1]}\n"
        return texto
    
    # ==================== MÉTODOS DEL CARRITO ====================

    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        """Guarda el carrito en el esquema del tenant"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS "{schema_name}".carritos (
                            id SERIAL PRIMARY KEY,
                            cliente_numero TEXT NOT NULL UNIQUE,
                            items JSONB NOT NULL,
                            total INTEGER DEFAULT 0,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    cur.execute(f"""
                        INSERT INTO "{schema_name}".carritos (cliente_numero, items, total, created_at, updated_at)
                        VALUES (%s, %s, %s, NOW(), NOW())
                        ON CONFLICT (cliente_numero) 
                        DO UPDATE SET items = EXCLUDED.items, total = EXCLUDED.total, updated_at = NOW()
                    """, (cliente_numero, json.dumps(items), total))
                conn.commit()
        except Exception as e:
            logger.error(f'Error guardando carrito: {e}')

    def _cargar_carrito(self, tenant_id: str, cliente_numero: str) -> dict:
        """Carga el carrito desde el esquema del tenant"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT items, total FROM "{schema_name}".carritos 
                        WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    row = cur.fetchone()
                    if row:
                        items = row[0]
                        if isinstance(items, str):
                            items = json.loads(items)
                        return {'items': items or [], 'total': row[1] or 0}
                    return {'items': [], 'total': 0}
        except Exception as e:
            logger.error(f'Error cargando carrito: {e}')
            return {'items': [], 'total': 0}
        
    def _agregar_al_carrito(self, tenant_id: str, cliente_numero: str, productos: list):
        """Agrega productos al carrito del cliente"""
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
        """Obtiene los datos del cliente desde la BD"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT nombre, cc, email, direccion, numero_telefono
                        FROM "{schema_name}".clientes
                        WHERE numero_telefono = %s
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
        """Guarda los datos temporales del cliente en la base de datos"""
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
                            logger.info(f"Cliente {numero} actualizado en BD")
                    else:
                        cliente_id = str(uuid.uuid4())
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".clientes (id, numero_telefono, nombre, cc, email, direccion)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (cliente_id, numero, datos.get('nombre'), datos.get('cc'), datos.get('email'), datos.get('direccion')))
                        logger.info(f"Cliente {numero} creado en BD")
                    
                    conn.commit()
        except Exception as e:
            logger.error(f'Error guardando cliente en BD: {e}')
    
    def _get_resumen_cliente(self, tenant_id: str, cliente_numero: str) -> str:
        """Obtiene un resumen estructurado del cliente y sus pedidos"""
        resumen = []
        
        cliente = self._obtener_cliente(tenant_id, cliente_numero)
        if cliente and any(cliente.values()):
            resumen.append("📋 DATOS DEL CLIENTE:")
            if cliente.get('nombre'):
                resumen.append(f"- Nombre: {cliente['nombre']}")
            if cliente.get('cc'):
                resumen.append(f"- Cédula: {cliente['cc']}")
            if cliente.get('telefono'):
                resumen.append(f"- Teléfono: {cliente['telefono']}")
            if cliente.get('email'):
                resumen.append(f"- Email: {cliente['email']}")
            if cliente.get('direccion'):
                resumen.append(f"- Dirección: {cliente['direccion']}")
        else:
            resumen.append("📋 DATOS DEL CLIENTE: No hay datos previos")
        
        return "\n".join(resumen)
    
    def _get_carrito_info_para_prompt(self, tenant_id: str, cliente_numero: str) -> str:
        """Obtiene información del carrito para el prompt"""
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        if not carrito.get('items'):
            return "Carrito vacío"
        
        items_texto = ""
        for item in carrito['items']:
            items_texto += f"- {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}\n"
        return f"📦 CARRITO ACTUAL:\n{items_texto}💰 Total: ${carrito.get('total', 0):,.0f}"
    
    def _formatear_datos_cliente(self, datos: dict) -> str:
        """Formatea los datos del cliente para confirmación"""
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
            texto += f"\n📅 **Fecha de entrega:** {datos['fecha_entrega']}"
        if datos.get('hora_entrega'):
            texto += f"\n⏰ **Hora:** {datos['hora_entrega']}"
        if datos.get('recojo_en_tienda'):
            texto += f"\n🏪 **Recojo en tienda**"
        if datos.get('pago_contraentrega'):
            texto += f"\n💰 **Pago:** Contraentrega"
        
        return texto
    
    def _finalizar_pedido(self, tenant: dict, numero: str, carrito: dict) -> str:
        """Finaliza el pedido/reserva y genera número de seguimiento"""
        if not carrito or not carrito.get('items'):
            return "No hay productos/servicios en tu carrito. ¿Qué te gustaría reservar?"
        
        datos_cliente = self._datos_cliente.get(numero, {})
        schema_name = self._get_schema_name(tenant['id'])
        
        # Obtener ubicación del negocio
        contexto = self._obtener_contexto_tenant(tenant['id'])
        ubicacion_negocio = contexto.get('ubicacion', '')
        nombre_negocio = tenant.get('nombre', 'nuestro local')
        
        # Determinar dirección de entrega/recojo
        direccion_entrega = datos_cliente.get('direccion', '')
        if datos_cliente.get('recojo_en_tienda'):
            direccion_entrega = f"Recojo en tienda - {nombre_negocio} - {ubicacion_negocio}"
        
        # Guardar cliente en BD
        cliente_id = self._obtener_o_crear_cliente(tenant['id'], numero, datos_cliente)
        if not cliente_id:
            return "❌ Hubo un error con tus datos. Por favor intenta de nuevo."
        
        pedido_id = str(uuid.uuid4())
        items = carrito['items']
        total = carrito['total']
        
        # Obtener secuencial y generar número de pedido/reserva
        with db_manager.get_connection(tenant['id']) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COALESCE(MAX(secuencial), 0) + 1 FROM "{schema_name}".pedidos')
                secuencial = cur.fetchone()[0] or 1
        
        fecha_str = datetime.now().strftime('%Y%m%d')
        numero_pedido = f"{tenant['nombre'][:3].upper()}-{fecha_str}-{secuencial:04d}"
        
        try:
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO "{schema_name}".pedidos 
                        (id, cliente_id, cliente_numero, numero_pedido, secuencial, items, total, estado, direccion_entrega, notas)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        pedido_id, cliente_id, numero, numero_pedido, secuencial, json.dumps(items),
                        total, 'nuevo', direccion_entrega,
                        f"Fecha: {datos_cliente.get('fecha_entrega', '')} Hora: {datos_cliente.get('hora_entrega', '')}".strip()
                    ))
                conn.commit()
            
            # Limpiar carrito y datos temporales
            self._guardar_carrito(tenant['id'], numero, [], 0)
            if numero in self._datos_cliente:
                del self._datos_cliente[numero]
            
            link_pago = generar_link_pago(total, pedido_id)
            
            items_texto = ""
            for item in items:
                subtotal = item.get('precio', 0) * item.get('cantidad', 1)
                items_texto += f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${subtotal:,.0f}\n"
            
            datos_texto = self._formatear_datos_cliente(datos_cliente)
            
            # Determinar si es reserva o pedido
            tipo = "RESERVA" if any(p in tenant.get('nombre', '').lower() for p in ['travel', 'tour', 'viaje', 'avars travel']) else "PEDIDO"
            
            return f"""✅ **¡{tipo} CONFIRMADA!**

📌 **Número de {tipo.lower()}:** *{numero_pedido}*
📝 *Guarda este número para hacer seguimiento*

{datos_texto}

📋 **Servicios/Productos:**
{items_texto}
💰 **Total:** ${total:,.0f}

📦 **Entrega/Recojo:** {direccion_entrega}

🔗 **Link de pago:** {link_pago}

📌 *Cuando completes el pago, avísame para confirmar tu {tipo.lower()}.*
📞 *Para consultar tu {tipo.lower()}, envía "estado {numero_pedido}"*"""
                
        except Exception as e:
            logger.error(f'Error creando pedido/reserva: {e}')
            return "❌ Hubo un error procesando tu solicitud. Por favor intenta de nuevo."
    
    def _obtener_o_crear_cliente(self, tenant_id: str, numero: str, datos_cliente: dict = None) -> str:
        """Obtiene o crea un cliente en el esquema del tenant"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT id, nombre, cc, email, direccion FROM "{schema_name}".clientes WHERE numero_telefono = %s', (numero,))
                    row = cur.fetchone()
                    
                    if row:
                        cliente_id = row[0]
                        if datos_cliente:
                            updates = []
                            params = []
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
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".clientes (id, numero_telefono, nombre, cc, email, direccion)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            cliente_id, numero,
                            datos_cliente.get('nombre') if datos_cliente else None,
                            datos_cliente.get('cc') if datos_cliente else None,
                            datos_cliente.get('email') if datos_cliente else None,
                            datos_cliente.get('direccion') if datos_cliente else None
                        ))
                        conn.commit()
                        return cliente_id
        except Exception as e:
            logger.error(f'Error gestionando cliente: {e}')
            return None
    
    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _intencion_reserva(self, texto: str) -> bool:
        """Detecta si el cliente quiere reservar un servicio"""
        palabras_reserva = [
            'reservar', 'apartar', 'separar', 'confirmar', 'tomar',
            'me gustaría', 'quiero', 'deseo', 'necesito', 'reserva'
        ]
        texto_lower = texto.lower()
        return any(palabra in texto_lower for palabra in palabras_reserva)
    
    def _extraer_y_guardar_datos(self, texto: str, numero: str):
        """Extrae datos del cliente usando IA y los guarda temporalmente"""
        if not ai_client.client:
            return
        
        prompt = f"""
        Extrae información del cliente del siguiente mensaje.
        
        MENSAJE: "{texto}"
        
        Devuelve SOLO un JSON:
        {{
            "nombre": "nombre completo",
            "cc": "número de cédula",
            "telefono": "número de teléfono",
            "email": "correo electrónico",
            "direccion": "dirección completa",
            "fecha_entrega": "fecha",
            "hora_entrega": "hora",
            "recojo_en_tienda": false,
            "pago_contraentrega": false
        }}
        """
        
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
                logger.info(f"Datos extraídos y guardados: {datos}")
        except Exception as e:
            logger.error(f'Error extrayendo datos: {e}')
    
    def _cliente_confirmo(self, texto: str) -> bool:
        """Detecta si el cliente confirmó el pedido/reserva"""
        confirmaciones = [
            'si', 'sí', 'dale', 'ok', 'correcto', 'confirmo',
            'confirmar', 'proceder', 'adelante', 'esta bien',
            'está bien', 'confirmo pedido', 'si confirmo', 'reservar',
            'apartar', 'separar', 'confirmar reserva'
        ]
        texto_lower = texto.lower().strip()
        return texto_lower in confirmaciones or any(c in texto_lower for c in confirmaciones if len(c) > 2)
    
    def _mostrar_resumen_carrito(self, tenant: dict, numero: str, carrito: dict) -> str:
        """Muestra el resumen del carrito"""
        if not carrito.get('items'):
            return "No tienes productos/servicios en tu carrito aún. ¿Qué te gustaría ordenar o reservar?"
        
        items_texto = ""
        for item in carrito['items']:
            subtotal = item.get('precio', 0) * item.get('cantidad', 1)
            items_texto += f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${subtotal:,.0f}\n"
        
        datos_pendientes = self._formatear_datos_cliente(self._datos_cliente.get(numero, {}))
        
        mensaje = f"""📋 **Tu pedido actual:**

{items_texto}
**Total:** ${carrito.get('total', 0):,.0f}"""
        
        if datos_pendientes:
            mensaje += f"""

📋 **Datos registrados:**
{datos_pendientes}"""
        
        mensaje += """

¿Algo más que deseas agregar o confirmamos el pedido? (responde "confirmo" para finalizar)"""
        
        return mensaje
    
    def _detectar_productos_con_ia(self, texto: str, menu: list) -> list:
        """Usa IA para detectar productos/servicios y cantidades"""
        if not ai_client.client or not menu:
            return []
        
        prompt = f"""
        El cliente quiere reservar un servicio o comprar un producto. Extrae el ítem del siguiente mensaje y relaciónalo con el catálogo.
        
        CATÁLOGO DISPONIBLE:
        {json.dumps([{'nombre': p.get('nombre'), 'precio': p.get('precio')} for p in menu[:30]], indent=2, ensure_ascii=False)}
        
        MENSAJE DEL CLIENTE: "{texto}"
        
        IMPORTANTE:
        - El cliente puede mencionar el servicio/producto de forma natural
        - Extrae la cantidad si la menciona (ej: "para 2 personas" → cantidad: 2, "2 tortas" → cantidad: 2)
        - Si no menciona cantidad, asume 1
        - Relaciona con el nombre más cercano en el catálogo
        
        Devuelve SOLO un JSON:
        {{
            "productos": [
                {{"nombre": "nombre exacto del catálogo", "cantidad": 1}}
            ]
        }}
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300
            )
            contenido = response.choices[0].message.content
            contenido = contenido.replace('```json', '').replace('```', '').strip()
            resultado = json.loads(contenido)
            
            productos_encontrados = []
            for p in resultado.get('productos', []):
                nombre = p.get('nombre', '')
                cantidad = p.get('cantidad', 1)
                
                # Buscar en el catálogo
                for producto in menu:
                    if producto['nombre'].lower() == nombre.lower() or nombre.lower() in producto['nombre'].lower():
                        productos_encontrados.append({
                            'nombre': producto['nombre'],
                            'precio': producto.get('precio', 0),
                            'cantidad': cantidad
                        })
                        break
            
            if productos_encontrados:
                logger.info(f"Servicios/Productos detectados: {productos_encontrados}")
            return productos_encontrados
        except Exception as e:
            logger.error(f'Error detectando servicios: {e}')
            return []
    
    def _detectar_productos_simples(self, texto: str, menu: list) -> list:
        """Detecta productos por coincidencia simple en el texto (sin IA)"""
        if not menu:
            return []
        
        texto_lower = texto.lower()
        productos_encontrados = []
        
        for producto in menu:
            nombre = producto.get('nombre', '').lower()
            # Buscar si el nombre del producto está en el texto
            if nombre in texto_lower:
                cantidad = 1
                # Buscar cantidad antes del producto (ej: "2 tortas", "3 empanadas")
                # Patrón: número + espacio + nombre del producto
                patron = rf'(\d+)\s*{re.escape(nombre)}'
                match = re.search(patron, texto_lower)
                if match:
                    cantidad = int(match.group(1))
                else:
                    # También buscar "una", "un"
                    if re.search(r'\buna?\s+' + re.escape(nombre), texto_lower):
                        cantidad = 1
                
                productos_encontrados.append({
                    'nombre': producto['nombre'],
                    'precio': producto.get('precio', 0),
                    'cantidad': cantidad
                })
                logger.info(f"Producto detectado por coincidencia simple: {producto['nombre']} x{cantidad}")
        
        return productos_encontrados

    def _procesar_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, contexto: dict) -> str:
        """Procesa el mensaje usando IA para entender lenguaje natural"""
        
        if not ai_client.client:
            return self._respuesta_fallback(tenant, menu)
        
        carrito_actual = self._cargar_carrito(tenant['id'], numero)
        resumen_cliente = self._get_resumen_cliente(tenant['id'], numero)
        
        # Obtener historial
        historial = self._get_historial_conversacion(tenant['id'], numero, 10)
        historial_texto = self._formatear_historial_para_prompt(historial)
        if historial:
            logger.info(f"Incluyendo {len(historial)} mensajes del historial")
        
        # Extraer y guardar datos del cliente
        self._extraer_y_guardar_datos(texto, numero)
        
        # Guardar datos en BD si hay información completa
        if numero in self._datos_cliente and self._datos_cliente[numero].get('nombre'):
            self._guardar_datos_cliente_en_bd(tenant['id'], numero)
        
        # ========== 1. VERIFICAR CONFIRMACIÓN ==========
        if self._cliente_confirmo(texto):
            if carrito_actual.get('items'):
                self._guardar_datos_cliente_en_bd(tenant['id'], numero)
                return self._finalizar_pedido(tenant, numero, carrito_actual)
            else:
                return "❌ No hay productos en tu carrito. Por favor, vuelve a indicarme qué deseas ordenar.\n\nEjemplo: 'quiero una torta de chocolate'"
        
        # ========== 2. VERIFICAR CONSULTA DE CARRITO ==========
        if any(palabra in texto.lower() for palabra in ['qué pedí', 'mi pedido', 'ver carrito', 'que tengo', 'mi reserva']):
            return self._mostrar_resumen_carrito(tenant, numero, carrito_actual)
        
        # ========== 3. DETECTAR PRODUCTOS (PRIORIDAD) ==========
        # Primero intentar con coincidencia simple (más rápida)
        productos_detectados = self._detectar_productos_simples(texto, menu)
        
        # Si no, usar IA para detectar productos
        if not productos_detectados:
            productos_detectados = self._detectar_productos_con_ia(texto, menu)
        
        # ========== 4. AGREGAR PRODUCTOS AL CARRITO ==========
        if productos_detectados:
            self._agregar_al_carrito(tenant['id'], numero, productos_detectados)
            nuevo_carrito = self._cargar_carrito(tenant['id'], numero)
            
            # Mostrar resumen con opción de confirmar
            items_texto = ""
            for item in nuevo_carrito['items']:
                subtotal = item.get('precio', 0) * item.get('cantidad', 1)
                items_texto += f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${subtotal:,.0f}\n"
            
            return f"""✅ **Productos agregados a tu pedido:**

    {items_texto}
    **Total:** ${nuevo_carrito.get('total', 0):,.0f}

    ¿Algo más o confirmamos el pedido? (responde "confirmo" para finalizar)"""
        
        # ========== 5. SI HAY CARRITO PERO NO SE DETECTARON PRODUCTOS ==========
        if carrito_actual.get('items'):
            return self._mostrar_resumen_carrito(tenant, numero, carrito_actual)
        
        # ========== 6. MOSTRAR MENÚ SI ESTÁ VACÍO ==========
        if menu:
            primeros = menu[:5]
            sugerencias = "\n".join([f"• {p['nombre']} - ${p['precio']:,.0f}" for p in primeros])
            return f"""🌟 **{tenant.get('nombre', 'Bienvenido')}**

    Estos son nuestros productos:

    {sugerencias}

    ¿Qué te gustaría ordenar? Escríbeme el nombre del producto."""
        
        # ========== 7. FALLBACK CON IA ==========
        # Solo llegar aquí si no hay productos detectados y no hay carrito
        menu_simplificado = []
        for p in menu[:30]:
            menu_simplificado.append({
                'nombre': p.get('nombre'),
                'precio': p.get('precio'),
                'descripcion': p.get('descripcion', '')[:100]
            })
        
        datos_pendientes = self._formatear_datos_cliente(self._datos_cliente.get(numero, {}))
        
        system_prompt = f"""Eres un asistente de ventas para {tenant.get('nombre', 'Mi negocio')}.

    🏪 INFORMACIÓN:
    - Horario: {contexto.get('horario', 'No especificado')}
    - Ubicación: {contexto.get('ubicacion', 'No especificada')}

    📋 PRODUCTOS:
    {json.dumps(menu_simplificado, indent=2, ensure_ascii=False)}

    {resumen_cliente}

    {historial_texto}

    INSTRUCCIONES:
    1. Responde de forma amable y natural en español.
    2. Ayuda al cliente a elegir un producto.
    3. No inventes productos que no están en el catálogo.
    """
        
        user_message = f"Cliente: {texto}\n\nAsistente:"
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=500
            )
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f'Error en IA: {e}')
            return self._respuesta_fallback(tenant, menu)
    
    def _parece_pedido(self, texto: str) -> bool:
        """Detecta si el mensaje parece un pedido de producto o servicio"""
        palabras_pedido = [
            'quiero', 'deseo', 'necesito', 'me gustaría', 'comprar', 
            'ordenar', 'pedir', 'reservar', 'agendar', 'tomar'
        ]
        
        # Palabras específicas de productos (para evitar confusiones)
        palabras_producto = [
            'torta', 'pastel', 'galleta', 'cheesecake', 'red velvet',
            'chocolate', 'vainilla', 'pizza', 'hamburguesa'
        ]
        
        # Palabras específicas de viajes/servicios
        palabras_servicio = [
            'tour', 'viaje', 'islas', 'rosario', 'barú', 'cartagena',
            'playa', 'vuelo', 'hotel', 'traslado', 'avión', 'reserva'
        ]
        
        texto_lower = texto.lower()
        
        # Si menciona palabras de servicio, es un pedido de servicio
        if any(palabra in texto_lower for palabra in palabras_servicio):
            return True
        
        # Si menciona palabras de producto, es pedido de producto
        if any(palabra in texto_lower for palabra in palabras_producto):
            return True
        
        # Si solo tiene palabras genéricas
        return any(palabra in texto_lower for palabra in palabras_pedido)
    
    def _intentar_agregar_producto(self, texto: str, tenant: dict, menu: list, numero: str, contexto: dict) -> str:
        """Intenta agregar un producto/servicio al carrito basado en el mensaje del cliente"""
        if not menu:
            return """📭 No hay servicios/productos cargados en el sistema.

Por favor, el administrador debe entrenar la IA con los servicios disponibles.

Mientras tanto, puedes contactarnos directamente al WhatsApp del negocio."""
        
        # Usar IA para identificar el producto/servicio
        prompt = f"""
        El cliente dice: "{texto}"
        
        Catálogo disponible:
        {json.dumps([{'nombre': p['nombre'], 'precio': p['precio']} for p in menu[:20]], indent=2, ensure_ascii=False)}
        
        ¿Qué producto o servicio quiere el cliente? Devuelve SOLO el nombre exacto del catálogo.
        Si no está seguro, devuelve "no_seguro".
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=50
            )
            producto_nombre = response.choices[0].message.content.strip().strip('"')
            
            if producto_nombre == "no_seguro":
                sugerencias = "\n".join([f"• {p['nombre']} - ${p['precio']:,.0f}" for p in menu[:5]])
                return f"Lo siento, no entendí qué deseas. Nuestros servicios/productos más populares:\n{sugerencias}\n¿Cuál te gustaría?"
            
            # Buscar el producto en el menú
            producto = None
            for p in menu:
                if p['nombre'].lower() == producto_nombre.lower():
                    producto = p
                    break
            
            if producto:
                self._agregar_al_carrito(tenant['id'], numero, [{'nombre': producto['nombre'], 'precio': producto['precio'], 'cantidad': 1}])
                nuevo_carrito = self._cargar_carrito(tenant['id'], numero)
                return f"✅ Agregado: {producto['nombre']} - ${producto['precio']:,.0f}\n\n{self._mostrar_resumen_carrito(tenant, numero, nuevo_carrito)}"
            else:
                sugerencias = "\n".join([f"• {p['nombre']} - ${p['precio']:,.0f}" for p in menu[:5]])
                return f"No encontré '{producto_nombre}' en el catálogo. Estos son nuestros servicios:\n{sugerencias}\n¿Cuál te gustaría?"
            
        except Exception as e:
            logger.error(f'Error identificando producto/servicio: {e}')
            sugerencias = "\n".join([f"• {p['nombre']} - ${p['precio']:,.0f}" for p in menu[:5]])
            return f"¿Qué te gustaría ordenar o reservar? Estos son algunos servicios:\n{sugerencias}"
    
    def _respuesta_fallback(self, tenant: dict, menu: list) -> str:
        """Respuesta de fallback cuando la IA no está disponible"""
        productos_sugeridos = menu[:5]
        if productos_sugeridos:
            sugerencias = "\n".join([f"• {p['nombre']} - ${p['precio']:,.0f}" for p in productos_sugeridos])
            return f"""Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}.

**Servicios/Productos sugeridos:**
{sugerencias}

¿Qué te gustaría ordenar o reservar? Puedes escribir "MENÚ" para ver el catálogo completo o decirme directamente lo que deseas."""
        else:
            return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿En qué puedo ayudarte hoy?"

# Instancia global
message_handler = MessageHandler()