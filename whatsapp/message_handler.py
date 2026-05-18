import json
import re
import uuid
from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from orders.repository import order_repo
from orders.payment import generar_link_pago
from whatsapp.client import whatsapp_client
from ai.client import ai_client
from core.logger import logger
from core.database import db_manager

class MessageHandler:
    """Procesa mensajes de WhatsApp usando IA con contexto personalizado y memoria"""
    
    def __init__(self):
        """Inicializa el manejador de mensajes"""
        self._datos_cliente = {}  # Almacena datos de clientes por número
        self._carritos_cache = {}  # Caché opcional para carritos
    
    def process(self, phone_id: str, numero: str, texto: str):
        """Procesa mensaje entrante y envía respuesta"""
        logger.info(f'Procesando mensaje de {numero}: {texto}')
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'Tenant no encontrado para phone_id: {phone_id}')
            return
        
        menu = schema_manager.get_menu(tenant['id'])
        pedidos_pendientes = order_repo.get_pendientes(tenant['id'], numero)
        contexto = self._obtener_contexto_tenant(tenant['id'])
        
        respuesta = self._responder_con_ia(texto, tenant, menu, numero, pedidos_pendientes, contexto)
        
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)

    def _obtener_contexto_tenant(self, tenant_id: str) -> dict:
        """Obtiene el contexto personalizado del tenant desde la base de datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        SELECT menu_estructurado, instrucciones, horario, ubicacion, 
                               politicas, prompt_personalizado 
                        FROM public.tenant_context 
                        WHERE tenant_id = %s
                    ''', (tenant_id,))
                    row = cur.fetchone()
                    
                    if row:
                        menu_estructurado = row[0]
                        if isinstance(menu_estructurado, str):
                            try:
                                menu_estructurado = json.loads(menu_estructurado)
                            except:
                                menu_estructurado = []
                        elif menu_estructurado is None:
                            menu_estructurado = []
                        
                        return {
                            'menu_estructurado': menu_estructurado,
                            'instrucciones': row[1] or '',
                            'horario': row[2] or '',
                            'ubicacion': row[3] or '',
                            'politicas': row[4] or '',
                            'prompt_personalizado': row[5] or ''
                        }
                    return {}
        except Exception as e:
            logger.error(f'Error obteniendo contexto para {tenant_id}: {e}')
            return {}
    
    def _extraer_datos_cliente(self, texto: str) -> dict:
        """Extrae datos del cliente del mensaje (nombre, cédula, teléfono, dirección, fecha)"""
        import re
        texto_lower = texto.lower()
        datos = {}
        
        # Patrones de búsqueda
        patrones = {
            'nombre': r'(?:soy|me llamo|mi nombre es|nombre:?)\s*([A-Za-záéíóúñ\s]+?)(?:\s*(?:y|,|cc|tel|$))',
            'cc': r'(?:cédula|cedula|cc|identificación|documento:?)\s*(\d{5,12})',
            'telefono': r'(?:tel|teléfono|telefono|cel|whatsapp:?)\s*(\d{7,15})',
            'email': r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            'direccion': r'(?:dirección|direccion|vivo en|mi dirección es:?)\s*([^,.]+(?:[,.][^,.]+)?)',
            'fecha_entrega': r'(?:para|entregar|recoger|para el|el día)\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+de\s+[a-z]+\s+del?\s+\d{2,4}|mañana|hoy|pasado mañana)',
            'hora_entrega': r'(?:a las|a la|alas|a las)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)',
            'recojo_en_tienda': r'(?:recojo|recoger|retiro|retirar)\s*(?:en la tienda|en tienda|local)',
            'pago_contraentrega': r'(?:pago\s+contra\s+entrega|contraentrega|pago\s+en\s+efectivo|efectivo|transferencia)'
        }
        
        for campo, patron in patrones.items():
            match = re.search(patron, texto, re.IGNORECASE)
            if match:
                datos[campo] = match.group(1).strip() if match.groups() else True
        
        return datos

    def _formatear_datos_cliente(self, datos: dict) -> str:
        """Formatea los datos del cliente para confirmación"""
        if not datos:
            return ""
        
        texto = ""
        if datos.get('nombre'):
            texto += f"📝 **Nombre:** {datos['nombre']}\n"
        if datos.get('cc'):
            texto += f"🆔 **Cédula:** {datos['cc']}\n"
        if datos.get('telefono'):
            texto += f"📞 **Teléfono:** {datos['telefono']}\n"
        if datos.get('email'):
            texto += f"📧 **Email:** {datos['email']}\n"
        if datos.get('direccion'):
            texto += f"📍 **Dirección:** {datos['direccion']}\n"
        if datos.get('fecha_entrega'):
            texto += f"📅 **Fecha de entrega:** {datos['fecha_entrega']}\n"
        if datos.get('hora_entrega'):
            texto += f"⏰ **Hora:** {datos['hora_entrega']}\n"
        if datos.get('recojo_en_tienda'):
            texto += f"🏪 **Recojo en tienda**\n"
        if datos.get('pago_contraentrega'):
            texto += f"💰 **Pago:** Contraentrega / Efectivo\n"
        
        return texto

    def _guardar_conversacion(self, tenant_id: str, cliente_numero: str, mensaje: str, respuesta: str):
        """Guarda la conversación en el esquema del tenant"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Verificar si la tabla existe, si no, crearla
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {tenant_id}.conversaciones (
                            id SERIAL PRIMARY KEY,
                            cliente_id UUID REFERENCES {tenant_id}.clientes(id) ON DELETE SET NULL,
                            cliente_numero TEXT NOT NULL,
                            mensaje TEXT NOT NULL,
                            respuesta TEXT,
                            tipo VARCHAR(20) DEFAULT 'cliente',
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    
                    # Insertar conversación
                    cur.execute(f"""
                        INSERT INTO {tenant_id}.conversaciones (cliente_numero, mensaje, respuesta)
                        VALUES (%s, %s, %s)
                    """, (cliente_numero, mensaje, respuesta))
                conn.commit()
                logger.info(f"Conversación guardada en {tenant_id}.conversaciones")
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
            
    # ==================== MÉTODOS DEL CARRITO ====================

    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        """Guarda el carrito en la base de datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    # Eliminar carrito anterior
                    cur.execute("DELETE FROM public.carritos WHERE tenant_id = %s AND cliente_numero = %s", 
                            (tenant_id, cliente_numero))
                    # Insertar nuevo carrito - convertir items a JSON string
                    cur.execute("""
                        INSERT INTO public.carritos (tenant_id, cliente_numero, items, total)
                        VALUES (%s, %s, %s, %s)
                    """, (tenant_id, cliente_numero, json.dumps(items), total))
                conn.commit()
                logger.info(f"Carrito guardado para {cliente_numero}: {len(items)} items, total ${total}")
        except Exception as e:
            logger.error(f'Error guardando carrito: {e}')

    def _cargar_carrito(self, tenant_id: str, cliente_numero: str) -> dict:
        """Carga el carrito desde la base de datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT items, total FROM public.carritos 
                        WHERE tenant_id = %s AND cliente_numero = %s
                    """, (tenant_id, cliente_numero))
                    row = cur.fetchone()
                    if row:
                        # items puede ser string o dict, asegurarse de que sea lista
                        items = row[0]
                        if isinstance(items, str):
                            items = json.loads(items)
                        elif items is None:
                            items = []
                        return {'items': items, 'total': row[1]}
                    return {'items': [], 'total': 0}
        except Exception as e:
            logger.error(f'Error cargando carrito: {e}')
            return {'items': [], 'total': 0}
        
    def _agregar_al_carrito(self, tenant_id: str, cliente_numero: str, productos: list):
        """Agrega productos al carrito del cliente usando BD"""
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        
        for p in productos:
            encontrado = False
            for item in carrito['items']:
                if item['nombre'] == p['nombre']:
                    item['cantidad'] += p['cantidad']
                    encontrado = True
                    break
            if not encontrado:
                carrito['items'].append(p)
            carrito['total'] += p['precio'] * p['cantidad']
        
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
        
    def _actualizar_cantidad_en_carrito(self, tenant_id: str, cliente_numero: str, producto_nombre: str, nueva_cantidad: int):
        """Actualiza la cantidad de un producto en el carrito"""
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        
        for item in carrito['items']:
            if item['nombre'] == producto_nombre:
                vieja_cantidad = item['cantidad']
                diferencia = nueva_cantidad - vieja_cantidad
                item['cantidad'] = nueva_cantidad
                carrito['total'] += item['precio'] * diferencia
                logger.info(f"Cantidad actualizada: {producto_nombre} de {vieja_cantidad} a {nueva_cantidad}")
                break
        
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
    
    # ==================== MÉTODOS DEL HISTORIAL ====================

    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 5) -> list:
        """Obtiene el historial de conversación desde el esquema del tenant"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Verificar si la tabla existe
                    cur.execute(f"""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = %s AND table_name = 'conversaciones'
                        )
                    """, (tenant_id,))
                    if not cur.fetchone()[0]:
                        return []
                    
                    cur.execute(f"""
                        SELECT mensaje, respuesta, created_at 
                        FROM {tenant_id}.conversaciones 
                        WHERE cliente_numero = %s 
                        ORDER BY created_at DESC 
                        LIMIT %s
                    """, (cliente_numero, limit))
                    rows = cur.fetchall()
                    return list(reversed(rows))
        except Exception as e:
            logger.error(f'Error obteniendo historial: {e}')
            return []
        
    def _formatear_historial_para_prompt(self, historial: list) -> str:
        """Formatea el historial para incluirlo en el prompt de IA"""
        if not historial:
            return ""
        
        texto = "\n\nHISTORIAL DE LA CONVERSACIÓN:\n"
        for h in historial:
            texto += f"Cliente: {h[0]}\n"
            texto += f"Asistente: {h[1]}\n"
        return texto

    # ==================== DETECCIÓN DE PRODUCTOS ====================

    def _detectar_productos_en_texto(self, texto: str, menu: list) -> list:
        """Detecta productos y cantidades en el texto (mejorado)"""
        import re
        productos_encontrados = []
        texto_lower = texto.lower()
        
        for producto in menu:
            nombre = producto['nombre'].lower()
            if nombre in texto_lower:
                cantidad = 1
                
                # Buscar número antes del producto (ej: "32 empanadas", "100 empanadas")
                patron = rf'(\d+)\s*{re.escape(nombre)}'
                match = re.search(patron, texto_lower)
                if match:
                    cantidad = int(match.group(1))
                    logger.info(f"Cantidad detectada: {cantidad} {nombre}")
                
                productos_encontrados.append({
                    'nombre': producto['nombre'],
                    'precio': producto['precio'],
                    'cantidad': cantidad
                })
                logger.info(f"Producto detectado: {producto['nombre']} x{cantidad}")
        
        return productos_encontrados

    def _detectar_productos_con_ia(self, texto: str, menu: list) -> list:
        """Usa IA para detectar productos y cantidades"""
        if not ai_client.client or not menu:
            return []
        
        prompt = f"""
        Extrae productos del siguiente mensaje.
        
        MENÚ DISPONIBLE:
        {json.dumps([{'nombre': p['nombre']} for p in menu[:50]], indent=2)}
        
        MENSAJE: "{texto}"
        
        Devuelve SOLO un JSON con la lista de productos encontrados:
        {{
            "productos": [
                {{"nombre": "nombre exacto del producto", "cantidad": 1}}
            ]
        }}
        
        Si no hay productos, devuelve {{"productos": []}}
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
                # Buscar el producto en el menú
                for producto in menu:
                    if producto['nombre'].lower() == nombre.lower() or nombre.lower() in producto['nombre'].lower():
                        productos_encontrados.append({
                            'nombre': producto['nombre'],
                            'precio': producto['precio'],
                            'cantidad': cantidad
                        })
                        break
            return productos_encontrados
        except Exception as e:
            logger.error(f'Error detectando productos con IA: {e}')
            return []

    # ==================== RESPUESTAS DEL CARRITO ====================

    def _mostrar_carrito_confirmacion(self, tenant: dict, numero: str, carrito: dict) -> str:
        """Muestra el carrito y pregunta si quiere agregar más"""
        if not carrito.get('items'):
            return "No tienes productos en tu pedido aún. ¿Qué te gustaría ordenar?"
        
        items_texto = ""
        for item in carrito['items']:
            subtotal = item['precio'] * item['cantidad']
            items_texto += f"• {item['cantidad']}x {item['nombre']}: ${subtotal:,.0f}\n"
        
        total = carrito['total']
        
        return f"""📋 **Tu pedido:**

{items_texto}
**Total:** ${total:,.0f}

¿Algo más que deseas agregar o procedemos con el pedido?"""

    def _mostrar_carrito(self, tenant: dict, numero: str, carrito: dict) -> str:
        """Muestra el carrito actual"""
        if not carrito.get('items'):
            return "No tienes productos en tu pedido aún. ¿Qué te gustaría ordenar?"
        
        items_texto = ""
        for item in carrito['items']:
            subtotal = item['precio'] * item['cantidad']
            items_texto += f"• {item['cantidad']}x {item['nombre']}: ${subtotal:,.0f}\n"
        
        total = carrito['total']
        
        return f"""📋 **Tu pedido actual:**

{items_texto}
**Total:** ${total:,.0f}"""

    def _obtener_o_crear_cliente(self, tenant_id: str, numero: str, datos_cliente: dict = None) -> str:
        """Obtiene un cliente existente o lo crea con los datos proporcionados"""
        try:
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    # Asegurar que la tabla clientes existe
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {tenant_id}.clientes (
                            id UUID PRIMARY KEY,
                            numero_telefono TEXT UNIQUE NOT NULL,
                            nombre TEXT,
                            cc TEXT,
                            email TEXT,
                            direccion TEXT,
                            direccion_despacho TEXT,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    conn.commit()
                    
                    # Buscar cliente por teléfono
                    cur.execute(f"SELECT id, nombre, cc, email, direccion FROM {tenant_id}.clientes WHERE numero_telefono = %s", (numero,))
                    row = cur.fetchone()
                    
                    if row:
                        cliente_id = row[0]
                        # Actualizar datos faltantes
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
                                cur.execute(f"UPDATE {tenant_id}.clientes SET {', '.join(updates)}, updated_at = NOW() WHERE id = %s", params)
                                conn.commit()
                        return cliente_id
                    else:
                        # Crear nuevo cliente
                        cliente_id = str(uuid.uuid4())
                        cur.execute(f"""
                            INSERT INTO {tenant_id}.clientes (id, numero_telefono, nombre, cc, email, direccion, direccion_despacho)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (
                            cliente_id, numero,
                            datos_cliente.get('nombre') if datos_cliente else None,
                            datos_cliente.get('cc') if datos_cliente else None,
                            datos_cliente.get('email') if datos_cliente else None,
                            datos_cliente.get('direccion') if datos_cliente else None,
                            datos_cliente.get('direccion_despacho') if datos_cliente else None
                        ))
                        conn.commit()
                        return cliente_id
        except Exception as e:
            logger.error(f'Error gestionando cliente: {e}')
            return None

    def _finalizar_pedido(self, tenant: dict, numero: str, carrito: dict) -> str:
        """Finaliza el pedido, guarda datos del cliente y genera link de pago"""
        if not carrito or not carrito.get('items'):
            return "No hay productos en tu pedido. ¿Qué te gustaría ordenar?"
        
        # Obtener datos del cliente guardados previamente
        datos_cliente = self._datos_cliente.get(numero, {})
        
        # Obtener o crear cliente en la base de datos
        cliente_id = self._obtener_o_crear_cliente(tenant['id'], numero, datos_cliente)
        if not cliente_id:
            return "❌ Hubo un error con tus datos. Por favor intenta de nuevo."
        
        pedido_id = str(uuid.uuid4())
        items = carrito['items']
        total = carrito['total']
        
        # Obtener secuencial para número de pedido
        with db_manager.get_connection(tenant['id']) as conn:
            with conn.cursor() as cur:
                # Asegurar tabla pedidos existe
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {tenant['id']}.pedidos (
                        id UUID PRIMARY KEY,
                        cliente_id UUID,
                        cliente_numero TEXT NOT NULL,
                        numero_pedido TEXT NOT NULL,
                        secuencial INTEGER NOT NULL,
                        items JSONB NOT NULL,
                        total INTEGER NOT NULL,
                        estado TEXT DEFAULT 'nuevo',
                        direccion_entrega TEXT,
                        notas TEXT,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW(),
                        pagado_at TIMESTAMP,
                        enviado_at TIMESTAMP,
                        cancelado_at TIMESTAMP
                    )
                """)
                conn.commit()
                
                cur.execute(f"SELECT COALESCE(MAX(secuencial), 0) + 1 FROM {tenant['id']}.pedidos")
                secuencial = cur.fetchone()[0]
        
        numero_pedido = db_manager.generar_numero_pedido(tenant['id'], secuencial)
        
        # Preparar dirección de entrega
        direccion_entrega = datos_cliente.get('direccion', '')
        if datos_cliente.get('recojo_en_tienda'):
            direccion_entrega = "Recojo en tienda"
        
        try:
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO {tenant['id']}.pedidos 
                        (id, cliente_id, cliente_numero, numero_pedido, secuencial, items, total, estado, direccion_entrega, notas)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        pedido_id, cliente_id, numero, numero_pedido, secuencial, json.dumps(items), 
                        total, "nuevo", direccion_entrega, 
                        f"Fecha entrega: {datos_cliente.get('fecha_entrega', '')} Hora: {datos_cliente.get('hora_entrega', '')}".strip()
                    ))
                conn.commit()
            
            # Limpiar carrito y datos del cliente
            self._guardar_carrito(tenant['id'], numero, [], 0)
            if numero in self._datos_cliente:
                del self._datos_cliente[numero]
            
            link_pago = generar_link_pago(total, pedido_id)
            
            # Formatear items para el mensaje
            items_texto = ""
            for item in items:
                subtotal = item['precio'] * item['cantidad']
                items_texto += f"• {item['cantidad']}x {item['nombre']}: ${subtotal:,.0f}\n"
            
            # Formatear datos del cliente para confirmación
            datos_texto = ""
            if datos_cliente.get('nombre'):
                datos_texto += f"\n📝 **Cliente:** {datos_cliente['nombre']}"
            if datos_cliente.get('cc'):
                datos_texto += f"\n🆔 **Cédula:** {datos_cliente['cc']}"
            if datos_cliente.get('telefono'):
                datos_texto += f"\n📞 **Teléfono:** {datos_cliente['telefono']}"
            if datos_cliente.get('email'):
                datos_texto += f"\n📧 **Email:** {datos_cliente['email']}"
            if direccion_entrega:
                datos_texto += f"\n📍 **Entrega:** {direccion_entrega}"
            if datos_cliente.get('fecha_entrega'):
                datos_texto += f"\n📅 **Fecha:** {datos_cliente['fecha_entrega']}"
            if datos_cliente.get('hora_entrega'):
                datos_texto += f"\n⏰ **Hora:** {datos_cliente['hora_entrega']}"
            
            return f"""✅ **¡Pedido #{numero_pedido} confirmado!**{datos_texto}

📋 **Productos:**
{items_texto}
💰 **Total:** ${total:,.0f}

🔗 **Link de pago:** {link_pago}

📌 Cuando completes el pago, avísame para empezar a preparar tu pedido."""
                
        except Exception as e:
            logger.error(f'Error creando pedido: {e}')
            return "❌ Hubo un error procesando tu pedido. Por favor intenta de nuevo."
    
    # ==================== RESPUESTA PRINCIPAL CON IA ====================

    def _responder_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, 
                      pedidos_pendientes: list, contexto: dict) -> str:
        """Usa DeepSeek con contexto personalizado y manejo de carrito"""
        
        if not ai_client.client:
            return self._respuesta_fallback(texto, tenant, menu, numero)
        
        texto_lower = texto.lower()
        
        # Cargar carrito desde BD
        carrito_actual = self._cargar_carrito(tenant['id'], numero)
        
        # 1. Detectar pagos (natural)
        if any(palabra in texto_lower for palabra in ['pague', 'pago', 'pagado', 'transferí', 'consigné', 'pagué', 'ya pague', 'listo el pago']):
            order_repo.marcar_pagado(tenant['id'], numero)
            return "✅ ¡Pago confirmado! En breve comenzamos a preparar tu pedido."
        
        # 2. Detectar confirmación de pedido
        if any(palabra in texto_lower for palabra in ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'esta bien', 'está bien', 'adelante', 'procesar', 'confirmar pedido']):
            if carrito_actual.get('items'):
                return self._finalizar_pedido(tenant, numero, carrito_actual)
        
        # 3. Detectar cancelación
        if any(palabra in texto_lower for palabra in ['cancela', 'cancelar', 'no quiero', 'mejor no']):
            self._guardar_carrito(tenant['id'], numero, [], 0)
            return "❌ Pedido cancelado. Estaré aquí cuando necesites algo."
        
        # 4. Ver carrito
        if any(palabra in texto_lower for palabra in ['que pedí', 'que tengo', 'mi pedido', 'ver carrito']):
            return self._mostrar_carrito(tenant, numero, carrito_actual)
        
        # 5. Detectar productos para agregar al carrito (usando IA)
        productos_detectados = self._detectar_productos_con_ia(texto, menu)
        
        if productos_detectados:
            self._agregar_al_carrito(tenant['id'], numero, productos_detectados)
            nuevo_carrito = self._cargar_carrito(tenant['id'], numero)
            
            # Extraer datos del cliente con IA
            datos_extraidos = self._extraer_datos_con_ia(texto)
            if datos_extraidos and any(datos_extraidos.values()):
                if numero not in self._datos_cliente:
                    self._datos_cliente[numero] = {}
                self._datos_cliente[numero].update(datos_extraidos)
                
                datos_formateados = self._formatear_datos_cliente(self._datos_cliente[numero])
                if datos_formateados:
                    return f"""{self._mostrar_carrito_confirmacion(tenant, numero, nuevo_carrito)}

📋 **Datos registrados:**
{datos_formateados}

¿Confirmas el pedido con estos datos?"""
            
            return self._mostrar_carrito_confirmacion(tenant, numero, nuevo_carrito)
        
        # 6. Si no hay productos detectados, usar IA para respuesta general Y extraer datos
        historial = self._get_historial_conversacion(tenant['id'], numero, 5)
        historial_texto = self._formatear_historial_para_prompt(historial)
        
        # Extraer datos del cliente con IA incluso si no hay productos
        datos_extraidos = self._extraer_datos_con_ia(texto)
        if datos_extraidos and any(datos_extraidos.values()):
            if numero not in self._datos_cliente:
                self._datos_cliente[numero] = {}
            self._datos_cliente[numero].update(datos_extraidos)
        
        # Construir prompt del sistema
        if contexto.get('prompt_personalizado'):
            system_prompt = contexto['prompt_personalizado'] + historial_texto
        else:
            system_prompt = self._construir_prompt_sistema(tenant, menu, pedidos_pendientes, contexto) + historial_texto
        
        # Agregar información del carrito y datos del cliente
        carrito_info = self._get_carrito_info_para_prompt(tenant['id'], numero)
        if carrito_info:
            system_prompt += f"\n\n{carrito_info}"
        
        datos_cliente_info = self._formatear_datos_cliente(self._datos_cliente.get(numero, {}))
        if datos_cliente_info:
            system_prompt += f"\n\nDatos del cliente registrados:\n{datos_cliente_info}"
        
        system_prompt += "\n\nIMPORTANTE: Si el cliente proporcionó información de contacto (nombre, cédula, teléfono, dirección, fecha/hora de entrega, forma de pago), confírmala y pregunta si desea finalizar el pedido."
        
        user_message = f"Cliente dice: \"{texto}\"\nGenera una respuesta amable y natural."
        
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
            logger.error(f'Error llamando a DeepSeek: {e}')
            return self._respuesta_fallback(texto, tenant, menu, numero)
    
    def _get_carrito_info_para_prompt(self, tenant_id: str, numero: str) -> str:
        """Obtiene información del carrito para el prompt"""
        if not tenant_id:
            return ""
        
        carrito = self._cargar_carrito(tenant_id, numero)
        if not carrito.get('items'):
            return ""
        
        items_texto = ""
        for item in carrito['items']:
            items_texto += f"- {item['cantidad']}x {item['nombre']}: ${item['precio'] * item['cantidad']:,.0f}\n"
        return f"Productos en carrito:\n{items_texto}Total: ${carrito.get('total', 0):,.0f}"

    def _construir_prompt_sistema(self, tenant: dict, menu: list, pedidos_pendientes: list, contexto: dict) -> str:
        """Construye prompt del sistema"""
        nombre_negocio = tenant.get('nombre', 'Mi negocio')
        horario = contexto.get('horario', 'No especificado')
        ubicacion = contexto.get('ubicacion', 'No especificada')
        instrucciones = contexto.get('instrucciones', '')
        
        prompt = f"""Eres un asistente de ventas por WhatsApp para {nombre_negocio}.

INFORMACIÓN DEL NEGOCIO:
- Horario: {horario}
- Ubicación: {ubicacion}
- Instrucciones especiales: {instrucciones}

MENÚ DISPONIBLE:
"""
        # Agregar primeros 20 productos del menú
        for i, producto in enumerate(menu[:20]):
            prompt += f"- {producto['nombre']}: ${producto['precio']:,.0f}\n"
        
        if len(menu) > 20:
            prompt += f"... y {len(menu) - 20} productos más.\n"
        
        prompt += """
REGLAS IMPORTANTES:
1. Sé amable, natural y servicial
2. Ayuda al cliente a armar su pedido
3. Confirma los datos del cliente cuando los proporcione
4. Si el cliente no especifica cantidad, asume 1 unidad
5. No inventes productos que no están en el menú
6. El link de pago se genera automáticamente al finalizar el pedido
7. Pregunta por datos de contacto si no los tiene: nombre, cédula, dirección, fecha/hora de entrega
8. Si el cliente dice "recojo en tienda", no preguntes por dirección de despacho
"""
        return prompt

    def _respuesta_fallback(self, texto: str, tenant: dict, menu: list, numero: str) -> str:
        """Respuesta de fallback"""
        return f"Hola! Soy el asistente de {tenant['nombre']}. ¿Qué te gustaría ordenar? Tenemos {len(menu)} productos disponibles."

    # ==================== EXTRAER DATOS CON IA (NO USA REGEX) ====================

    def _extraer_datos_con_ia(self, texto: str) -> dict:
        """Usa IA para extraer datos del cliente del mensaje"""
        if not ai_client.client:
            return {}
        
        prompt = f"""
        Extrae información del cliente del siguiente mensaje.
        
        MENSAJE: "{texto}"
        
        Devuelve SOLO un JSON con estos campos (si no los encuentras, déjalos vacíos):
        {{
            "nombre": "nombre completo",
            "cc": "número de cédula",
            "telefono": "número de teléfono",
            "email": "correo electrónico",
            "direccion": "dirección completa",
            "fecha_entrega": "fecha de entrega o recogida",
            "hora_entrega": "hora de entrega o recogida",
            "recojo_en_tienda": true/false,
            "pago_contraentrega": true/false
        }}
        
        IMPORTANTE: 
        - Si dice "recojo en tienda" o "recoger en tienda", pon recojo_en_tienda: true
        - Si dice "pago contraentrega", "efectivo", "contra entrega", pon pago_contraentrega: true
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300
            )
            contenido = response.choices[0].message.content
            # Limpiar markdown
            contenido = contenido.replace('```json', '').replace('```', '').strip()
            return json.loads(contenido)
        except Exception as e:
            logger.error(f'Error extrayendo datos con IA: {e}')
            return {}


# Instancia global
message_handler = MessageHandler()