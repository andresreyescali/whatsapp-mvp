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

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    numero = data.get("from")
    texto = data.get("text")

    respuesta = procesar_mensaje(texto, numero)
    print(f"\n📲 Enviando a {numero}:\n{respuesta}\n")

    return jsonify({"status": "ok"})

@app.route("/webhook-wompi", methods=["POST"])
def webhook_wompi():
    data = request.json
    referencia = data.get("referencia")

    pedidos = leer_pedidos()
    pedido = next((p for p in pedidos if p["id"] == referencia), None)

    if pedido:
        pedido["estado"] = "pagado"
        guardar_pedidos(pedidos)

        print(f"\n📲 Enviando a {pedido['numero']}:\n✅ Pago recibido. Tu pedido está en preparación 🍔\n")

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
