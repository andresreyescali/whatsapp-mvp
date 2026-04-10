from flask import Flask, request, jsonify
from datetime import datetime
import json
import uuid
import os
import requests
import psycopg2

ADMIN_KEY = os.environ.get("ADMIN_KEY")
app = Flask(__name__)

# ================================
# DB
# ================================

def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS negocios (
        id TEXT PRIMARY KEY,
        nombre TEXT,
        phone_id TEXT,
        token TEXT,
        menu TEXT
    );
    """)

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

    conn.commit()
    conn.close()

def rows_to_dict(cursor, rows):
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]

# ================================
# NEGOCIOS
# ================================

def obtener_negocio(phone_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM negocios WHERE phone_id = %s", (phone_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    negocio = rows_to_dict(cursor, [row])[0]
    conn.close()
    return negocio

# ================================
# PEDIDOS
# ================================

def crear_pedido(pedido_id, numero, item, total, negocio_id):
    conn = get_db()
    cursor = conn.cursor()

    fecha = datetime.now()

    print("🧾 creando pedido...", flush=True)
    print("🆔 negocio_id:", negocio_id, flush=True)
    print("📦 item:", item, flush=True)
    print("💰 total:", total, flush=True)

    cursor.execute("""
    INSERT INTO pedidos (id, numero, item, total, estado, negocio_id, fecha)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (pedido_id, numero, item, total, "pendiente_pago", negocio_id, fecha))

    conn.commit()
    conn.close()

def marcar_pagado(numero, negocio_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE pedidos
    SET estado = 'pagado'
    WHERE numero = %s AND negocio_id = %s AND estado = 'pendiente_pago'
    """, (numero, negocio_id))

    conn.commit()
    conn.close()

# ================================
# LÓGICA MENSAJES
# ================================

def generar_link_pago(total, referencia):
    return f"https://checkout.wompi.co/l/test_{referencia}_{total}"

def procesar_mensaje(texto, numero, negocio):
    texto = texto.lower()
    menu = json.loads(negocio["menu"])

    if "menu" in texto:
        respuesta = "🍔 Menú:\n"
        for item, precio in menu.items():
            respuesta += f"- {item.capitalize()} (${precio})\n"
        return respuesta

    if "pague" in texto:
        marcar_pagado(numero, negocio["id"])
        return "Pago confirmado! ✅ Tu pedido va en camino 🚀"

    if "horario" in texto:
        return "🕒 Abrimos de 12pm a 10pm"

    if "ubicacion" in texto or "donde" in texto:
        return "📍 Estamos en Cali"

    for item in menu:
        if item.lower() in texto:
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
    if request.method == "GET":
        token = "mi_token_123"
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
# ENDPOINTS
# ================================

@app.route("/crear_negocio", methods=["GET"])
def crear_negocio():
    key = request.args.get("key")

    if key != ADMIN_KEY:
        return "Unauthorized", 401

    conn = get_db()
    cursor = conn.cursor()

    menu = json.dumps({
        "pizza": 25000,
        "gaseosa": 5000
    })

    cursor.execute("""
    INSERT INTO negocios (id, nombre, phone_id, token, menu)
    VALUES (%s, %s, %s, %s, %s)
    """, (
        str(uuid.uuid4()),
        "Pizzeria Avars",
        "946960701843409",
        "TU_TOKEN",
        menu
    ))

    conn.commit()
    conn.close()

    return "Negocio creado ✅"

@app.route("/pedidos/<negocio_id>", methods=["GET"])
def ver_pedidos(negocio_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM pedidos WHERE negocio_id = %s", (negocio_id,))
    rows = cursor.fetchall()

    pedidos = rows_to_dict(cursor, rows)

    conn.close()

    return jsonify(pedidos)

# ================================
# RUN
# ================================

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)