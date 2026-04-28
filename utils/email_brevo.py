import requests
import os
from core.logger import logger

class BrevoEmailSender:
    """Servicio para enviar emails usando Brevo API (gratuito - 300 emails/día)"""
    
    def __init__(self):
        self.api_key = os.environ.get('BREVO_API_KEY')
        # CORREGIDO: usar el email que usaste para registrar Brevo (debe estar verificado)
        self.from_email = os.environ.get('EMAIL_FROM', 'tu-email-registrado@gmail.com')
        self.from_name = os.environ.get('EMAIL_FROM_NAME', 'WhatsApp Bot SaaS')
    
    def enviar_codigo_verificacion(self, email_to: str, codigo: str, nombre_negocio: str) -> bool:
        """Envía código de verificación por email usando Brevo API"""
        
        if not self.api_key:
            logger.error("BREVO_API_KEY no configurada")
            return False
        
        # Si el email remitente no está configurado, usar el de la API (Brevo asigna uno por defecto)
        if not self.from_email or self.from_email == 'tu-email-registrado@gmail.com':
            # Brevo asigna un remitente por defecto si no especificas uno verificado
            self.from_email = None
        
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
        
        # Solo incluir sender si está configurado
        if self.from_email:
            data["sender"] = {"name": self.from_name, "email": self.from_email}
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            if response.status_code == 201:
                logger.info(f"✅ Email de verificación enviado a {email_to}")
                return True
            else:
                logger.error(f"❌ Error enviando email: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Error enviando email: {e}")
            return False

# Instancia global
email_sender = BrevoEmailSender()