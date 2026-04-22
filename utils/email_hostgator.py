import smtplib
import ssl
import os
from email.message import EmailMessage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from core.logger import logger

class HostGatorEmailSender:
    """Servicio para enviar emails usando SMTP de HostGator"""
    
    def __init__(self):
        # Configuración desde variables de entorno
        self.smtp_server = os.environ.get('HOSTGATOR_SMTP_SERVER', 'smtp.hostgator.com')
        self.smtp_port = int(os.environ.get('HOSTGATOR_SMTP_PORT', 465))
        self.email_user = os.environ.get('HOSTGATOR_EMAIL_USER')
        self.email_password = os.environ.get('HOSTGATOR_EMAIL_PASSWORD')
        self.from_name = os.environ.get('EMAIL_FROM_NAME', 'WhatsApp Bot SaaS')
    
    def enviar_codigo_verificacion(self, email_to: str, codigo: str, nombre_negocio: str) -> bool:
        """Envía código de verificación por email usando SMTP de HostGator"""
        
        if not self.email_user or not self.email_password:
            logger.error("Credenciales de email no configuradas")
            return False
        
        subject = f"🔐 Código de verificación - {nombre_negocio}"
        
        # Crear mensaje
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.email_user  # IMPORTANTE: Debe coincidir exactamente [citation:7]
        msg['To'] = email_to
        
        # Versión texto plano
        text_content = f"""
Código de verificación: {codigo}

Este código expira en 10 minutos.

Ingresa este código en el panel de control para activar tu asistente de ventas.
"""
        
        # Versión HTML
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #25D366; color: white; padding: 20px; text-align: center; }}
        .code {{ font-size: 32px; font-weight: bold; color: #25D366; text-align: center; padding: 20px; letter-spacing: 5px; }}
        .footer {{ font-size: 12px; color: #666; text-align: center; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>WhatsApp Bot SaaS</h2>
        </div>
        <h2>¡Hola!</h2>
        <p>Has registrado el negocio <strong>{nombre_negocio}</strong> en WhatsApp Bot SaaS.</p>
        <p>Para activar tu asistente de ventas, ingresa el siguiente código de verificación:</p>
        <div class="code">{codigo}</div>
        <p>Este código expira en <strong>10 minutos</strong>.</p>
        <p>Si no solicitaste este registro, ignora este mensaje.</p>
        <div class="footer">
            <p>© 2026 WhatsApp Bot SaaS - Automatiza tus ventas</p>
        </div>
    </div>
</body>
</html>
"""
        
        # Adjuntar ambas versiones
        part1 = MIMEText(text_content, 'plain')
        part2 = MIMEText(html_content, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        try:
            # Puerto 465: usar SMTP_SSL (SSL directo) [citation:1]
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
                    server.login(self.email_user, self.email_password)
                    server.send_message(msg)
            else:
                # Puerto 587: usar STARTTLS
                context = ssl.create_default_context()
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.starttls(context=context)
                    server.login(self.email_user, self.email_password)
                    server.send_message(msg)
            
            logger.info(f"Email de verificación enviado a {email_to} vía HostGator")
            return True
            
        except smtplib.SMTPAuthenticationError:
            logger.error("Error de autenticación SMTP. Verifica usuario/contraseña")
            return False
        except Exception as e:
            logger.error(f"Error enviando email: {e}")
            return False

email_sender = HostGatorEmailSender()