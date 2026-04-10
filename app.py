from flask import Flask, request, jsonify
from datetime import datetime
from openai import OpenAI
import json
import uuid
import os
import requests
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

ADMIN_KEY = os.environ.get("ADMIN_KEY")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

app = Flask(__name__)

# Inicializar cliente de DeepSeek
if DEEPSEEK_API_KEY:
    deepseek_client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )
else:
    deepseek_client = None
    print("⚠️ DEEPSEEK_API_KEY no configurada, la IA no funcionará")

# ================================
# DB
# ================================

def get_db():
    """Retorna una conexión a la base de datos"""
    return psycopg.connect(os.environ["DATABASE_URL"])

def init_db():
    """Inicializa las tablas de la base de datos"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            # Tabla de negocios
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS negocios (
                id TEXT PRIMARY KEY,
                nombre TEXT,
                phone_id TEXT,
                token TEXT,
                menu TEXT,
                usar_ia BOOLEAN DEFAULT FALSE
            );
            """)
            
            # Tabla de pedidos
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id TEXT PRIMARY KEY,
                numero TEXT,
                item TEXT,
                total INTEGER,
                estado TEXT,
                negocio_id TEXT,
                fecha TIMESTAMP
            );
            """)
            
            # Agregar columna usar_ia si no existe (para migración)
            try:
                cursor.execute("ALTER TABLE negocios ADD COLUMN usar_ia BOOLEAN DEFAULT FALSE")
            except:
                pass  # La columna ya existe
            
            conn.commit()
    
    print("✅ Base de datos inicializada correctamente")

def obtener_negocio(phone_id):
    """Obtiene un negocio por su phone_id"""
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM negocios WHERE phone_id = %s", (phone_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

# ================================
# DEEPSEEK INTEGRATION
# ================================

def responder_con_ia(texto, negocio, numero, pedidos_pendientes=None):
    """
    Usa DeepSeek para generar respuestas inteligentes
    """
    if not deepseek_client:
        return None
        
    menu = json.loads(negocio["menu"])
    
    # Formatear menú para el prompt
    menu_texto = "\n".join([f"- {item}: ${precio}" for item, precio in menu.items()])
    
    # Obtener pedidos pendientes del cliente
    pedidos_info = ""
    if pedidos_pendientes:
        pedidos_info = "\nPedidos pendientes del cliente:\n"
        for pedido in pedidos_pendientes:
            pedidos_info += f"- {pedido['item']} (${pedido['total']}) - Estado: {pedido['estado']}\n"
    
    prompt = f"""
Eres un asistente de ventas por WhatsApp para el negocio "{negocio['nombre']}".

INFORMACIÓN DEL NEGOCIO:
- Nombre: {negocio['nombre']}
- Horario: 12pm a 10pm
- Ubicación: Cali

MENÚ:
{menu_texto}

{pedidos_info}

REGLAS IMPORTANTES:
1. Responde de forma corta, amigable y clara (máximo 2-3 oraciones).
2. Si el cliente pregunta por el menú, muéstrale las opciones disponibles.
3. Si el cliente menciona algún producto del menú, confirma el pedido y genera un link de pago.
4. Si el cliente dice "ya pague" o similar, confirma el pago.
5. Para ubicación, indica la dirección.
6. Para horario, indica el horario de atención.
7. Si el cliente saluda, responde amablemente y ofrece ayuda.

MENSAJE DEL CLIENTE: {texto}

RESPUESTA (corta y amigable):
"""
    
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Eres un vendedor experto en WhatsApp que responde de forma breve y amigable."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=200
        )
        
        respuesta_ia = response.choices[0].message.content
        print(f"🤖 DeepSeek respondió: {respuesta_ia}", flush=True)
        return respuesta_ia
        
    except Exception as e:
        print(f"❌ Error con DeepSeek: {str(e)}", flush=True)
        return None

def procesar_pedido_con_ia(texto, menu, negocio_id, numero):
    """
    Usa IA para detectar si el cliente quiere hacer un pedido
    Retorna: (item_encontrado, total, mensaje_confirmacion)
    """
    if not deepseek_client:
        return None, None, None
        
    prompt = f"""
Analiza si el siguiente mensaje de un cliente indica que quiere hacer un pedido de alguno de estos productos:

Menú disponible:
{json.dumps(menu, indent=2)}

Mensaje del cliente: "{texto}"

Instrucciones:
1. Si el cliente menciona UN producto del menú, responde SOLO con el nombre del producto exacto como aparece en el menú.
2. Si no menciona ningún producto, responde SOLO con "NO_PEDIDO".
3. Responde SOLO con el producto o "NO_PEDIDO", sin texto adicional.

Ejemplo:
- "quiero una pizza" -> pizza
- "dame una gaseosa" -> gaseosa
- "hola" -> NO_PEDIDO
"""
    
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=20
        )
        
        producto = response.choices[0].message.content.strip()
        
        if producto != "NO_PEDIDO" and producto in menu:
            total = menu[producto]
            pedido_id = str(uuid.uuid4())
            
            crear_pedido(pedido_id, numero, producto, total, negocio_id)
            
            link = generar_link_pago(total, pedido_id)
            
            mensaje = f"""Perfecto 👍

🆔 Pedido: {pedido_id}
{producto} - ${total}

Paga aquí 👇
{link}

Escribe 'ya pague' cuando completes el pago ✅"""
            
            return producto, total, mensaje
        
        return None, None, None
        
    except Exception as e:
        print(f"❌ Error procesando pedido con IA: {str(e)}", flush=True)
        return None, None, None

# ================================
# PEDIDOS
# ================================

def crear_pedido(pedido_id, numero, item, total, negocio_id):
    """Crea un nuevo pedido en la base de datos"""
    fecha = datetime.now()
    
    print("🧾 creando pedido...", flush=True)
    print("🆔 negocio_id:", negocio_id, flush=True)
    print("📦 item:", item, flush=True)
    print("💰 total:", total, flush=True)
    
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
            INSERT INTO pedidos (id, numero, item, total, estado, negocio_id, fecha)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (pedido_id, numero, item, total, "pendiente_pago", negocio_id, fecha))
            conn.commit()

def marcar_pagado(numero, negocio_id):
    """Marca un pedido como pagado"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
            UPDATE pedidos
            SET estado = 'pagado'
            WHERE numero = %s AND negocio_id = %s AND estado = 'pendiente_pago'
            """, (numero, negocio_id))
            conn.commit()
    
def obtener_pedidos_pendientes(numero, negocio_id):
    """Obtiene pedidos pendientes del cliente"""
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""
            SELECT * FROM pedidos 
            WHERE numero = %s AND negocio_id = %s AND estado = 'pendiente_pago'
            ORDER BY fecha DESC
            """, (numero, negocio_id))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

def obtener_pedidos_negocio(negocio_id):
    """Obtiene todos los pedidos de un negocio"""
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM pedidos WHERE negocio_id = %s", (negocio_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

def generar_link_pago(total, referencia):
    """Genera un link de pago (ejemplo con Wompi)"""
    return f"https://checkout.wompi.co/l/test_{referencia}_{total}"

def procesar_mensaje(texto, numero, negocio):
    """Procesa el mensaje del cliente y retorna la respuesta"""
    texto_lower = texto.lower()
    menu = json.loads(negocio["menu"])
    usar_ia = negocio.get("usar_ia", False)
    
    # Verificar si el negocio tiene IA activada
    if usar_ia and deepseek_client:
        print("🤖 Usando IA para responder...", flush=True)
        
        # Verificar si es confirmación de pago
        if any(palabra in texto_lower for palabra in ["pague", "pago", "pagado", "ya pague", "ya pagué"]):
            marcar_pagado(numero, negocio["id"])
            return "¡Pago confirmado! ✅ Tu pedido va en camino 🚀"
        
        # Intentar detectar pedido con IA
        producto, total, mensaje_pedido = procesar_pedido_con_ia(texto, menu, negocio["id"], numero)
        if producto:
            return mensaje_pedido
        
        # Si no es pedido, usar IA para respuesta general
        pedidos_pendientes = obtener_pedidos_pendientes(numero, negocio["id"])
        respuesta_ia = responder_con_ia(texto, negocio, numero, pedidos_pendientes)
        
        if respuesta_ia:
            return respuesta_ia
        else:
            # Fallback a lógica tradicional si la IA falla
            print("⚠️ Fallback a lógica tradicional", flush=True)
            return procesar_mensaje_tradicional(texto_lower, menu, numero, negocio)
    
    else:
        # Usar lógica tradicional
        return procesar_mensaje_tradicional(texto_lower, menu, numero, negocio)

def procesar_mensaje_tradicional(texto_lower, menu, numero, negocio):
    """Lógica original sin IA"""
    
    if "menu" in texto_lower:
        respuesta = "🍔 Menú:\n"
        for item, precio in menu.items():
            respuesta += f"- {item.capitalize()} (${precio})\n"
        return respuesta

    if "pague" in texto_lower or "pago" in texto_lower:
        marcar_pagado(numero, negocio["id"])
        return "¡Pago confirmado! ✅ Tu pedido va en camino 🚀"

    if "horario" in texto_lower:
        return "🕒 Abrimos de 12pm a 10pm"

    if "ubicacion" in texto_lower or "donde" in texto_lower:
        return "📍 Estamos en Cali"

    for item in menu:
        if item.lower() in texto_lower:
            total = menu[item]
            pedido_id = str(uuid.uuid4())

            crear_pedido(pedido_id, numero, item, total, negocio["id"])
            link = generar_link_pago(total, pedido_id)

            return f"""Perfecto 👍

🆔 Pedido: {pedido_id}
{item} - ${total}

Paga aquí 👇
{link}

Escribe 'ya pague' cuando completes el pago ✅"""

    return """Hola 👋

Puedes escribir:
🍔 menu
📍 ubicación
🕒 horario
"""

# ================================
# WHATSAPP
# ================================

def enviar_whatsapp(numero, mensaje, negocio):
    """Envía un mensaje por WhatsApp usando la API de Meta"""
    token = negocio["token"]
    phone_id = negocio["phone_id"]

    url = f"https://graph.facebook.com/v15.0/{phone_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": numero,
        "text": {"body": mensaje}
    }

    r = requests.post(url, headers=headers, json=data)

    print(f"📤 Enviando a {numero}: {mensaje}", flush=True)
    print("Status:", r.status_code, r.text, flush=True)

# ================================
# WEBHOOK
# ================================

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    """Webhook para recibir mensajes de WhatsApp"""
    if request.method == "GET":
        token = "EAAUn9pg7tjIBRAIeJcCwfuS8npQDT4bZCTFZCQjLz9ge6ZAcQPHCZAZCaPWkglZBf7FgvRCYVlgZCjJCpdNZBZAA23l95ABJhE1mnq8eFjy7jBC6kDZCSR7VzC2mZB7x5ZBe8pzpjg3wQGkji4flEjZBuAxnSdUs3r1yNhcZA0ZBJXx0DyWtbmxNP47X5mzTZBP0bXZCjDevZAoyPO9BwheuhbPVZC0jlspVpWafQ6mVcZBM06quFtv6"
        if request.args.get("hub.verify_token") == token:
            return request.args.get("hub.challenge")
        return "Error"

    data = request.get_json(force=True)

    print("\n====================", flush=True)
    print("📩 REQUEST RAW:", data, flush=True)
    print("====================\n", flush=True)

    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            print("ℹ️ Evento ignorado", flush=True)
            return "ok"

        mensaje = value["messages"][0]

        if "text" not in mensaje:
            print("ℹ️ Mensaje no es texto", flush=True)
            return "ok"

        phone_id = value["metadata"]["phone_number_id"]
        numero = mensaje["from"]
        texto = mensaje["text"]["body"]

        print("📱 phone_id:", phone_id, flush=True)
        print("📨 texto:", texto, flush=True)

    except Exception as e:
        print("❌ ERROR:", str(e), flush=True)
        return "error"

    negocio = obtener_negocio(phone_id)

    print("🏢 negocio:", negocio, flush=True)

    if not negocio:
        return "ok"

    respuesta = procesar_mensaje(texto, numero, negocio)

    enviar_whatsapp(numero, respuesta, negocio)

    return "ok"

# ================================
# ENDPOINTS ADMIN
# ================================

@app.route("/crear_negocio", methods=["GET"])
def crear_negocio():
    """Crea un nuevo negocio"""
    key = request.args.get("key")

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    nombre = request.args.get("nombre")
    phone_id = request.args.get("phone_id")
    token = request.args.get("token")
    usar_ia = request.args.get("usar_ia", "false").lower() == "true"

    if not nombre or not phone_id or not token:
        return "Faltan parámetros (nombre, phone_id, token)", 400

    # Verificar si ya existe
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM negocios WHERE phone_id = %s", (phone_id,))
            existente = cursor.fetchone()

            if existente:
                return "❌ Ya existe un negocio con ese phone_id"

            # Menú base
            menu = json.dumps({
                "pizza": 25000,
                "gaseosa": 5000,
                "hamburguesa": 18000,
                "perro caliente": 12000
            })

            negocio_id = str(uuid.uuid4())

            cursor.execute("""
            INSERT INTO negocios (id, nombre, phone_id, token, menu, usar_ia)
            VALUES (%s, %s, %s, %s, %s, %s)
            """, (negocio_id, nombre, phone_id, token, menu, usar_ia))

            conn.commit()

    print("✅ Negocio creado:", nombre, flush=True)
    print("🆔 negocio_id:", negocio_id, flush=True)
    print("🤖 IA activada:", usar_ia, flush=True)

    return jsonify({
        "status": "ok",
        "negocio_id": negocio_id,
        "nombre": nombre,
        "usar_ia": usar_ia
    })

@app.route("/pedidos/<negocio_id>", methods=["GET"])
def ver_pedidos(negocio_id):
    """Lista todos los pedidos de un negocio"""
    pedidos = obtener_pedidos_negocio(negocio_id)
    return jsonify(pedidos)

@app.route("/actualizar_token", methods=["GET"])
def actualizar_token():
    """Actualiza el token de WhatsApp de un negocio"""
    key = request.args.get("key")
    negocio_id = request.args.get("negocio_id")
    nuevo_token = request.args.get("token")

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
            UPDATE negocios
            SET token = %s
            WHERE id = %s
            """, (nuevo_token, negocio_id))
            conn.commit()

    return "Token actualizado ✅"

@app.route("/negocios", methods=["GET"])
def ver_negocios():
    """Lista todos los negocios"""
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT id, nombre, phone_id, usar_ia FROM negocios")
            rows = cursor.fetchall()
            negocios = [dict(row) for row in rows]

    return jsonify(negocios)

@app.route("/eliminar_negocio", methods=["GET"])
def eliminar_negocio():
    """Elimina un negocio y sus pedidos"""
    key = request.args.get("key")
    negocio_id = request.args.get("negocio_id")

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    if not negocio_id:
        return "Falta negocio_id", 400

    with get_db() as conn:
        with conn.cursor() as cursor:
            # Verificar si existe
            cursor.execute("SELECT * FROM negocios WHERE id = %s", (negocio_id,))
            negocio = cursor.fetchone()

            if not negocio:
                return "❌ Negocio no existe"

            print("🗑 Eliminando negocio:", negocio_id, flush=True)

            # Eliminar pedidos primero
            cursor.execute("DELETE FROM pedidos WHERE negocio_id = %s", (negocio_id,))

            # Eliminar negocio
            cursor.execute("DELETE FROM negocios WHERE id = %s", (negocio_id,))

            conn.commit()

    print("✅ Negocio eliminado:", negocio_id, flush=True)

    return jsonify({
        "status": "ok",
        "mensaje": "Negocio eliminado",
        "negocio_id": negocio_id
    })

@app.route("/activar_ia", methods=["GET"])
def activar_ia():
    """Activa o desactiva la IA en un negocio"""
    key = request.args.get("key")
    negocio_id = request.args.get("negocio_id")
    activar = request.args.get("activar", "true").lower() == "true"

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    if not negocio_id:
        return "Falta negocio_id", 400

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
            UPDATE negocios
            SET usar_ia = %s
            WHERE id = %s
            """, (activar, negocio_id))
            conn.commit()

    estado = "activada" if activar else "desactivada"
    print(f"🤖 IA {estado} para negocio {negocio_id}", flush=True)

    return jsonify({
        "status": "ok",
        "mensaje": f"IA {estado} correctamente",
        "negocio_id": negocio_id,
        "usar_ia": activar
    })

# ================================
# RUN
# ================================

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)