from flask import Flask, request, jsonify
from datetime import datetime
import json
import uuid
import os
import requests
import sqlite3

ADMIN_KEY = os.environ.get("ADMIN_KEY")
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
    conn = sqlite3.connect("pedidos2.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # TABLA NEGOCIOS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS negocios (
        id TEXT PRIMARY KEY,
        nombre TEXT,
        phone_id TEXT,
        token TEXT,
        menu TEXT
    )
    """)

    # TABLA PEDIDOS (con negocio_id + fecha)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pedidos (
        id TEXT PRIMARY KEY,
        numero TEXT,
        item TEXT,
        total INTEGER,
        estado TEXT,
        negocio_id TEXT,
        fecha TEXT
    )
    """)

    conn.commit()
    conn.close()

def obtener_negocio(phone_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM negocios")
    row = cursor.fetchone()

    conn.close()

    return dict(row) if row else None

def crear_pedido(pedido_id, numero, item, total, negocio_id):
    
    conn = get_db()
    cursor = conn.cursor()

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO pedidos (id, numero, item, total, estado, negocio_id, fecha)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (pedido_id, numero, item, total, "pendiente_pago", negocio_id, fecha))
    
    print("🧾 creando pedido...", flush=True)
    print("🆔 negocio_id:", negocio["id"], flush=True)
    print("📦 item:", item, flush=True)
    print("💰 total:", total, flush=True)
    
    conn.commit()
    conn.close()

def marcar_pagado(numero, negocio_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE pedidos
    SET estado = 'pagado'
    WHERE numero = ? AND negocio_id = ? AND estado = 'pendiente_pago'
    """, (numero, negocio_id))

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

def procesar_mensaje(texto, numero, negocio):
    texto = texto.lower()
    menu = json.loads(negocio["menu"])

    # MENU dinámico
    if "menu" in texto:
        respuesta = "🍔 Menú:\n"
        print("📤 respuesta generada:", respuesta, flush=True)
        for item, precio in menu.items():
            respuesta += f"- {item.capitalize()} (${precio})\n"
        return respuesta

    # Pago
    if "pague" in texto:
        marcar_pagado(numero, negocio["id"])
        return "Pago confirmado! ✅ Tu pedido va en camino 🚀"

    # Respuestas básicas (puedes mover a DB después)
    if "horario" in texto:
        return "🕒 Abrimos de 12pm a 10pm"

    if "ubicacion" in texto or "donde" in texto:
        return "📍 Estamos en Cali"

    # Pedido
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
# Enviar mensaje WhatsApp
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

        print("\n====================", flush=True)
        print("📩 REQUEST RAW:", flush=True)
        print(data, flush=True)
        print("====================\n", flush=True)

        try:
            value = data["entry"][0]["changes"][0]["value"]

            phone_id = value["metadata"]["phone_number_id"]
            print("📱 phone_id recibido:", phone_id, flush=True)
            mensaje = value["messages"][0]

            numero = mensaje["from"]
            texto = mensaje["text"]["body"]

        except (KeyError, IndexError):
            print("❌ No se pudo extraer mensaje", flush=True)
            return "no message"

        # 🔥 MULTI-TENANT
        negocio = obtener_negocio(phone_id)
        print("🔎 buscando negocio con phone_id:", phone_id, flush=True)
        print("🏢 negocio encontrado:", negocio, flush=True)
        print("🆔 negocio_id:", negocio["id"] if negocio else None, flush=True)
        
        if not negocio:
            print("❌ Negocio no encontrado", flush=True)
            return "no negocio"

        # 🔥 PASAR NEGOCIO
        respuesta = procesar_mensaje(texto, numero, negocio)
        print("📤 respuesta generada:", respuesta,flush=True)

        # 🔥 ENVIAR CON TOKEN DEL NEGOCIO
        enviar_whatsapp(numero, respuesta, negocio)

        return "ok"

# ================================
# Endpoints útiles
# ================================

@app.route("/crear_negocio", methods=["GET"])
def crear_negocio_demo():
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
    VALUES (?, ?, ?, ?, ?)
    """, (
        str(uuid.uuid4()),
        "Pizzeria Avars",
        "946960701843409",
        "EAAUn9pg7tjIBRAIeJcCwfuS8npQDT4bZCTFZCQjLz9ge6ZAcQPHCZAZCaPWkglZBf7FgvRCYVlgZCjJCpdNZBZAA23l95ABJhE1mnq8eFjy7jBC6kDZCSR7VzC2mZB7x5ZBe8pzpjg3wQGkji4flEjZBuAxnSdUs3r1yNhcZA0ZBJXx0DyWtbmxNP47X5mzTZBP0bXZCjDevZAoyPO9BwheuhbPVZC0jlspVpWafQ6mVcZBM06quFtv6",
        menu
    ))

    conn.commit()
    conn.close()

    return "Negocio creado ✅"

@app.route("/pedidos/<negocio_id>", methods=["GET"])
def ver_pedidos_por_negocio(negocio_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM pedidos WHERE negocio_id = ?", (negocio_id,))
    rows = cursor.fetchall()

    conn.close()

    pedidos = [dict(row) for row in rows]

    return jsonify(pedidos)

# ================================
# RUN
# ================================

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)