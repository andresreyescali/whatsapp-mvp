import json
import re
import uuid
import os
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
        self._conversacion_activa = {}
        self._pedido_confirmado = {}  # {numero: True/False}
        self._pedido_confirmado_time = {}  # {numero: timestamp}
    
    def _get_schema_name(self, tenant_id: str) -> str:
        tenant = tenant_repo.find_by_id(tenant_id)
        if tenant and tenant.get('schema_name'):
            return tenant['schema_name']
        return f"tenant_{tenant_id.replace('-', '_')}"

    # ================== Limpia comillas =============================    
    def _limpiar_mensaje(self, texto: str) -> str:
        """Limpia comillas y caracteres especiales del mensaje"""
        if not texto:
            return texto
        texto = re.sub(r'^[\'"]+|[\'"]+$', '', texto)
        return texto.strip()

    def process(self, phone_id: str, numero: str, texto: str):
        texto = self._limpiar_mensaje(texto)
        logger.info(f"🟢 [PROCESS] Cliente: {numero}, Mensaje: {texto[:100]}")
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'⚠️ Tenant no encontrado para phone_id: {phone_id}')
            return
        
        schema_manager.ensure_schema(tenant['id'])
        
        # ========== VERIFICAR Y RESETEAR PEDIDO EXPIRADO ==========
        if self._pedido_confirmado.get(numero):
            tiempo_confirmado = self._pedido_confirmado_time.get(numero)
            if tiempo_confirmado:
                minutos_pasados = (datetime.now() - tiempo_confirmado).total_seconds() / 60
                if minutos_pasados > 30:
                    self._pedido_confirmado[numero] = False
                    self._pedido_confirmado_time[numero] = None
                    logger.info(f"🔄 Pedido confirmado expirado para {numero}")
        
        contexto = self._obtener_contexto_tenant(tenant['id'])
        menu = self._obtener_menu(tenant['id'])
        
        conv_activa = self._conversacion_activa.get(numero)
        
        if conv_activa and conv_activa.get('estado') == 'confirmando_pedido':
            respuesta = self._procesar_confirmacion(texto, tenant, numero, conv_activa)
        else:
            respuesta = self._procesar_con_ia(tenant, menu, numero, texto, contexto)
        
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
                        WHERE disponible = true
                        ORDER BY categoria, nombre
                        LIMIT 200
                    """)
                    rows = cur.fetchall()
                    return [{
                        'id': str(row[0]),
                        'nombre': row[1],
                        'descripcion': row[2] or '',
                        'precio': row[3],
                        'categoria': row[4] or 'general',
                        'disponible': row[5],
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
    
    def _get_historial_conversacion(self, tenant_id: str, cliente_numero: str, limit: int = 15) -> list:
        """Obtiene el historial de conversación en orden cronológico"""
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
                    logger.info(f"📜 Historial recuperado: {len(rows)} mensajes para {cliente_numero}")
                    return rows
        except Exception as e:
            logger.error(f'Error obteniendo historial: {e}')
            return []
    
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
            return {'items': [], 'total': 0}
    
    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id FROM "{schema_name}".carritos WHERE cliente_numero = %s
                    """, (cliente_numero,))
                    existing = cur.fetchone()
                    items_json = json.dumps(items)
                    if existing:
                        cur.execute(f"""
                            UPDATE "{schema_name}".carritos 
                            SET items = %s, total = %s, updated_at = NOW()
                            WHERE cliente_numero = %s
                        """, (items_json, total, cliente_numero))
                    else:
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".carritos (cliente_numero, items, total, created_at, updated_at)
                            VALUES (%s, %s, %s, NOW(), NOW())
                        """, (cliente_numero, items_json, total))
                    conn.commit()
        except Exception as e:
            logger.error(f'Error guardando carrito: {e}')
    
    def _limpiar_carrito(self, tenant_id: str, cliente_numero: str):
        self._guardar_carrito(tenant_id, cliente_numero, [], 0)
    
    # ==================== GESTIÓN DE CLIENTES ====================
    
    def _extraer_datos_cliente(self, mensaje: str) -> dict:
        """Extrae datos del cliente del mensaje usando expresiones regulares"""
        datos = {}
        mensaje_lower = mensaje.lower()
        
        patrones_nombre = [
            r'me llamo\s+([A-Za-zÁÉÍÓÚáéíóúÑñ\s]+)',
            r'mi nombre es\s+([A-Za-zÁÉÍÓÚáéíóúÑñ\s]+)',
            r'soy\s+([A-Za-zÁÉÍÓÚáéíóúÑñ\s]+)',
            r'nombre[:\s]+([A-Za-zÁÉÍÓÚáéíóúÑñ\s]+)'
        ]
        for patron in patrones_nombre:
            match = re.search(patron, mensaje_lower, re.IGNORECASE)
            if match:
                nombre = match.group(1).strip().title()
                if len(nombre) > 2 and not any(p in nombre.lower() for p in ['quiero', 'necesito', 'quisiera', 'me gustaría']):
                    datos['nombre'] = nombre
                    break
        
        patron_email = r'[\w\.-]+@[\w\.-]+\.\w+'
        match = re.search(patron_email, mensaje)
        if match:
            datos['email'] = match.group(0)
        
        patrones_direccion = [
            r'vivo en\s+([A-Za-z0-9ÁÉÍÓÚáéíóúÑñ\s\#,\.\-]+)',
            r'dirección[:\s]+([A-Za-z0-9ÁÉÍÓÚáéíóúÑñ\s\#,\.\-]+)',
            r'mi dirección es\s+([A-Za-z0-9ÁÉÍÓÚáéíóúÑñ\s\#,\.\-]+)'
        ]
        for patron in patrones_direccion:
            match = re.search(patron, mensaje_lower, re.IGNORECASE)
            if match:
                direccion = match.group(1).strip()
                if len(direccion) > 5:
                    datos['direccion'] = direccion
                    break
        
        patron_cc = r'\b(\d{8,10})\b'
        match = re.search(patron_cc, mensaje)
        if match:
            cc = match.group(1)
            if len(cc) >= 8:
                datos['cc'] = cc
        
        return datos
    
    def _cargar_cliente(self, tenant_id: str, telefono: str) -> dict:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, numero_telefono, nombre, cc, email, direccion, 
                               direccion_despacho, created_at, updated_at, ultimo_pedido
                        FROM "{schema_name}".clientes
                        WHERE numero_telefono = %s
                    """, (telefono,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'id': str(row[0]),
                            'telefono': row[1],
                            'nombre': row[2],
                            'cc': row[3],
                            'email': row[4],
                            'direccion': row[5],
                            'direccion_despacho': row[6],
                            'created_at': row[7],
                            'updated_at': row[8],
                            'ultimo_pedido': row[9]
                        }
                    return {}
        except Exception as e:
            logger.error(f'Error cargando cliente: {e}')
            return {}
    
    def _guardar_datos_cliente(self, tenant_id: str, telefono: str, mensaje: str):
        datos = self._extraer_datos_cliente(mensaje)
        if datos:
            logger.info(f"📝 Datos detectados para {telefono}: {datos}")
            try:
                schema_name = self._get_schema_name(tenant_id)
                with db_manager.get_connection(tenant_id) as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"""
                            SELECT id FROM "{schema_name}".clientes 
                            WHERE numero_telefono = %s
                        """, (telefono,))
                        existing = cur.fetchone()
                        if existing:
                            updates = []
                            params = []
                            for campo, valor in datos.items():
                                if valor:
                                    updates.append(f"{campo} = %s")
                                    params.append(valor)
                            if updates:
                                updates.append("updated_at = NOW()")
                                params.append(telefono)
                                cur.execute(f"""
                                    UPDATE "{schema_name}".clientes
                                    SET {', '.join(updates)}
                                    WHERE numero_telefono = %s
                                """, params)
                                logger.info(f"✅ Cliente actualizado: {telefono}")
                        else:
                            cur.execute(f"""
                                INSERT INTO "{schema_name}".clientes 
                                (numero_telefono, nombre, cc, email, direccion, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                            """, (telefono, datos.get('nombre'), datos.get('cc'), datos.get('email'), datos.get('direccion')))
                            logger.info(f"✅ Nuevo cliente creado: {telefono}")
                    conn.commit()
            except Exception as e:
                logger.error(f"Error guardando cliente: {e}")
            return datos
        return None
    
    def _obtener_contexto_cliente(self, tenant_id: str, telefono: str) -> str:
        cliente = self._cargar_cliente(tenant_id, telefono)
        if not cliente or not any([cliente.get('nombre'), cliente.get('email'), cliente.get('direccion')]):
            return ""
        contexto = "\n📋 *DATOS DEL CLIENTE (YA REGISTRADOS):*\n"
        if cliente.get('nombre'):
            contexto += f"- Nombre: {cliente['nombre']}\n"
        if cliente.get('email'):
            contexto += f"- Email: {cliente['email']}\n"
        if cliente.get('direccion'):
            contexto += f"- Dirección: {cliente['direccion']}\n"
        if cliente.get('cc'):
            contexto += f"- Cédula: {cliente['cc']}\n"
        contexto += "\n⚠️ NO preguntes estos datos nuevamente ya que el cliente ya los proporcionó.\n"
        contexto += "Si el cliente quiere actualizar algún dato, actualízalo y confirma el cambio.\n"
        return contexto
    
    # ==================== FUNCIONES QUE LA IA LLAMA ====================
    
    def _agregar_producto_al_carrito(self, tenant_id: str, cliente_numero: str, nombre: str, precio: int, cantidad: int = 1):
        logger.info(f"🛒 Agregando producto estándar: {cantidad}x {nombre} (${precio})")
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        if not carrito:
            carrito = {'items': [], 'total': 0}
        encontrado = False
        for item in carrito['items']:
            if item.get('nombre') == nombre and not item.get('personalizado', False):
                item['cantidad'] += cantidad
                carrito['total'] += precio * cantidad
                encontrado = True
                logger.info(f"✅ Producto existente actualizado: {nombre} ahora {item['cantidad']} unidades")
                break
        if not encontrado:
            carrito['items'].append({
                'nombre': nombre,
                'precio': precio,
                'cantidad': cantidad,
                'personalizado': False,
                'added_at': datetime.now().isoformat()
            })
            carrito['total'] += precio * cantidad
            logger.info(f"✅ Nuevo producto agregado: {nombre}")
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
        logger.info(f"📦 Carrito ahora: {len(carrito['items'])} items, total: ${carrito['total']}")
        return True

    def _agregar_producto_personalizado_al_carrito(self, tenant_id: str, cliente_numero: str, 
                                                    nombre: str, precio: int, 
                                                    detalles: dict = None, cantidad: int = 1):
        logger.info(f"🛒 Agregando producto personalizado: {cantidad}x {nombre} (${precio})")
        logger.info(f"📝 Detalles: {detalles}")
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        if not carrito:
            carrito = {'items': [], 'total': 0}
        carrito['items'].append({
            'nombre': nombre,
            'precio': precio,
            'cantidad': cantidad,
            'personalizado': True,
            'detalles': detalles or {},
            'added_at': datetime.now().isoformat()
        })
        carrito['total'] += precio * cantidad
        self._guardar_carrito(tenant_id, cliente_numero, carrito['items'], carrito['total'])
        logger.info(f"✅ Producto personalizado agregado. Total items: {len(carrito['items'])}, total: ${carrito['total']}")
        return True
    
    def _listar_productos(self, tenant_id: str, categoria: str = None, detalle: str = "resumen") -> str:
        """
        Lista los productos disponibles en la base de datos del tenant.
        Puede filtrar por categoría y elegir nivel de detalle.
        """
        try:
            # Obtener productos frescos de la BD
            productos = self._obtener_menu(tenant_id)
            
            if not productos:
                return "📭 No hay productos disponibles en este momento."
            
            # Filtrar por categoría si se especifica
            productos_filtrados = productos
            if categoria:
                categoria_lower = categoria.lower()
                productos_filtrados = []
                for p in productos:
                    p_categoria = p.get('categoria', '').lower()
                    # Buscar coincidencia parcial o exacta
                    if (categoria_lower in p_categoria or 
                        p_categoria in categoria_lower or
                        categoria_lower in p.get('nombre', '').lower()):
                        productos_filtrados.append(p)
                
                if not productos_filtrados:
                    # Buscar por nombre de producto si no encuentra por categoría
                    for p in productos:
                        if categoria_lower in p.get('nombre', '').lower():
                            productos_filtrados.append(p)
                    
                    if not productos_filtrados:
                        # Mostrar categorías disponibles
                        categorias_disponibles = sorted(set(p.get('categoria', 'general') for p in productos))
                        return f"No encontré productos para '{categoria}'. Las categorías disponibles son: {', '.join(categorias_disponibles)}"
            
            # Agrupar por categoría
            categorias = {}
            for p in productos_filtrados:
                cat = p.get('categoria', 'general')
                if cat not in categorias:
                    categorias[cat] = []
                categorias[cat].append(p)
            
            # Emojis por categoría
            emojis_por_categoria = {
                'tortas': '🎂',
                'pasteleria': '🎂',
                'pasabocas_dulces': '🧁',
                'pasabocas_salados': '🥐',
                'bebidas_calientes': '☕',
                'bebidas_frias': '🧋',
                'postres': '🍨',
                'decoraciones': '🎀',
                'general': '📦',
            }
            
            respuesta = "📋 *Productos disponibles:*\n\n"
            
            for cat, items in categorias.items():
                emoji = emojis_por_categoria.get(cat, '📦')
                nombre_cat = cat.replace('_', ' ').title()
                respuesta += f"{emoji} *{nombre_cat}*\n"
                
                # Limitar a 15 productos por categoría para no saturar
                for p in items[:15]:
                    if detalle == "completo" and p.get('descripcion'):
                        desc = p['descripcion'][:50]
                        respuesta += f"• *{p['nombre']}*: ${p['precio']:,} - {desc}...\n"
                    else:
                        respuesta += f"• {p['nombre']}: ${p['precio']:,}\n"
                
                if len(items) > 15:
                    respuesta += f"  ... y {len(items) - 15} productos más en {nombre_cat}\n"
                
                respuesta += "\n"
            
            total_productos = len(productos_filtrados)
            respuesta += f"📌 *Total:* {total_productos} productos"
            
            if categoria:
                respuesta += f" en {categoria}"
            
            respuesta += "\n\n💡 *Para ver más detalles de un producto específico, pregúntame por él.*"
            
            return respuesta
            
        except Exception as e:
            logger.error(f"Error en listar_productos: {e}")
            return "❌ Hubo un error al consultar los productos. Por favor intenta de nuevo."
    
    # ==================== MÉTODOS PARA ENVIAR MEDIOS ====================
    
    def _enviar_imagen(self, tenant: dict, numero: str, url_imagen: str, caption: str = None):
        try:
            if not url_imagen.startswith('http'):
                base_url = os.environ.get('BASE_URL', 'https://whatsapp-mvp-docker.onrender.com')
                url_completa = f"{base_url}{url_imagen}"
            else:
                url_completa = url_imagen
            logger.info(f"Enviando imagen a {numero}: {url_completa}")
            return whatsapp_client.send_image(tenant, numero, url_completa, caption)
        except Exception as e:
            logger.error(f'Error en _enviar_imagen: {e}')
            return False
    
    def _enviar_documento(self, tenant: dict, numero: str, url_documento: str, filename: str, caption: str = None):
        try:
            if not url_documento.startswith('http'):
                base_url = os.environ.get('BASE_URL', 'https://whatsapp-mvp-docker.onrender.com')
                url_completa = f"{base_url}{url_documento}"
            else:
                url_completa = url_documento
            logger.info(f"Enviando documento a {numero}: {filename}")
            return whatsapp_client.send_document(tenant, numero, url_completa, filename, caption)
        except Exception as e:
            logger.error(f'Error en _enviar_documento: {e}')
            return False
    
    def _enviar_video(self, tenant: dict, numero: str, url_video: str, caption: str = None):
        try:
            if not url_video.startswith('http'):
                base_url = os.environ.get('BASE_URL', 'https://whatsapp-mvp-docker.onrender.com')
                url_completa = f"{base_url}{url_video}"
            else:
                url_completa = url_video
            logger.info(f"Enviando video a {numero}: {url_completa}")
            return whatsapp_client.send_video(tenant, numero, url_completa, caption)
        except Exception as e:
            logger.error(f'Error en _enviar_video: {e}')
            return False
    
    def _enviar_audio(self, tenant: dict, numero: str, url_audio: str):
        try:
            if not url_audio.startswith('http'):
                base_url = os.environ.get('BASE_URL', 'https://whatsapp-mvp-docker.onrender.com')
                url_completa = f"{base_url}{url_audio}"
            else:
                url_completa = url_audio
            logger.info(f"Enviando audio a {numero}: {url_completa}")
            return whatsapp_client.send_audio(tenant, numero, url_completa)
        except Exception as e:
            logger.error(f'Error en _enviar_audio: {e}')
            return False
    
    def _enviar_recurso_visual(self, tenant: dict, numero: str, recurso_nombre: str) -> str:
        try:
            logger.info(f"🔍 Buscando recurso: '{recurso_nombre}' para tenant {tenant['id']}")
            recursos = schema_manager.get_recursos_visuales(tenant['id'])
            if not recursos:
                logger.warning(f"No hay recursos visuales para tenant {tenant['id']}")
                return None
            logger.info(f"📁 Recursos disponibles: {[r.get('nombre') for r in recursos]}")
            recurso_encontrado = None
            recurso_buscar = recurso_nombre.lower()
            for r in recursos:
                nombre_recurso = r.get('nombre', '').lower()
                if recurso_buscar == nombre_recurso:
                    recurso_encontrado = r
                    logger.info(f"✅ Recurso encontrado por coincidencia exacta: {r.get('nombre')}")
                    break
                elif recurso_buscar in nombre_recurso:
                    recurso_encontrado = r
                    logger.info(f"✅ Recurso encontrado por coincidencia parcial: {r.get('nombre')}")
                    break
                elif nombre_recurso in recurso_buscar:
                    recurso_encontrado = r
                    logger.info(f"✅ Recurso encontrado por coincidencia inversa: {r.get('nombre')}")
                    break
            if not recurso_encontrado:
                logger.warning(f"❌ Recurso NO encontrado: {recurso_nombre}")
                disponibles = [r.get('nombre') for r in recursos[:5]]
                if disponibles:
                    mensaje = f"No encontré '{recurso_nombre}'. Los recursos disponibles son: {', '.join(disponibles)}"
                    whatsapp_client.send_message(tenant, numero, mensaje)
                return None
            tipo = recurso_encontrado.get('tipo', '')
            url = recurso_encontrado.get('url', '')
            nombre = recurso_encontrado.get('nombre', '')
            descripcion = recurso_encontrado.get('descripcion', '')
            logger.info(f"📤 Enviando recurso: {nombre} (tipo: {tipo}, url: {url[:100]}...)")
            emojis = {'imagen': '📷', 'image': '📷', 'pdf': '📄', 'documento': '📄', 'video': '🎥'}
            emoji = emojis.get(tipo, '📎')
            caption = f"{emoji} *{nombre}*"
            if descripcion:
                caption += f"\n\n{descripcion}"
            if tipo in ['imagen', 'image'] and url:
                logger.info(f"🖼️ Enviando imagen a {numero}")
                resultado = self._enviar_imagen(tenant, numero, url, caption)
                if resultado:
                    logger.info(f"✅ Imagen enviada exitosamente")
                    return f"✅ Te envié {nombre}"
                else:
                    logger.error(f"❌ Falló el envío de la imagen")
                    return None
            elif tipo in ['pdf', 'documento', 'document'] and url:
                filename = url.split('/')[-1]
                if not filename.endswith('.pdf'):
                    filename = f"{nombre}.pdf"
                logger.info(f"📄 Enviando documento a {numero}: {filename}")
                resultado = self._enviar_documento(tenant, numero, url, filename, caption)
                if resultado:
                    logger.info(f"✅ Documento enviado exitosamente")
                    return f"✅ Te envié {nombre}"
                else:
                    logger.error(f"❌ Falló el envío del documento")
                    return None
            elif tipo in ['video'] and url:
                logger.info(f"🎥 Enviando video a {numero}")
                resultado = self._enviar_video(tenant, numero, url, caption)
                if resultado:
                    return f"✅ Te envié {nombre}"
                else:
                    return None
            else:
                logger.warning(f"⚠️ Tipo de recurso no soportado: {tipo}")
                return None
        except Exception as e:
            logger.error(f'❌ Error en _enviar_recurso_visual: {e}')
            import traceback
            traceback.print_exc()
            return None
    
    # ==================== PROMPT PERSONALIZABLE ====================
    
    def _obtener_system_prompt(self, tenant_id: str) -> str:
        """Obtiene el system prompt personalizado del tenant desde la base de datos"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT system_prompt FROM public.tenant_context WHERE tenant_id = %s
                    """, (tenant_id,))
                    row = cur.fetchone()
                    if row and row[0]:
                        logger.info(f"📝 Usando system prompt personalizado para tenant {tenant_id}")
                        return row[0]
        except Exception as e:
            logger.error(f"Error obteniendo system prompt personalizado: {e}")
        return None

    def _obtener_prompt_por_defecto(self, tenant: dict, menu_texto: str, recursos_texto: str,
                                     carrito_texto: str, historial_texto: str,
                                     contexto: dict, contexto_cliente: str,
                                     estado_pedido: str, tiempo_confirmado: str) -> str:
        """Genera el prompt por defecto (fallback) con instrucciones genéricas"""
        return f"""
Eres un asistente de ventas para {tenant.get('nombre', 'el negocio')}.

⚠️ REGLA OBLIGATORIA: Tienes que USAR LAS FUNCIONES para agregar productos al carrito. NO respondas con texto describiendo precios sin usar las funciones.

{contexto_cliente}

📜 HISTORIAL DE LA CONVERSACIÓN (USA ESTO PARA SABER EL CONTEXTO):
{historial_texto}

🛒 CARRITO ACTUAL:
{carrito_texto}

📋 PRODUCTOS DESTACADOS (referencia - usa SOLO para respuestas rápidas):
{menu_texto[:500]}...

📌 PARA VER TODOS LOS PRODUCTOS o buscar por categoría, usa la función 'listar_productos'

{recursos_texto}

📌 FUNCIONES DISPONIBLES:

1. agregar_producto_carrito(nombre_producto, precio, cantidad)
   - Ejemplo: "quiero torta red velvet media" → agregar_producto_carrito("Torta Red Velvet (Media)", 68700, 1)

2. agregar_producto_personalizado(nombre_base, precio, detalles, cantidad)
   - Usa cuando el cliente pida personalizaciones (cubierta, letrero, etc.)

3. listar_productos(categoria, detalle)
   - Úsala cuando el cliente pregunte: "qué venden", "qué productos tienen", "qué tortas", "qué pasabocas", "qué bebidas"
   - Si pregunta por una categoría específica: listar_productos(categoria="tortas")
   - detalle: "resumen" (solo nombres y precios) o "completo" (incluye descripción)

4. ver_carrito() - cuando el cliente diga "ver carrito" o "mi pedido"

5. confirmar_pedido() - cuando el cliente APRUEBE el pedido (diga "sí", "confirmo", "dale", "ok")

6. cancelar_pedido() - cuando el cliente QUIERA CANCELAR

7. enviar_recurso_visual(nombre_recurso) - para enviar imágenes o PDFs

📌 INSTRUCCIONES:

- SIEMPRE usa las funciones. NUNCA respondas con texto describiendo precios sin usar funciones.
- Usa el HISTORIAL para saber qué está pidiendo el cliente. No pierdas el contexto.
- Cuando el cliente diga "media", "libra", "cuarto" o "porción", es el TAMAÑO del producto.
- Para productos personalizados (torta + cubierta + base), haz UNA llamada por cada elemento.
- Responde en español, breve y amable.

EJEMPLO COMPLETO:
Cliente: "qué tortas tienen"
Tú: llamas a listar_productos(categoria="tortas")
Luego respondes: "Tenemos estas tortas disponibles: [lista de tortas]"

Cliente: "quiero torta red velvet media"
Tú: llamas a agregar_producto_carrito("Torta Red Velvet (Media)", 68700, 1)
Luego respondes: "✅ Agregué la Torta Red Velvet (Media) a tu carrito. ¿Algo más?"

RESPONDE en español.
"""

    def _reemplazar_variables_prompt(self, prompt: str, tenant: dict, menu_texto: str,
                                      recursos_texto: str, carrito_texto: str,
                                      historial_texto: str, contexto: dict,
                                      contexto_cliente: str, estado_pedido: str,
                                      tiempo_confirmado: str) -> str:
        """Reemplaza las variables del prompt personalizado con los valores reales"""
        variables = {
            '{nombre_negocio}': tenant.get('nombre', 'el negocio'),
            '{menu}': menu_texto,
            '{recursos}': recursos_texto,
            '{carrito}': carrito_texto,
            '{historial}': historial_texto,
            '{horario}': contexto.get('horario', 'No especificado'),
            '{ubicacion}': contexto.get('ubicacion', 'No especificada'),
            '{politicas}': contexto.get('politicas', 'No especificadas'),
            '{contexto_cliente}': contexto_cliente,
            '{estado_pedido}': estado_pedido,
            '{tiempo_confirmado}': tiempo_confirmado,
        }
        for var, valor in variables.items():
            prompt = prompt.replace(var, valor)
        return prompt

    # ==================== PROCESAMIENTO PRINCIPAL CON IA ====================
    
    def _procesar_con_ia(self, tenant: dict, menu: list, numero: str, texto: str, contexto: dict) -> str:
        logger.info(f"🤖 [IA] Procesando: {texto[:100]}...")
        
        if not ai_client.client:
            return self._respuesta_fallback(tenant, menu)
        
        # Guardar datos del cliente si los detecta
        self._guardar_datos_cliente(tenant['id'], numero, texto)
        
        # Obtener contexto del cliente
        contexto_cliente = self._obtener_contexto_cliente(tenant['id'], numero)
        
        # Obtener historial (EN ORDEN CRONOLÓGICO)
        historial = self._get_historial_conversacion(tenant['id'], numero, 15)
        carrito = self._cargar_carrito(tenant['id'], numero)
        recursos = schema_manager.get_recursos_visuales(tenant['id'])
        
        # Formatear historial para el prompt
        historial_texto = ""
        if historial:
            historial_texto = "\n"
            for h in historial:
                cliente_msg = h[0]
                asistente_msg = h[1]
                historial_texto += f"Cliente: {cliente_msg}\nAsistente: {asistente_msg}\n"
            logger.info(f"📜 Historial formateado con {len(historial)} mensajes")
        else:
            historial_texto = "\n(No hay historial previo)\n"
        
        # Formatear recursos para el prompt
        recursos_texto = ""
        if recursos:
            recursos_texto = "\n📁 RECURSOS VISUALES DISPONIBLES:\n"
            for r in recursos:
                recursos_texto += f"- Nombre: '{r['nombre']}' | Tipo: {r['tipo']} | Descripción: {r.get('descripcion', 'Sin descripción')}\n"
        else:
            recursos_texto = "\n📁 No hay recursos visuales disponibles.\n"
        
        # Formatear menú (SOLO destacados para contexto, no todo)
        menu_texto = ""
        if menu:
            # Solo los primeros 15 productos como referencia
            destacados = menu[:15]
            menu_texto = "\n".join([f"- {p['nombre']}: ${p['precio']:,}" for p in destacados])
            if len(menu) > 15:
                menu_texto += f"\n... y {len(menu) - 15} productos más. Usa 'listar_productos' para ver todos."
        
        # Formatear carrito
        carrito_texto = ""
        if carrito.get('items'):
            carrito_texto = "\n🛒 CARRITO ACTUAL:\n"
            for item in carrito['items']:
                carrito_texto += f"- {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}\n"
            carrito_texto += f"💰 Total: ${carrito.get('total', 0):,.0f}\n"
        else:
            carrito_texto = "\n🛒 Carrito vacío\n"
        
        # Estado del pedido confirmado
        estado_pedido = "SÍ" if self._pedido_confirmado.get(numero) else "NO"
        tiempo_confirmado = ""
        if self._pedido_confirmado.get(numero) and self._pedido_confirmado_time.get(numero):
            minutos = (datetime.now() - self._pedido_confirmado_time[numero]).total_seconds() / 60
            tiempo_confirmado = f" (confirmado hace {minutos:.0f} minutos)"
        
        # Tools
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "agregar_producto_carrito",
                    "description": "Agrega un producto estándar al carrito.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nombre_producto": {"type": "string"},
                            "precio": {"type": "integer"},
                            "cantidad": {"type": "integer", "default": 1}
                        },
                        "required": ["nombre_producto", "precio"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "agregar_producto_personalizado",
                    "description": "Agrega un producto personalizado al carrito.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nombre_base": {"type": "string"},
                            "precio": {"type": "integer"},
                            "detalles": {"type": "object"},
                            "cantidad": {"type": "integer", "default": 1}
                        },
                        "required": ["nombre_base", "precio"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "listar_productos",
                    "description": "Muestra la lista de productos disponibles con sus precios. Úsala cuando el cliente pregunte: qué venden, qué productos tienen, qué tortas, qué pasabocas, qué bebidas, etc.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "categoria": {
                                "type": "string",
                                "description": "Categoría a filtrar (ej: 'tortas', 'pasabocas_dulces', 'bebidas_calientes'). Si no se especifica, muestra todas las categorías."
                            },
                            "detalle": {
                                "type": "string",
                                "description": "Nivel de detalle: 'resumen' (solo nombres y precios), 'completo' (incluye descripción). Por defecto 'resumen'."
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "enviar_recurso_visual",
                    "description": "Envía un recurso visual (imagen, PDF, video) al cliente.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recurso_nombre": {
                                "type": "string",
                                "description": "El nombre exacto del recurso a enviar"
                            }
                        },
                        "required": ["recurso_nombre"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "ver_carrito",
                    "description": "Muestra el contenido actual del carrito.",
                    "parameters": {"type": "object", "properties": {}, "required": []}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "confirmar_pedido",
                    "description": "Confirma el pedido o inicia un nuevo pedido si ya hay uno confirmado.",
                    "parameters": {"type": "object", "properties": {}, "required": []}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cancelar_pedido",
                    "description": "Cancela el pedido actual y limpia completamente el carrito.",
                    "parameters": {"type": "object", "properties": {}, "required": []}
                }
            }
        ]
        
        # ========== Obtener prompt personalizado o usar el por defecto ==========
        system_prompt_custom = self._obtener_system_prompt(tenant['id'])
        
        if system_prompt_custom:
            # Reemplazar variables en el prompt personalizado
            system_prompt = self._reemplazar_variables_prompt(
                system_prompt_custom, tenant, menu_texto, recursos_texto,
                carrito_texto, historial_texto, contexto, contexto_cliente,
                estado_pedido, tiempo_confirmado
            )
            logger.info(f"✅ Usando system prompt personalizado para tenant {tenant['id']}")
        else:
            # Usar prompt por defecto
            system_prompt = self._obtener_prompt_por_defecto(
                tenant, menu_texto, recursos_texto, carrito_texto, historial_texto,
                contexto, contexto_cliente, estado_pedido, tiempo_confirmado
            )
            logger.info(f"📝 Usando system prompt por defecto para tenant {tenant['id']}")
        
        # Log para depuración del historial
        logger.info(f"📜 Historial enviado a IA: {len(historial)} mensajes")
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Cliente: {texto}"}
                ],
                temperature=0.7,
                max_tokens=500,
                tools=tools,
                tool_choice="auto"
            )
            
            message = response.choices[0].message
            
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    logger.info(f"🔧 [TOOL] {function_name}: {args}")
                    
                    if function_name == "agregar_producto_carrito":
                        self._agregar_producto_al_carrito(
                            tenant['id'], numero,
                            args.get("nombre_producto"),
                            args.get("precio"),
                            args.get("cantidad", 1)
                        )
                        carrito_act = self._cargar_carrito(tenant['id'], numero)
                        return f"""✅ *Agregado a tu pedido:*
• {args.get('cantidad', 1)}x {args.get('nombre_producto')}: ${args.get('precio') * args.get('cantidad', 1):,.0f}

💰 *Total actual:* ${carrito_act.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido?"""
                    
                    elif function_name == "agregar_producto_personalizado":
                        self._agregar_producto_personalizado_al_carrito(
                            tenant['id'], numero,
                            args.get("nombre_base"),
                            args.get("precio"),
                            args.get("detalles", {}),
                            args.get("cantidad", 1)
                        )
                        carrito_act = self._cargar_carrito(tenant['id'], numero)
                        return f"""✅ *Agregado a tu pedido:*
• {args.get('cantidad', 1)}x {args.get('nombre_base')}: ${args.get('precio') * args.get('cantidad', 1):,.0f}

💰 *Total actual:* ${carrito_act.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido?"""
                    
                    elif function_name == "listar_productos":
                        categoria = args.get("categoria")
                        detalle = args.get("detalle", "resumen")
                        resultado = self._listar_productos(tenant['id'], categoria, detalle)
                        return resultado
                    
                    elif function_name == "enviar_recurso_visual":
                        recurso_nombre = args.get("recurso_nombre")
                        resultado = self._enviar_recurso_visual(tenant, numero, recurso_nombre)
                        if resultado:
                            return resultado
                        else:
                            return f"Lo siento, no encontré el recurso '{recurso_nombre}'."
                    
                    elif function_name == "ver_carrito":
                        carrito_act = self._cargar_carrito(tenant['id'], numero)
                        if not carrito_act.get('items'):
                            return "🛒 Tu carrito está vacío. ¿Qué te gustaría ordenar?"
                        return self._mostrar_resumen_pedido(carrito_act['items'], carrito_act['total'])
                    
                    elif function_name == "confirmar_pedido":
                        # Si ya hay pedido confirmado, resetear para nuevo pedido
                        if self._pedido_confirmado.get(numero):
                            self._pedido_confirmado[numero] = False
                            self._pedido_confirmado_time[numero] = None
                            self._limpiar_carrito(tenant['id'], numero)
                            return "✅ Perfecto, empecemos un nuevo pedido. ¿Qué te gustaría ordenar?"
                        
                        carrito_final = self._cargar_carrito(tenant['id'], numero)
                        logger.info(f"📦 Confirmando pedido - Carrito tiene {len(carrito_final.get('items', []))} items, total: ${carrito_final.get('total', 0)}")
                        
                        if carrito_final and carrito_final.get('items'):
                            self._conversacion_activa[numero] = {
                                'estado': 'confirmando_pedido',
                                'productos': carrito_final['items'],
                                'total': carrito_final['total']
                            }
                            return self._mostrar_resumen_pedido(carrito_final['items'], carrito_final['total'])
                        else:
                            return "No hay productos en tu carrito para confirmar. Agrega algunos productos primero."
                    
                    elif function_name == "cancelar_pedido":
                        self._limpiar_carrito(tenant['id'], numero)
                        self._pedido_confirmado[numero] = False
                        self._conversacion_activa.pop(numero, None)
                        logger.info(f"🗑️ Pedido cancelado para {numero}")
                        return "✅ Pedido cancelado. Tu carrito está vacío. ¿Quieres empezar un nuevo pedido?"
            
            return message.content or self._respuesta_fallback(tenant, menu)
            
        except Exception as e:
            logger.error(f'Error en IA: {e}')
            return self._respuesta_fallback(tenant, menu)
    
    def _es_confirmacion(self, texto: str) -> bool:
        """Solo se usa para el flujo de confirmación manual (fallback) cuando no hay IA"""
        confirmaciones = ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'confirmar', 
                          'proceder', 'adelante', 'esta bien', 'está bien']
        return texto.lower().strip() in confirmaciones
    
    def _mostrar_resumen_pedido(self, productos: list, total: int) -> str:
        if not productos:
            return "No hay productos en tu pedido."
        items_texto = ""
        for i, p in enumerate(productos, 1):
            nombre = p.get('nombre', 'Producto')
            cantidad = p.get('cantidad', 1)
            precio_unitario = p.get('precio', 0)
            subtotal = precio_unitario * cantidad
            emoji = "🎂" if "torta" in nombre.lower() else "🍪" if "galleta" in nombre.lower() else "📦"
            items_texto += f"{emoji} *{cantidad}x {nombre}*: ${subtotal:,.0f}\n"
            if p.get('personalizado') and p.get('detalles'):
                for key, value in p['detalles'].items():
                    items_texto += f"   └─ {key}: {value}\n"
        return f"""📋 *Resumen de tu pedido:*

    {items_texto}
    💰 *Total:* ${total:,.0f}

    ¿Confirmas este pedido? (responde "sí" o "confirmo")"""
    
    def _procesar_confirmacion(self, texto: str, tenant: dict, numero: str, conv: dict) -> str:
        if self._es_confirmacion(texto):
            productos = conv.get('productos', [])
            total = conv.get('total', 0)
            
            pedido_id = str(uuid.uuid4())
            schema_name = self._get_schema_name(tenant['id'])
            
            with db_manager.get_connection(tenant['id']) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT COALESCE(MAX(secuencial), 0) + 1 FROM "{schema_name}".pedidos')
                    secuencial = cur.fetchone()[0] or 1
            
            numero_pedido = f"{tenant['nombre'][:3].upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:4].upper()}"
            
            try:
                with db_manager.get_connection(tenant['id']) as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"""
                            INSERT INTO "{schema_name}".pedidos 
                            (id, cliente_numero, numero_pedido, secuencial, items, total, estado, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        """, (pedido_id, numero, numero_pedido, secuencial, json.dumps(productos), total, 'nuevo'))
                    conn.commit()
                
                self._pedido_confirmado[numero] = True
                self._pedido_confirmado_time[numero] = datetime.now()
                self._limpiar_carrito(tenant['id'], numero)
                self._conversacion_activa.pop(numero, None)
                
                items_texto = ""
                for p in productos:
                    items_texto += f"• {p.get('cantidad', 1)}x {p.get('nombre')}: ${p.get('precio', 0) * p.get('cantidad', 1):,.0f}\n"
                
                return f"""✅ *¡PEDIDO CONFIRMADO!*

📌 *Número de pedido:* {numero_pedido}

📋 *Productos:*
{items_texto}
💰 *Total:* ${total:,.0f}

📌 *Gracias por tu compra. Te notificaremos cuando tu pedido esté listo.*

💡 *Para hacer un nuevo pedido, solo escribe:* "nuevo pedido" o "quiero comprar otra cosa"
"""
                
            except Exception as e:
                logger.error(f'Error creando pedido: {e}')
                return "❌ Hubo un error procesando tu pedido."
        else:
            return "¿Confirmas el pedido? Responde 'sí' para finalizar."
    
    def _respuesta_fallback(self, tenant: dict, menu: list) -> str:
        return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿En qué puedo ayudarte?"


message_handler = MessageHandler()