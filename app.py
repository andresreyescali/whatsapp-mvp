from flask import Flask, request, jsonify
import json
import uuid
import os
import requests
import sqlite3

app = Flask(__name__)

# ================================
# Cargar menú
# ================================
with open("menu.json") as f:
    menu = json.load(f)

# ================================
# BASE DE DATOS (SQLite)
# ================================

def get_db():
    conn = sqlite3.connect("pedidos.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pedidos (
        id TEXT PRIMARY KEY,
        numero TEXT,
        item TEXT,
        total INTEGER,
        estado TEXT
    )
    """)

    conn.commit()
    conn.close()

def crear_pedido(pedido_id, numero, item, total):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO pedidos (id, numero, item, total, estado)
    VALUES (?, ?, ?, ?, ?)
    """, (pedido_id, numero, item, total, "pendiente_pago"))

    conn.commit()
    conn.close()

def marcar_pagado(numero):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE pedidos
    SET estado = 'pagado'
    WHERE numero = ? AND estado = 'pendiente_pago'
    """, (numero,))

    conn.commit()
    conn.close()

def obtener_pedidos():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM pedidos")
    rows = cursor.fetchall()

    conn.close()
    return [dict(row) for row in rows]

# ================================
# Pago (simulado)
# ================================

def generar_link_pago(total, referencia):
    return f"https://checkout.wompi.co/l/test_{referencia}_{total}"

# ================================
# Lógica de mensajes
# ================================

def procesar_mensaje(texto, numero):
    texto = texto.lower()

    if "menu" in texto:
        return "🍔 Menú:\n- Hamburguesa ($18k)\n- Pizza ($25k)\n- Gaseosa ($5k)"

    if "pague" in texto:
        marcar_pagado(numero)
        return "Pago confirmado! ✅ Tu pedido va en camino 🚀"

    if "horario" in texto:
        return "🕒 Abrimos de 12pm a 10pm"

    if "ubicacion" in texto or "donde" in texto:
        return "📍 Estamos en Cali"

    for item in menu:
        if item.lower() in texto:
            total = menu[item]
            pedido_id = str(uuid.uuid4())

            crear_pedido(pedido_id, numero, item, total)

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
# Enviar mensaje WhatsApp
# ================================

def enviar_whatsapp(numero, mensaje):
    token = os.environ.get("WHATSAPP_TOKEN")
    phone_id = os.environ.get("WHATSAPP_PHONE_ID")

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

    print(f"📤 Enviando a {numero}: {mensaje}")
    print("Status:", r.status_code, r.text)

# ================================
# Webhook
# ================================

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        token = "mi_token_123"
        if request.args.get("hub.verify_token") == token:
            return request.args.get("hub.challenge")
        return "Error: token inválido"

    if request.method == "POST":
        data = request.get_json(force=True)

        print("\n====================")
        print("📩 REQUEST RAW:")
        print(data)
        print("====================\n")

        try:
            mensaje = data["entry"][0]["changes"][0]["value"]["messages"][0]
            numero = mensaje["from"]
            texto = mensaje["text"]["body"]
        except (KeyError, IndexError):
            print("❌ No se pudo extraer mensaje")
            return "no message"

        respuesta = procesar_mensaje(texto, numero)
        enviar_whatsapp(numero, respuesta)

        return "ok"

# ================================
# Endpoints útiles
# ================================

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "OK", 200

@app.route("/pedidos", methods=["GET"])
def ver_pedidos():
    return jsonify(obtener_pedidos())

# ================================
# RUN
# ================================

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)