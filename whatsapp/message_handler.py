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
        self._estados_conversacion = {}  # {numero: estado}
        self._producto_temporal = {}     # {numero: producto_info}
        self._conversacion_personalizacion = {}  # {numero: {config_id, atributos_pendientes, respuestas}}
    
    def _get_schema_name(self, tenant_id: str) -> str:
        tenant = tenant_repo.find_by_id(tenant_id)
        if tenant and tenant.get('schema_name'):
            return tenant['schema_name']
        return f"tenant_{tenant_id.replace('-', '_')}"
    
    def _get_estado(self, numero: str) -> str:
        """Obtiene el estado actual de una conversación"""
        return self._estados_conversacion.get(numero)
    
    def _set_estado(self, numero: str, estado: str):
        """Establece el estado de una conversación"""
        if estado is None:
            self._estados_conversacion.pop(numero, None)
        else:
            self._estados_conversacion[numero] = estado
        logger.info(f'📌 [ESTADO] {numero} -> {estado}')
    
    def process(self, phone_id: str, numero: str, texto: str):
        logger.info(f'🟢 [PROCESS] Iniciando - Cliente: {numero}, Mensaje: {texto[:100]}')
        
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            logger.warning(f'⚠️ [PROCESS] Tenant no encontrado para phone_id: {phone_id}')
            return
        
        schema_manager.ensure_schema(tenant['id'])
        menu = self._obtener_menu(tenant['id'])
        contexto = self._obtener_contexto_tenant(tenant['id'])
        
        # Verificar estado actual de la conversación
        estado_actual = self._get_estado(numero)
        
        if estado_actual == 'esperando_respuesta_personalizacion':
            respuesta = self._procesar_respuesta_personalizacion(texto, tenant, numero)
        elif estado_actual == 'esperando_adicional':
            respuesta = self._procesar_adicional(texto, tenant, numero)
        elif estado_actual == 'esperando_personalizacion':
            respuesta = self._procesar_personalizacion(texto, tenant, numero)
        else:
            respuesta = self._procesar_con_ia(texto, tenant, menu, numero, contexto)
        
        if respuesta:
            whatsapp_client.send_message(tenant, numero, respuesta)
            self._guardar_conversacion(tenant['id'], numero, texto, respuesta)
            logger.info(f'🟢 [PROCESS] Respuesta enviada a {numero}')
        else:
            logger.warning(f'⚠️ [PROCESS] No se generó respuesta para {numero}')

    def _obtener_menu(self, tenant_id: str) -> list:
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible, 
                               imagen_url, tiempo_preparacion, destacado, metadata
                        FROM "{schema_name}".productos 
                        WHERE disponible = true
                        ORDER BY categoria, nombre
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
                        
                        productos.append({
                            'id': str(row[0]),
                            'nombre': row[1],
                            'descripcion': row[2] or '',
                            'precio': row[3],
                            'categoria': row[4] or 'general',
                            'disponible': row[5],
                            'imagen_url': row[6],
                            'tiempo_preparacion': row[7],
                            'destacado': row[8] if row[8] else False,
                            'personalizaciones': metadata.get('personalizaciones', []),
                            'adicionales': metadata.get('adicionales', [])
                        })
                    return productos
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
                logger.info(f'💬 [CONVERSACION] Guardada - Cliente: {cliente_numero}')
        except Exception as e:
            logger.error(f'Error guardando conversación: {e}')
    
    # ==================== PERSONALIZACIÓN CONFIGURABLE (NUEVA) ====================
    
    def _iniciar_personalizacion_por_config(self, tenant_id: str, numero: str, config_nombre: str) -> str:
        """Inicia el flujo de personalización usando una configuración existente"""
        try:
            config = schema_manager.get_configuracion_completa(tenant_id, config_nombre)
            if not config:
                return f"Lo siento, no tengo una configuración para personalizar {config_nombre}. ¿Te gustaría ver nuestro menú regular?"
            
            atributos = config.get('atributos', [])
            if not atributos:
                return f"La configuración '{config_nombre}' no tiene atributos definidos. Contacta al administrador."
            
            # Iniciar conversación de personalización
            self._conversacion_personalizacion[numero] = {
                'config_id': config['id'],
                'config_nombre': config['nombre'],
                'atributos_pendientes': atributos.copy(),
                'atributo_actual': None,
                'respuestas': {},
                'precio_base': 0
            }
            
            self._set_estado(numero, 'esperando_respuesta_personalizacion')
            
            # Hacer la primera pregunta
            return self._hacer_siguiente_pregunta_personalizacion(tenant_id, numero)
            
        except Exception as e:
            logger.error(f'Error iniciando personalización: {e}')
            return "❌ Error al iniciar la personalización. Por favor intenta de nuevo."
    
    def _hacer_siguiente_pregunta_personalizacion(self, tenant_id: str, numero: str) -> str:
        """Hace la siguiente pregunta de personalización usando IA para formularla"""
        conv = self._conversacion_personalizacion.get(numero)
        if not conv:
            self._set_estado(numero, None)
            return "❌ Error en la personalización. Por favor intenta de nuevo."
        
        atributos_pendientes = conv.get('atributos_pendientes', [])
        
        if not atributos_pendientes:
            # Todas las preguntas respondidas, calcular precio y finalizar
            return self._finalizar_personalizacion(tenant_id, numero)
        
        # Tomar el siguiente atributo
        atributo = atributos_pendientes[0]
        conv['atributo_actual'] = atributo
        
        # Usar IA para formular la pregunta de forma natural
        if ai_client.client:
            prompt = f"""
Eres un asistente de ventas. Debes hacer la siguiente pregunta al cliente.

ATRIBUTO A PREGUNTAR:
- Nombre: {atributo['nombre']}
- Tipo: {atributo['tipo']}
- Opciones: {json.dumps(atributo.get('opciones', []))}
- Pregunta base: {atributo['pregunta']}
- Requerido: {atributo['requerido']}

RESPUESTAS PREVIAS DEL CLIENTE:
{json.dumps(conv.get('respuestas', {}), indent=2, ensure_ascii=False)}

INSTRUCCIONES:
1. Formula la pregunta de forma natural, cálida y conversacional
2. Si tiene opciones, menciónalas amigablemente
3. Si tiene precio extra en las opciones, menciónalo
4. Sé breve y claro

RESPONDE SOLO CON LA PREGUNTA, nada más.
"""
            try:
                response = ai_client.client.chat.completions.create(
                    model=ai_client.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=300
                )
                pregunta = response.choices[0].message.content
                logger.info(f"🤖 [PREGUNTA IA] {pregunta}")
                return pregunta
            except Exception as e:
                logger.error(f'Error generando pregunta con IA: {e}')
        
        # Fallback: usar la pregunta guardada
        pregunta_base = atributo['pregunta']
        if atributo.get('tipo') == 'select' and atributo.get('opciones'):
            opciones = atributo.get('opciones', [])
            pregunta_base += "\n\nOpciones disponibles:\n"
            for i, opt in enumerate(opciones, 1):
                pregunta_base += f"{i}. {opt}\n"
        
        return pregunta_base
    
    def _procesar_respuesta_personalizacion(self, texto: str, tenant: dict, numero: str) -> str:
        """Procesa la respuesta del cliente durante la personalización usando IA"""
        conv = self._conversacion_personalizacion.get(numero)
        if not conv:
            self._set_estado(numero, None)
            return "❌ Error en la personalización. Por favor intenta de nuevo."
        
        atributo_actual = conv.get('atributo_actual')
        if not atributo_actual:
            return self._hacer_siguiente_pregunta_personalizacion(tenant['id'], numero)
        
        # Usar IA para interpretar la respuesta
        if ai_client.client:
            prompt = f"""
Interpreta la respuesta del cliente y extrae el valor para el atributo.

ATRIBUTO:
- Nombre: {atributo_actual['nombre']}
- Tipo: {atributo_actual['tipo']}
- Opciones: {json.dumps(atributo_actual.get('opciones', []))}
- Precios extra por opción: {json.dumps(atributo_actual.get('precio_extra', {}))}

RESPUESTA DEL CLIENTE: "{texto}"

INSTRUCCIONES:
1. Extrae el valor que el cliente quiere elegir
2. Si es tipo 'select', encuentra la opción más cercana
3. Si es tipo 'si_no', responde true/false
4. Si es tipo 'numero', extrae el número
5. Si es tipo 'texto', toma el texto
6. Calcula el precio extra según las opciones

Devuelve SOLO un JSON:
{{"valor": "valor_extraido", "precio_extra": 0}}
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
                
                valor = resultado.get('valor')
                precio_extra = resultado.get('precio_extra', 0)
                
                if valor:
                    # Guardar respuesta
                    respuestas = conv.get('respuestas', {})
                    respuestas[atributo_actual['nombre']] = {
                        'valor': valor,
                        'precio_extra': precio_extra
                    }
                    conv['respuestas'] = respuestas
                    conv['precio_base'] = conv.get('precio_base', 0) + precio_extra
                    
                    # Mover a siguiente atributo
                    atributos_pendientes = conv.get('atributos_pendientes', [])
                    if atributos_pendientes:
                        conv['atributos_pendientes'] = atributos_pendientes[1:]
                    
                    self._conversacion_personalizacion[numero] = conv
                    
                    return self._hacer_siguiente_pregunta_personalizacion(tenant['id'], numero)
                    
            except Exception as e:
                logger.error(f'Error interpretando respuesta: {e}')
        
        # Fallback: si la IA falla, pedir que repita
        return f"No entendí bien. {atributo_actual['pregunta']} Por favor, responde claramente."
    
    def _finalizar_personalizacion(self, tenant_id: str, numero: str) -> str:
        """Finaliza la personalización, calcula precio y agrega al carrito"""
        conv = self._conversacion_personalizacion.pop(numero, None)
        if not conv:
            return "❌ Error al finalizar la personalización."
        
        respuestas = conv.get('respuestas', {})
        precio_total = conv.get('precio_base', 0)
        config_nombre = conv.get('config_nombre', 'Producto')
        
        # Construir nombre del producto
        nombre_producto = f"🎨 {config_nombre.capitalize()} Personalizada"
        
        # Crear item para el carrito
        item = {
            'id': str(uuid.uuid4()),
            'nombre': nombre_producto,
            'precio': precio_total,
            'cantidad': 1,
            'personalizacion': respuestas,
            'tipo': 'personalizado'
        }
        
        # Agregar al carrito
        carrito = self._cargar_carrito(tenant_id, numero)
        carrito['items'].append(item)
        carrito['total'] += precio_total
        self._guardar_carrito(tenant_id, numero, carrito['items'], carrito['total'])
        
        self._set_estado(numero, None)
        
        # Generar resumen con IA
        if ai_client.client:
            prompt = f"""
Genera un resumen amigable del producto personalizado que el cliente acaba de crear.

PRODUCTO: {config_nombre}
PRECIO TOTAL: ${precio_total:,.0f}

RESPUESTAS DEL CLIENTE:
{json.dumps(respuestas, indent=2, ensure_ascii=False)}

INSTRUCCIONES:
1. Crea un resumen cálido y claro
2. Lista todas las opciones que eligió el cliente
3. Muestra el precio total
4. Pregunta si quiere agregar algo más o confirmar el pedido

Responde en español, como un asistente amable.
"""
            try:
                response = ai_client.client.chat.completions.create(
                    model=ai_client.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=500
                )
                resumen = response.choices[0].message.content
                return resumen
            except Exception as e:
                logger.error(f'Error generando resumen: {e}')
        
        # Fallback
        resumen = f"✅ *¡Listo! Tu {config_nombre} personalizada está creada.*\n\n"
        resumen += "📝 *Detalles de tu personalización:*\n"
        for key, value in respuestas.items():
            valor = value.get('valor') if isinstance(value, dict) else value
            precio_extra = value.get('precio_extra', 0) if isinstance(value, dict) else 0
            if precio_extra > 0:
                resumen += f"  • {key}: {valor} (+${precio_extra:,})\n"
            else:
                resumen += f"  • {key}: {valor}\n"
        
        resumen += f"\n💰 *Precio total:* ${precio_total:,.0f}\n\n"
        resumen += "¿Algo más que quieras agregar? O responde *confirmo* para finalizar el pedido."
        
        return resumen
    
    # ==================== MANEJO DE ADICIONALES Y PERSONALIZACIONES (LEGACY) ====================
    
    def _procesar_seleccion_producto(self, tenant_id: str, numero: str, producto_id: str):
        """Maneja la selección de un producto y pregunta por sus adicionales"""
        try:
            producto = self._obtener_producto_por_id(tenant_id, producto_id)
            if not producto:
                return "❌ Producto no encontrado"
            
            # Guardar producto temporalmente
            self._producto_temporal[numero] = {
                'id': producto_id,
                'nombre': producto['nombre'],
                'precio_base': producto['precio'],
                'adicionales': producto.get('adicionales', []),
                'personalizaciones': producto.get('personalizaciones', []),
                'adicionales_seleccionados': [],
                'personalizaciones_seleccionadas': {}
            }
            
            adicionales = producto.get('adicionales', [])
            
            if adicionales and len(adicionales) > 0:
                # Preguntar por los adicionales
                mensaje = f"✅ *{producto['nombre']}* - ${producto['precio']:,}\n\n"
                mensaje += "🎨 *Opciones disponibles:*\n\n"
                
                for i, adic in enumerate(adicionales, 1):
                    precio_extra = adic.get('precio_extra', 0)
                    multiple = adic.get('multiple', False)
                    multi_texto = " (puedes elegir varios)" if multiple else ""
                    
                    if precio_extra > 0:
                        mensaje += f"• {adic['nombre']} *(+${precio_extra:,})*{multi_texto}\n"
                    else:
                        mensaje += f"• {adic['nombre']} *(sin costo extra)*{multi_texto}\n"
                
                mensaje += "\n📝 *Responde con:*\n"
                mensaje += "• El *número* de la opción (ej: '5')\n"
                mensaje += "• El *nombre* de lo que quieres (ej: 'torta negra')\n"
                mensaje += "• *Ninguno* si no quieres adicionales\n"
                mensaje += "• *Siguiente* para continuar"
                
                self._set_estado(numero, 'esperando_adicional')
                return mensaje
            else:
                # No tiene adicionales, continuar con personalizaciones
                return self._procesar_personalizaciones_producto(tenant_id, numero)
                
        except Exception as e:
            logger.error(f'Error en selección de producto: {e}')
            return "❌ Error al procesar el producto"
    
    def _procesar_adicional(self, texto: str, tenant: dict, numero: str) -> str:
        """Procesa la selección de adicionales usando IA para interpretar lenguaje natural"""
        try:
            producto_temp = self._producto_temporal.get(numero)
            if not producto_temp:
                self._set_estado(numero, None)
                return "❌ Por favor, selecciona un producto primero"
            
            adicionales = producto_temp.get('adicionales', [])
            respuesta = texto.lower().strip()
            
            # Verificar si quiere continuar sin más adicionales
            if respuesta in ['ninguno', 'ninguna', 'no', '0', 'siguiente', 'continuar', 'saltar']:
                # Pasar a personalizaciones
                return self._procesar_personalizaciones_producto(tenant['id'], numero)
            
            # ========== USAR IA PARA INTERPRETAR LA RESPUESTA ==========
            if ai_client.client and adicionales:
                # Construir prompt para la IA
                opciones_texto = ""
                for i, adic in enumerate(adicionales, 1):
                    precio_extra = adic.get('precio_extra', 0)
                    opciones_texto += f"{i}. {adic['nombre']} (+${precio_extra:,})\n"
                
                prompt = f"""
    Interpreta la respuesta del cliente y determina qué opción de adicional quiere elegir.

    OPCIONES DISPONIBLES:
    {opciones_texto}

    RESPUESTA DEL CLIENTE: "{texto}"

    INSTRUCCIONES:
    1. Analiza qué opción está pidiendo el cliente basado en su mensaje
    2. Si dice "torta negra", debe elegir la opción que contiene "Torta Negra"
    3. Si dice "vainilla", debe elegir la opción con vainilla
    4. Si dice "chocolate", debe elegir la opción con chocolate
    5. Si dice "ninguno" o "no quiero", responde con "ninguno"
    6. Si no está seguro, responde con "no_seguro"

    Devuelve SOLO un JSON:
    {{"opcion": "numero_del_1_al_N", "nombre": "nombre_de_la_opcion", "confianza": "alta|media|baja"}}
    Si no quiere ninguno: {{"opcion": "ninguno"}}
    Si no está seguro: {{"opcion": "no_seguro"}}
    """
                try:
                    response = ai_client.client.chat.completions.create(
                        model=ai_client.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=200
                    )
                    contenido = response.choices[0].message.content
                    contenido = contenido.replace('```json', '').replace('```', '').strip()
                    resultado = json.loads(contenido)
                    
                    opcion = resultado.get('opcion')
                    
                    if opcion == 'ninguno':
                        return self._procesar_personalizaciones_producto(tenant['id'], numero)
                    
                    if opcion != 'no_seguro' and opcion:
                        try:
                            opcion_idx = int(opcion) - 1
                            if 0 <= opcion_idx < len(adicionales):
                                adic = adicionales[opcion_idx]
                                producto_temp['adicionales_seleccionados'].append(adic)
                                logger.info(f"🤖 [IA] Mapeó '{texto}' a opción {opcion}: {adic['nombre']}")
                                
                                if adic.get('multiple', False):
                                    return self._preguntar_si_mas_adicionales(tenant['id'], numero, producto_temp)
                                else:
                                    return self._procesar_personalizaciones_producto(tenant['id'], numero)
                        except ValueError:
                            pass
                            
                except Exception as e:
                    logger.error(f'Error en IA para interpretar adicional: {e}')
            
            # ========== FALLBACK: intentar mapeo por palabras clave ==========
            # Mapear respuestas de texto a opciones
            for i, adic in enumerate(adicionales, 1):
                nombre_adicional = adic['nombre'].lower()
                # Buscar coincidencias de palabras clave
                palabras_clave = nombre_adicional.replace('sabor a ', '').replace('o ', '').split()
                for palabra in palabras_clave:
                    if len(palabra) > 3 and palabra in respuesta:
                        producto_temp['adicionales_seleccionados'].append(adic)
                        logger.info(f"🔑 [KEYWORD] Mapeó '{texto}' a opción {i}: {adic['nombre']}")
                        
                        if adic.get('multiple', False):
                            return self._preguntar_si_mas_adicionales(tenant['id'], numero, producto_temp)
                        else:
                            return self._procesar_personalizaciones_producto(tenant['id'], numero)
            
            # ========== ÚLTIMO RECURSO: intentar parsear número ==========
            # Verificar si es un número
            if respuesta.isdigit():
                opcion_idx = int(respuesta) - 1
                if 0 <= opcion_idx < len(adicionales):
                    adic = adicionales[opcion_idx]
                    producto_temp['adicionales_seleccionados'].append(adic)
                    
                    if adic.get('multiple', False):
                        return self._preguntar_si_mas_adicionales(tenant['id'], numero, producto_temp)
                    else:
                        return self._procesar_personalizaciones_producto(tenant['id'], numero)
            
            # Si no se pudo interpretar, mostrar mensaje de ayuda
            return self._opcion_invalida_adicional(adicionales)
            
        except Exception as e:
            logger.error(f'Error procesando adicional: {e}')
            self._set_estado(numero, None)
            return "❌ Error al procesar tu selección. Por favor intenta de nuevo."
        
    
    def _preguntar_si_mas_adicionales(self, tenant_id: str, numero: str, producto_temp: dict) -> str:
        """Pregunta si quiere agregar más adicionales"""
        adicionales = producto_temp.get('adicionales', [])
        seleccionados = producto_temp.get('adicionales_seleccionados', [])
        
        if seleccionados:
            mensaje = "📋 *Adicionales seleccionados hasta ahora:*\n"
            for s in seleccionados:
                precio = s.get('precio_extra', 0)
                mensaje += f"  • {s['nombre']}" + (f" (+${precio:,})" if precio > 0 else "") + "\n"
            mensaje += "\n"
        
        mensaje += "¿Deseas agregar *más adicionales*?\n\n"
        
        for i, adic in enumerate(adicionales, 1):
            precio_extra = adic.get('precio_extra', 0)
            ya_seleccionado = any(s.get('nombre') == adic['nombre'] for s in seleccionados)
            if ya_seleccionado:
                mensaje += f"{i}. {adic['nombre']} *[YA SELECCIONADO]*\n"
            else:
                if precio_extra > 0:
                    mensaje += f"{i}. {adic['nombre']} *(+${precio_extra:,})*\n"
                else:
                    mensaje += f"{i}. {adic['nombre']} *(sin costo extra)*\n"
        
        mensaje += "\n📝 *Responde con el número* del adicional que quieres agregar\n"
        mensaje += "Responde *ninguno* si no quieres más\n"
        mensaje += "Responde *siguiente* para continuar"
        
        return mensaje
    
    def _opcion_invalida_adicional(self, adicionales: list) -> str:
        """Mensaje de opción inválida para adicionales"""
        mensaje = "❌ *No entendí tu selección*\n\n"
        mensaje += "Puedes responder de varias formas:\n"
        mensaje += "• Con el *número* de la opción (ej: '5')\n"
        mensaje += "• Con el *nombre* del sabor (ej: 'torta negra')\n"
        mensaje += "• Con *ninguno* si no quieres adicionales\n\n"
        mensaje += "📋 *Opciones disponibles:*\n"
        
        for i, adic in enumerate(adicionales, 1):
            precio_extra = adic.get('precio_extra', 0)
            nombre = adic['nombre']
            if precio_extra > 0:
                mensaje += f"{i}. {nombre} (+${precio_extra:,})\n"
            else:
                mensaje += f"{i}. {nombre} (sin costo extra)\n"
        
        mensaje += "\n¿Cuál prefieres? (escribe el número o el nombre)"
        return mensaje
    
    def _procesar_personalizaciones_producto(self, tenant_id: str, numero: str) -> str:
        """Procesa las personalizaciones del producto"""
        producto_temp = self._producto_temporal.get(numero)
        if not producto_temp:
            self._set_estado(numero, None)
            return "❌ Por favor, selecciona un producto primero"
        
        personalizaciones = producto_temp.get('personalizaciones', [])
        
        if personalizaciones and len(personalizaciones) > 0:
            pendientes = []
            for p in personalizaciones:
                nombre = p.get('nombre')
                if nombre not in producto_temp.get('personalizaciones_seleccionadas', {}):
                    pendientes.append(p)
            
            if pendientes:
                siguiente = pendientes[0]
                mensaje = f"📝 *Personalización: {siguiente['nombre']}*\n\n"
                
                if siguiente.get('tipo') == 'select' and siguiente.get('opciones'):
                    opciones = siguiente.get('opciones', [])
                    mensaje += "Opciones disponibles:\n"
                    for i, opt in enumerate(opciones, 1):
                        mensaje += f"{i}. {opt}\n"
                    mensaje += f"\n📝 Responde con el número de tu elección"
                else:
                    mensaje += "Por favor, escribe tu respuesta:"
                    if siguiente.get('requerido'):
                        mensaje += " *(requerido)*"
                
                self._set_estado(numero, 'esperando_personalizacion')
                return mensaje
        
        return self._agregar_al_carrito_desde_temporal(tenant_id, numero)
    
    def _procesar_personalizacion(self, texto: str, tenant: dict, numero: str) -> str:
        """Procesa una respuesta de personalización"""
        try:
            producto_temp = self._producto_temporal.get(numero)
            if not producto_temp:
                self._set_estado(numero, None)
                return "❌ Por favor, selecciona un producto primero"
            
            personalizaciones = producto_temp.get('personalizaciones', [])
            seleccionadas = producto_temp.get('personalizaciones_seleccionadas', {})
            
            pendiente = None
            for p in personalizaciones:
                if p.get('nombre') not in seleccionadas:
                    pendiente = p
                    break
            
            if not pendiente:
                return self._agregar_al_carrito_desde_temporal(tenant['id'], numero)
            
            if pendiente.get('tipo') == 'select' and pendiente.get('opciones'):
                try:
                    opcion_idx = int(texto) - 1
                    opciones = pendiente.get('opciones', [])
                    if 0 <= opcion_idx < len(opciones):
                        seleccionadas[pendiente['nombre']] = opciones[opcion_idx]
                    else:
                        return f"❌ Opción inválida. Elige un número del 1 al {len(opciones)}"
                except ValueError:
                    return f"❌ Por favor, responde con el número de la opción (1-{len(pendiente.get('opciones', []))})"
            else:
                if not texto.strip() and pendiente.get('requerido'):
                    return f"❌ '{pendiente['nombre']}' es requerido. Por favor responde:"
                seleccionadas[pendiente['nombre']] = texto.strip()
            
            producto_temp['personalizaciones_seleccionadas'] = seleccionadas
            self._producto_temporal[numero] = producto_temp
            
            return self._procesar_personalizaciones_producto(tenant['id'], numero)
            
        except Exception as e:
            logger.error(f'Error procesando personalización: {e}')
            self._set_estado(numero, None)
            return "❌ Error al procesar tu respuesta"
    
    def _agregar_al_carrito_desde_temporal(self, tenant_id: str, numero: str) -> str:
        """Agrega el producto temporal al carrito con todos sus adicionales y personalizaciones"""
        try:
            producto_temp = self._producto_temporal.pop(numero, None)
            if not producto_temp:
                return "❌ Error: No hay producto para agregar"
            
            precio_final = producto_temp['precio_base']
            for adic in producto_temp.get('adicionales_seleccionados', []):
                precio_final += adic.get('precio_extra', 0)
            
            nombre_producto = producto_temp['nombre']
            
            if producto_temp.get('adicionales_seleccionados'):
                nombres_adicionales = [a['nombre'] for a in producto_temp['adicionales_seleccionados']]
                nombre_producto += f" (+{', '.join(nombres_adicionales)})"
            
            item = {
                'id': producto_temp['id'],
                'nombre': nombre_producto,
                'nombre_base': producto_temp['nombre'],
                'precio': precio_final,
                'precio_base': producto_temp['precio_base'],
                'cantidad': 1,
                'adicionales': producto_temp.get('adicionales_seleccionados', []),
                'personalizaciones': producto_temp.get('personalizaciones_seleccionadas', {})
            }
            
            carrito = self._cargar_carrito(tenant_id, numero)
            carrito['items'].append(item)
            carrito['total'] += precio_final
            self._guardar_carrito(tenant_id, numero, carrito['items'], carrito['total'])
            
            self._set_estado(numero, None)
            
            mensaje = f"✅ *Agregado a tu pedido:*\n"
            mensaje += f"• {nombre_producto}: ${precio_final:,}\n"
            
            if producto_temp.get('personalizaciones_seleccionadas'):
                mensaje += "\n📝 *Personalizaciones:*\n"
                for key, value in producto_temp['personalizaciones_seleccionadas'].items():
                    mensaje += f"  • {key}: {value}\n"
            
            mensaje += f"\n💰 *Total actual:* ${carrito['total']:,}\n\n"
            mensaje += "¿Algo más? (responde 'ver' para ver tu pedido o 'confirmo' para finalizar)"
            
            return mensaje
            
        except Exception as e:
            logger.error(f'Error agregando al carrito desde temporal: {e}')
            self._set_estado(numero, None)
            return "❌ Error al agregar el producto al carrito"
    
    def _obtener_producto_por_id(self, tenant_id: str, producto_id: str) -> dict:
        """Obtiene un producto por su ID con todos sus detalles"""
        try:
            schema_name = self._get_schema_name(tenant_id)
            with db_manager.get_connection(tenant_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT id, nombre, descripcion, precio, categoria, disponible, 
                               imagen_url, tiempo_preparacion, destacado, metadata
                        FROM "{schema_name}".productos WHERE id = %s
                    """, (producto_id,))
                    row = cur.fetchone()
                    if row:
                        metadata = row[9] if len(row) > 9 and row[9] else {}
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except:
                                metadata = {}
                        
                        return {
                            'id': str(row[0]),
                            'nombre': row[1],
                            'descripcion': row[2] or '',
                            'precio': row[3],
                            'categoria': row[4] or 'general',
                            'disponible': row[5],
                            'imagen_url': row[6],
                            'tiempo_preparacion': row[7],
                            'destacado': row[8] if row[8] else False,
                            'personalizaciones': metadata.get('personalizaciones', []),
                            'adicionales': metadata.get('adicionales', [])
                        }
                    return None
        except Exception as e:
            logger.error(f'Error obteniendo producto: {e}')
            return None
    
    # ==================== MÉTODOS DEL CARRITO ====================

    def _guardar_carrito(self, tenant_id: str, cliente_numero: str, items: list, total: int):
        logger.info(f'💾 [CARRITO] Guardando - Cliente: {cliente_numero}, Items: {len(items)}, Total: ${total:,.0f}')
        
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
                        total = row[1] or 0
                        return {'items': items, 'total': total}
                    return {'items': [], 'total': 0}
        except Exception as e:
            logger.error(f'Error cargando carrito: {e}')
            return {'items': [], 'total': 0}
        
    def _agregar_al_carrito(self, tenant_id: str, cliente_numero: str, productos: list):
        """Agrega productos directamente al carrito (sin preguntar adicionales)"""
        carrito = self._cargar_carrito(tenant_id, cliente_numero)
        
        for p in productos:
            encontrado = False
            for item in carrito['items']:
                if item.get('nombre') == p.get('nombre'):
                    item['cantidad'] = item.get('cantidad', 1) + p.get('cantidad', 1)
                    carrito['total'] += p.get('precio', 0) * p.get('cantidad', 1)
                    encontrado = True
                    break
            if not encontrado:
                carrito['items'].append({
                    'id': p.get('id'),
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
    
    def _mostrar_resumen_carrito(self, tenant: dict, numero: str, carrito: dict) -> str:
        if not carrito.get('items'):
            return "No tienes productos en tu carrito. ¿Qué te gustaría ordenar?"
        
        items_texto = ""
        for item in carrito['items']:
            items_texto += f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}\n"
            if item.get('personalizacion'):
                for key, value in item['personalizacion'].items():
                    valor = value.get('valor') if isinstance(value, dict) else value
                    items_texto += f"     └─ {key}: {valor}\n"
            elif item.get('personalizaciones'):
                for key, value in item['personalizaciones'].items():
                    items_texto += f"     └─ {key}: {value}\n"
        
        return f"""📋 **Tu pedido actual:**
{items_texto}
**Total:** ${carrito.get('total', 0):,.0f}

¿Algo más o confirmamos el pedido? (responde "confirmo")"""
    
    def _finalizar_pedido(self, tenant: dict, numero: str, carrito: dict) -> str:
        """Finaliza el pedido y genera número de seguimiento"""
        logger.info(f"🎯 [FINALIZAR] Iniciando finalización para cliente {numero}")
        
        if not carrito or not carrito.get('items'):
            return "No hay productos en tu carrito. ¿Qué te gustaría ordenar?"
        
        datos_cliente = self._datos_cliente.get(numero, {})
        schema_name = self._get_schema_name(tenant['id'])
        
        cliente_existente = self._obtener_cliente(tenant['id'], numero)
        
        datos_completos = {}
        if cliente_existente:
            datos_completos.update(cliente_existente)
        datos_completos.update(datos_cliente)
        
        contexto = self._obtener_contexto_tenant(tenant['id'])
        direccion_entrega = datos_completos.get('direccion', '')
        if datos_completos.get('recojo_en_tienda'):
            direccion_entrega = f"Recojo en tienda - {tenant.get('nombre')} - {contexto.get('ubicacion', '')}"
        
        cliente_id = self._obtener_o_crear_cliente(tenant['id'], numero, datos_completos)
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
                    cur.execute(f'INSERT INTO "{schema_name}".pedidos (id, cliente_id, cliente_numero, cliente_nombre, numero_pedido, secuencial, items, total, estado, direccion_entrega, notas) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)', (pedido_id, cliente_id, numero, datos_completos.get('nombre', numero), numero_pedido, secuencial, json.dumps(items), total, 'nuevo', direccion_entrega, f"Fecha: {datos_completos.get('fecha_entrega', '')} Hora: {datos_completos.get('hora_entrega', '')}".strip()))
                conn.commit()
            
            self._guardar_carrito(tenant['id'], numero, [], 0)
            if numero in self._datos_cliente:
                del self._datos_cliente[numero]
            
            items_texto = ""
            for item in items:
                items_texto += f"• {item.get('cantidad', 1)}x {item.get('nombre')}: ${item.get('precio', 0) * item.get('cantidad', 1):,.0f}\n"
                if item.get('personalizacion'):
                    for key, value in item['personalizacion'].items():
                        valor = value.get('valor') if isinstance(value, dict) else value
                        items_texto += f"     └─ {key}: {valor}\n"
                elif item.get('personalizaciones'):
                    for key, value in item['personalizaciones'].items():
                        items_texto += f"     └─ {key}: {value}\n"
            
            datos_texto = self._formatear_datos_cliente(datos_completos)
            
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
                    cur.execute(f'SELECT id FROM "{schema_name}".clientes WHERE numero_telefono = %s', (numero,))
                    row = cur.fetchone()
                    
                    if row:
                        cliente_id = row[0]
                        if datos_cliente:
                            updates = []
                            params = []
                            if datos_cliente.get('nombre'):
                                updates.append("nombre = %s")
                                params.append(datos_cliente['nombre'])
                            if datos_cliente.get('cc'):
                                updates.append("cc = %s")
                                params.append(datos_cliente['cc'])
                            if datos_cliente.get('email'):
                                updates.append("email = %s")
                                params.append(datos_cliente['email'])
                            if datos_cliente.get('direccion'):
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
                            INSERT INTO "{schema_name}".clientes (id, numero_telefono, nombre, cc, email, direccion, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                        """, (cliente_id, numero, 
                            datos_cliente.get('nombre') if datos_cliente else None,
                            datos_cliente.get('cc') if datos_cliente else None,
                            datos_cliente.get('email') if datos_cliente else None,
                            datos_cliente.get('direccion') if datos_cliente else None))
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
    
    # ==================== DETECCIÓN DE PRODUCTOS CON IA ====================
    
    def _extraer_productos_con_ia(self, texto: str, menu: list) -> list:
        """Usa IA para extraer productos del mensaje del cliente"""
        if not ai_client.client or not menu:
            return []
        
        prompt = f"""
        Extrae los productos que el cliente quiere comprar del siguiente mensaje.
        
        MENSAJE: "{texto}"
        
        CATÁLOGO DE PRODUCTOS:
        {json.dumps([{'nombre': p['nombre'], 'precio': p['precio']} for p in menu], indent=2, ensure_ascii=False)}
        
        IMPORTANTE:
        - El cliente puede escribir en lenguaje natural
        - Relaciona lo que pide con el nombre más cercano del catálogo
        - Extrae la cantidad (si no se especifica, es 1)
        
        Devuelve SOLO un JSON válido:
        {{"productos": [{{"id": "id_del_producto", "nombre": "nombre exacto del catálogo", "cantidad": 1}}]}}
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=500
            )
            contenido = response.choices[0].message.content
            contenido = contenido.replace('```json', '').replace('```', '').strip()
            resultado = json.loads(contenido)
            
            productos = []
            for p in resultado.get('productos', []):
                nombre = p.get('nombre', '')
                cantidad = p.get('cantidad', 1)
                for producto in menu:
                    if producto['nombre'].lower() == nombre.lower():
                        productos.append({
                            'id': producto['id'],
                            'nombre': producto['nombre'],
                            'precio': producto.get('precio', 0),
                            'cantidad': cantidad
                        })
                        break
            if productos:
                logger.info(f"🤖 [IA] Productos detectados: {productos}")
            return productos
        except Exception as e:
            logger.error(f"Error IA extrayendo productos: {e}")
            return []

    def _extraer_productos_del_historial_con_ia(self, historial: list, menu: list) -> list:
        """Usa IA para extraer productos de toda la conversación"""
        if not ai_client.client or not menu or not historial:
            return []
        
        texto_historial = "\n".join([f"Cliente: {h[0]}" for h in historial[-15:]])
        
        prompt = f"""
        Analiza la siguiente conversación y extrae los productos que el cliente quiere comprar.
        
        CONVERSACIÓN:
        {texto_historial}
        
        CATÁLOGO DE PRODUCTOS:
        {json.dumps([{'id': p['id'], 'nombre': p['nombre'], 'precio': p['precio']} for p in menu], indent=2, ensure_ascii=False)}
        
        IMPORTANTE:
        - El cliente acaba de confirmar el pedido (dijo "confirmo" o "si")
        - Busca en la conversación qué productos pidió anteriormente
        - Relaciona con el nombre más cercano del catálogo
        - Extrae la cantidad
        
        Devuelve SOLO un JSON:
        {{"productos": [{{"id": "id_del_producto", "nombre": "nombre exacto del catálogo", "cantidad": 1}}]}}
        """
        
        try:
            response = ai_client.client.chat.completions.create(
                model=ai_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=500
            )
            contenido = response.choices[0].message.content
            contenido = contenido.replace('```json', '').replace('```', '').strip()
            resultado = json.loads(contenido)
            
            productos = []
            for p in resultado.get('productos', []):
                nombre = p.get('nombre', '')
                cantidad = p.get('cantidad', 1)
                producto_id = p.get('id')
                
                producto_encontrado = None
                if producto_id:
                    for producto in menu:
                        if producto['id'] == producto_id:
                            producto_encontrado = producto
                            break
                
                if not producto_encontrado:
                    for producto in menu:
                        if producto['nombre'].lower() == nombre.lower():
                            producto_encontrado = producto
                            break
                
                if producto_encontrado:
                    productos.append({
                        'id': producto_encontrado['id'],
                        'nombre': producto_encontrado['nombre'],
                        'precio': producto_encontrado.get('precio', 0),
                        'cantidad': cantidad
                    })
            
            if productos:
                logger.info(f"🤖 [IA] Productos encontrados en historial: {productos}")
            return productos
        except Exception as e:
            logger.error(f"Error IA extrayendo productos del historial: {e}")
            return []
    
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
                logger.info(f"📝 [DATOS] Extraídos: {datos}")
        except Exception as e:
            logger.error(f'Error extrayendo datos: {e}')
    
    def _cliente_confirmo(self, texto: str) -> bool:
        confirmaciones = ['si', 'sí', 'dale', 'ok', 'correcto', 'confirmo', 'confirmar', 'proceder', 'adelante', 'esta bien', 'está bien', 'confirmo pedido']
        palabras_pago = ['pague', 'pago', 'pagado', 'transferí', 'consigné', 'pagué', 'ya pague', 'listo el pago']
        texto_lower = texto.lower().strip()
        es_confirmacion = texto_lower in confirmaciones or any(c in texto_lower for c in confirmaciones if len(c) > 2) or any(p in texto_lower for p in palabras_pago)
        if es_confirmacion:
            logger.info(f"✅ [CONFIRMACION] Detectada: {texto}")
        return es_confirmacion
    
    def _procesar_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, contexto: dict) -> str:
        """Procesa el mensaje usando IA para lenguaje natural"""
        
        logger.info(f"🤖 [IA] Procesando mensaje: {texto[:100]}...")
        
        if not ai_client.client:
            logger.warning("⚠️ [IA] Cliente no disponible, usando fallback")
            return self._respuesta_fallback(tenant, menu)
        
        carrito_actual = self._cargar_carrito(tenant['id'], numero)
        resumen_cliente = self._get_resumen_cliente(tenant['id'], numero)
        historial = self._get_historial_conversacion(tenant['id'], numero, 15)
        historial_texto = self._formatear_historial_para_prompt(historial)
        
        self._extraer_y_guardar_datos(texto, numero)
        if numero in self._datos_cliente and self._datos_cliente[numero].get('nombre'):
            self._guardar_datos_cliente_en_bd(tenant['id'], numero)
        
        texto_lower = texto.lower()
        
        # 1. Verificar pago
        if any(p in texto_lower for p in ['pague', 'pago', 'pagado', 'transferí', 'consigné', 'pagué', 'ya pague', 'listo el pago']):
            logger.info("💰 [PAGO] Detectado mensaje de pago")
            return "✅ ¡Pago confirmado! En breve comenzamos a preparar tu pedido."
        
        # 2. Verificar si quiere personalizar algo (NUEVO)
        palabras_personalizar = ['personalizar', 'personalizado', 'customizar', 'a mi gusto', 'quiero crear', 'hacer una']
        if any(p in texto_lower for p in palabras_personalizar):
            # Buscar configuraciones disponibles
            configs = schema_manager.get_configuraciones_personalizacion(tenant['id'], solo_activos=True)
            if configs:
                if len(configs) == 1:
                    return self._iniciar_personalizacion_por_config(tenant['id'], numero, configs[0]['nombre'])
                else:
                    mensaje = "🎨 *Opciones de personalización disponibles:*\n\n"
                    for i, cfg in enumerate(configs, 1):
                        mensaje += f"{i}. {cfg['nombre'].capitalize()}\n"
                        if cfg.get('descripcion'):
                            mensaje += f"   {cfg['descripcion']}\n"
                    mensaje += "\n📝 Responde con el número de la opción que deseas personalizar"
                    return mensaje
        
        # 3. Verificar respuesta de selección de configuración
        if texto_lower.isdigit() and 1 <= int(texto_lower) <= 10:
            configs = schema_manager.get_configuraciones_personalizacion(tenant['id'], solo_activos=True)
            idx = int(texto_lower) - 1
            if 0 <= idx < len(configs):
                return self._iniciar_personalizacion_por_config(tenant['id'], numero, configs[idx]['nombre'])
        
        # 4. Verificar confirmación
        if self._cliente_confirmo(texto):
            logger.info(f"✅ [CONFIRMACION] Cliente confirmó: {texto}")
            if carrito_actual.get('items'):
                self._guardar_datos_cliente_en_bd(tenant['id'], numero)
                return self._finalizar_pedido(tenant, numero, carrito_actual)
            else:
                productos_encontrados = self._extraer_productos_del_historial_con_ia(historial, menu)
                if productos_encontrados:
                    self._agregar_al_carrito(tenant['id'], numero, productos_encontrados)
                    carrito_actual = self._cargar_carrito(tenant['id'], numero)
                    if carrito_actual.get('items'):
                        return self._finalizar_pedido(tenant, numero, carrito_actual)
                return "❌ No pude identificar los productos que deseas. Por favor, escríbelos nuevamente.\n\nEjemplo: 'quiero una torta porcion personal'"
        
        # 5. Verificar consulta de carrito
        if any(p in texto_lower for p in ['qué pedí', 'mi pedido', 'ver carrito', 'que tengo']):
            return self._mostrar_resumen_carrito(tenant, numero, carrito_actual)
        
        # 6. Verificar si quiere ver el menú
        if any(p in texto_lower for p in ['menú', 'menu', 'productos', 'catálogo', 'catalogo', 'qué venden']):
            return self._mostrar_menu(tenant, menu)
        
        # 7. Detectar productos en el mensaje actual
        productos_detectados = self._extraer_productos_con_ia(texto, menu)
        
        # 8. Si hay productos, procesar el primero con sus adicionales
        if productos_detectados:
            producto = productos_detectados[0]
            logger.info(f"🛒 [PRODUCTO] Detectado: {producto}")
            return self._procesar_seleccion_producto(tenant['id'], numero, producto['id'])
        
        # 9. Si hay carrito, mostrar resumen
        if carrito_actual.get('items'):
            return self._mostrar_resumen_carrito(tenant, numero, carrito_actual)
        
        # 10. Si no hay carrito, usar IA para responder
        return self._respuesta_con_ia(texto, tenant, menu, numero, contexto, resumen_cliente, historial_texto)
    
    def _mostrar_menu(self, tenant: dict, menu: list) -> str:
        """Muestra el menú de productos disponibles"""
        if not menu:
            return "📋 No hay productos disponibles en este momento."
        
        categorias = {}
        for p in menu:
            cat = p.get('categoria', 'general')
            if cat not in categorias:
                categorias[cat] = []
            categorias[cat].append(p)
        
        mensaje = f"📋 *MENÚ DE {tenant.get('nombre', 'PRODUCTOS')}*\n\n"
        
        for cat, productos in categorias.items():
            emoji = self._get_emoji_categoria(cat)
            mensaje += f"*{emoji} {cat.upper()}*\n"
            for p in productos[:10]:
                mensaje += f"• *{p['nombre']}* - ${p['precio']:,}\n"
                if p.get('descripcion'):
                    mensaje += f"  {p['descripcion'][:60]}...\n"
            mensaje += "\n"
        
        # Verificar si hay configuraciones de personalización
        configs = schema_manager.get_configuraciones_personalizacion(tenant['id'], solo_activos=True)
        if configs:
            mensaje += "🎨 *¿Quieres personalizar algo?*\n"
            for cfg in configs:
                mensaje += f"• *{cfg['nombre'].capitalize()} personalizada*\n"
            mensaje += "\n"
        
        mensaje += "📝 *Para pedir, solo escribe el nombre del producto*\n"
        mensaje += "Ejemplo: 'quiero una torta porcion personal'"
        
        return mensaje
    
    def _get_emoji_categoria(self, categoria: str) -> str:
        emojis = {
            'tortas': '🍰',
            'postres': '🍨',
            'panes': '🥖',
            'bebidas': '🥤',
            'pizzas': '🍕',
            'hamburguesas': '🍔',
            'general': '📦',
            'adicionales': '➕'
        }
        return emojis.get(categoria.lower(), '📦')
    
    def _respuesta_con_ia(self, texto: str, tenant: dict, menu: list, numero: str, contexto: dict, resumen_cliente: str, historial_texto: str) -> str:
        """Genera respuesta usando IA"""
        menu_simplificado = [{'nombre': p.get('nombre'), 'precio': p.get('precio')} for p in menu[:30]]
        
        # Obtener configuraciones disponibles
        configs = schema_manager.get_configuraciones_personalizacion(tenant['id'], solo_activos=True)
        configs_texto = "\n".join([f"- {c['nombre'].capitalize()} personalizada" for c in configs]) if configs else "No hay opciones de personalización"
        
        system_prompt = f"""Eres un asistente de ventas conversacional para {tenant.get('nombre', 'Mi negocio')}.

🏪 INFORMACIÓN:
- Horario: {contexto.get('horario', 'No especificado')}
- Ubicación: {contexto.get('ubicacion', 'No especificada')}

📋 PRODUCTOS DISPONIBLES:
{json.dumps(menu_simplificado, indent=2, ensure_ascii=False)}

🎨 OPCIONES DE PERSONALIZACIÓN DISPONIBLES:
{configs_texto}

{resumen_cliente}
{historial_texto}

INSTRUCCIONES IMPORTANTES:
1. Responde de forma natural, cálida y conversacional en español.
2. Cuando el cliente pida un producto, confirma los detalles.
3. Si el cliente quiere personalizar, ofrécele las opciones disponibles.
4. NO generes números de pedido ni confirmes reservas.
5. Para finalizar, el cliente debe decir "confirmo".
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
            return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿Te gustaría ordenar {sugerencias} o personalizar algo? Escríbeme lo que deseas."
        return f"Hola! Soy el asistente de {tenant.get('nombre', 'mi negocio')}. ¿En qué puedo ayudarte?"


# Instancia global
message_handler = MessageHandler()