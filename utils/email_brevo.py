import requests
import os
from core.logger import logger

class BrevoEmailSender:
    """Servicio para enviar emails usando Brevo API (gratuito - 300 emails/día)"""
    
    def __init__(self):
        self.api_key = os.environ.get('BREVO_API_KEY')
        self.from_email = os.environ.get('EMAIL_FROM', '')
        self.from_name = os.environ.get('EMAIL_FROM_NAME', 'WhatsApp Bot SaaS')
        
        # Log de configuración
        logger.info(f"Email sender configurado - API Key: {'Configurada' if self.api_key else 'NO CONFIGURADA'}")
        logger.info(f"Email FROM: {self.from_email if self.from_email else 'NO CONFIGURADO'}")
    
    def enviar_codigo_verificacion(self, email_to: str, codigo: str, nombre_negocio: str) -> bool:
        """Envía código de verificación por email usando Brevo API"""
        
        logger.info(f"=== INICIANDO ENVÍO DE EMAIL ===")
        logger.info(f"Para: {email_to}")
        logger.info(f"Código: {codigo}")
        logger.info(f"Negocio: {nombre_negocio}")
        
        if not self.api_key:
            logger.error("❌ BREVO_API_KEY no configurada en variables de entorno")
            return False
        
        subject = f"🔐 Código de verificación - {nombre_negocio}"
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #25D366; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
        .content {{ padding: 20px; background: #f9f9f9; }}
        .code {{ font-size: 32px; font-weight: bold; color: #25D366; text-align: center; padding: 20px; letter-spacing: 5px; background: white; border-radius: 10px; }}
        .footer {{ font-size: 12px; color: #666; text-align: center; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>🤖 WhatsApp Bot SaaS</h2>
        </div>
        <div class="content">
            <h2>¡Hola!</h2>
            <p>Has registrado el negocio <strong>{nombre_negocio}</strong> en WhatsApp Bot SaaS.</p>
            <p>Para activar tu asistente de ventas, ingresa el siguiente código de verificación:</p>
            <div class="code">{codigo}</div>
            <p>Este código expira en <strong>10 minutos</strong>.</p>
            <p>Si no solicitaste este registro, ignora este mensaje.</p>
        </div>
        <div class="footer">
            <p>© 2026 WhatsApp Bot SaaS - Automatiza tus ventas</p>
        </div>
    </div>
</body>
</html>
        """
        
        text_content = f"""
Código de verificación: {codigo}

Este código expira en 10 minutos.

Ingresa este código en el panel de control para activar tu asistente de ventas.
        """
        
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json"
        }
        
        # Configurar datos del email
        data = {
            "to": [{"email": email_to}],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content
        }
        
        # Brevo permite omitir el sender, usará el predeterminado de la cuenta
        if self.from_email:
            data["sender"] = {"name": self.from_name, "email": self.from_email}
            logger.info(f"Usando sender: {self.from_email}")
        else:
            logger.info("No se especificó sender, Brevo usará el predeterminado")
        
        logger.info(f"Enviando petición a Brevo...")
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            logger.info(f"Respuesta Brevo - Status code: {response.status_code}")
            logger.info(f"Respuesta Brevo - Body: {response.text}")
            
            if response.status_code == 201:
                logger.info(f"✅ Email de verificación enviado a {email_to}")
                return True
            else:
                logger.error(f"❌ Error enviando email: {response.status_code} - {response.text}")
                return False
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout conectando a Brevo")
            return False
        except Exception as e:
            logger.error(f"❌ Error enviando email: {e}")
            import traceback
            traceback.print_exc()
            return False
# Agregar estos métodos a la clase BrevoEmailSender

    def enviar_confirmacion_pedido(self, email_to: str, nombre_negocio: str, numero_pedido: str, items: list, total: int, cliente_numero: str) -> bool:
        """Envía email de confirmación de pedido"""
        if not self.api_key:
            logger.error("BREVO_API_KEY no configurada")
            return False
        
        items_html = ""
        for item in items:
            subtotal = item['precio'] * item.get('cantidad', 1)
            items_html += f"<tr><td>{item.get('cantidad', 1)}x {item['nombre']}</td><td>${subtotal:,.0f}</td></tr>"
        
        from datetime import datetime
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"></head>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #25D366; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
                    <h2>🛒 Nuevo Pedido - {nombre_negocio}</h2>
                </div>
                <div style="background: #f9f9f9; padding: 20px; border-radius: 0 0 10px 10px;">
                    <h3>📋 Pedido #{numero_pedido}</h3>
                    <p><strong>📱 Cliente:</strong> {cliente_numero}</p>
                    <p><strong>🕒 Fecha:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                    <h3>🛒 Productos:</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="background: #e0e0e0;"><th>Producto</th><th>Subtotal</th></tr>
                        {items_html}
                        <tr style="background: #f0f0f0; font-weight: bold;"><td>Total</td><td>${total:,.0f}</td></tr>
                    </table>
                    <div style="margin-top: 20px; text-align: center;">
                        <a href="https://whatsapp-mvp-docker.onrender.com/admin/tenants" style="background: #25D366; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">📊 Ver en Panel</a>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self._enviar_email(email_to, f"🛒 Nuevo Pedido #{numero_pedido} - {nombre_negocio}", html)

    def enviar_actualizacion_pedido(self, email_to: str, nombre_negocio: str, numero_pedido: str, estado: str) -> bool:
        """Envía email de actualización de pedido (prioridad alta)"""
        if not self.api_key:
            return False
        
        emoji = "✅" if estado == "pagado" else "🚚" if estado == "enviado" else "❌"
        texto = "PAGADO" if estado == "pagado" else "ENVIADO" if estado == "enviado" else "CANCELADO"
        color = "#4CAF50" if estado == "pagado" else "#FF9800" if estado == "enviado" else "#f44336"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"></head>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: {color}; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
                    <h2>{emoji} Pedido #{numero_pedido} - {texto}</h2>
                </div>
                <div style="background: #fff3e0; padding: 20px; border-radius: 0 0 10px 10px;">
                    <p>El estado de tu pedido ha sido actualizado a: <strong>{estado.upper()}</strong></p>
                    <div style="margin-top: 20px; text-align: center;">
                        <a href="https://whatsapp-mvp-docker.onrender.com/admin/tenants" style="background: {color}; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">📊 Ver Pedido</a>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self._enviar_email(email_to, f"⚠️ Pedido #{numero_pedido} actualizado - {nombre_negocio}", html)

    def _enviar_email(self, email_to: str, subject: str, html_content: str) -> bool:
        """Método interno para enviar email"""
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json"
        }
        
        data = {
            "to": [{"email": email_to}],
            "subject": subject,
            "htmlContent": html_content
        }
        
        if self.from_email:
            data["sender"] = {"name": self.from_name, "email": self.from_email}
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            if response.status_code == 201:
                logger.info(f"✅ Email enviado a {email_to}")
                return True
            else:
                logger.error(f"❌ Error enviando email: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Error enviando email: {e}")
            return False

# Instancia global
email_sender = BrevoEmailSender()