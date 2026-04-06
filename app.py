from flask import Flask, request, jsonify
import json
import uuid
import os
import requests

app = Flask(__name__)

# Cargar menú
with open("menu.json") as f:
    menu = json.load(f)

# Funciones para leer y guardar pedidos
def leer_pedidos():
    if not os.path.exists("pedidos.json"):
        return []
    with open("pedidos.json") as f:
        return json.load(f)

def guardar_pedidos(pedidos):
    with open("pedidos.json", "w") as f:
        json.dump(pedidos, f, indent=2)

# Generar link de pago (demo)
def generar_link_pago(total, referencia):
    return f"https://checkout.wompi.co/l/test_{referencia}_{total}"

# Procesar mensaje de usuario
def procesar_mensaje(texto, numero):
    texto = texto.lower()

    if "menu" in texto:
        return "🍔 Menú:\n- Hamburguesa ($18k)\n- Pizza ($25k)\n- Gaseosa ($5k)"

    if "pague" in texto:
        pedidos = leer_pedidos()
        for p in pedidos:
                if p["numero"] == numero:
                p["estado"] = "pagado"
                guardar_pedidos(pedidos)
        return "Pago confirmado ✅"
    
    for item in menu:
        if item.lower() in texto:
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

🆔 Pedido: {pedido_id}
Producto: {item}
Total: ${total}

Paga aquí 👇
{link}

Te confirmo cuando pagues ✅"""
    return "Hola 👋 escribe 'menu' para ver opciones"

# Función para enviar mensaje a WhatsApp
def enviar_whatsapp(numero, mensaje):
    # token = os.environ.get("WHATSAPP_TOKEN")  # Tu token de WhatsApp Cloud
    # phone_id = os.environ.get("WHATSAPP_PHONE_ID")  # Tu número de WhatsApp ID
    token = "EAAUn9pg7tjIBRDri7t4dp7DXnTwC3GKy6BD0JVlQPRUmiZB0W4cFrPVPizjDkADUiGUXZAJwoLLoWKyZC9jPOSppwl5kVitkGjhuxvAv7uyWL1IpuhwFZAaZAb9lIVhwIsJ4XMDfOiCiBxpXEBVtV6QCnqAIuabkOaXP76LFhdU4bZC3k4lo3DpB6UefHkddZB7TT1H0fCHn2G9jsOoxnF35cZBFJblndhyKAQiKlphKeFmnIb7hkGMPTZBdsj6Nv4B3oI5VNYw0ZAvmBoEScKWmhCpwZDZD"
    phone_id = "946960701843409"
    url = f"https://graph.facebook.com/v15.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = {
        "messaging_product": "whatsapp",
        "to": numero,
        "text": {"body": mensaje}
    }
    r = requests.post(url, headers=headers, json=data)
    print(f"📤 Enviando a {numero}: {mensaje}")
    print("Status:", r.status_code, r.text)

# Webhook principal
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        # Verificación del token para Meta
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

        # Extraer número y texto correctamente
        try:
            mensaje = data["entry"][0]["changes"][0]["value"]["messages"][0]
            numero = mensaje["from"]
            texto = mensaje["text"]["body"]
        except (KeyError, IndexError):
            print("❌ No se pudo extraer número o texto")
            return "no text"

        print(f"👉 numero: {numero}")
        print(f"👉 texto: {texto}")

        respuesta = procesar_mensaje(texto, numero)

        # Enviar respuesta a WhatsApp
        enviar_whatsapp(numero, respuesta)

        return "ok"

@app.route("/pedidos", methods=["GET"])
def ver_pedidos():
    return jsonify(leer_pedidos())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)