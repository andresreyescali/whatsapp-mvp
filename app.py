from flask import Flask, request, jsonify
import json
import uuid
import os

app = Flask(__name__)

with open("menu.json") as f:
    menu = json.load(f)

def leer_pedidos():
    with open("pedidos.json") as f:
        return json.load(f)

def guardar_pedidos(pedidos):
    with open("pedidos.json", "w") as f:
        json.dump(pedidos, f, indent=2)

def generar_link_pago(total, referencia):
    return f"https://checkout.wompi.co/l/test_{referencia}_{total}"

def procesar_mensaje(texto, numero):
    texto = texto.lower()

    if "menu" in texto:
        return "🍔 Menú:\n- Hamburguesa ($18k)\n- Pizza ($25k)\n- Gaseosa ($5k)"

    for item in menu:
        if item in texto:
            total = menu[item]
            pedido_id = str(uuid.uuid4())

            pedidos = leer_pedidos()
            pedidos.append({
                "id": pedido_id,
                "numero": numero,
                "item": item,
                "total": total,
                "estado": "pendiente_pago"
            })
            guardar_pedidos(pedidos)

            link = generar_link_pago(total, pedido_id)

            return f"""Perfecto 👍
{item} - ${total}

Paga aquí 👇
{link}

Te confirmo cuando pagues ✅"""
    return "Hola 👋 escribe 'menu' para ver opciones"

@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    # 🔐 Verificación de Meta (GET)
    if request.method == "GET":
        token = "mi_token_123"

        if request.args.get("hub.verify_token") == token:
            return request.args.get("hub.challenge")

        return "Error de verificación"

    # 📩 Mensajes entrantes (POST)
    if request.method == "POST":
        data = request.json

        print("📩 REQUEST RECIBIDO:")
        print(data)

        try:
            # Para pruebas manuales
            if "from" in data:
                numero = data.get("from")
                texto = data.get("text")

            # Para WhatsApp real (Meta)
            else:
                mensaje = data["entry"][0]["changes"][0]["value"]["messages"][0]
                numero = mensaje["from"]
                texto = mensaje["text"]["body"]

            respuesta = procesar_mensaje(texto, numero)

            print(f"\n📲 Enviando a {numero}:\n{respuesta}\n")

        except Exception as e:
            print("❌ Error:", e)

        return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
