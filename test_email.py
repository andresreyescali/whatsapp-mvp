# test_email_local.py - ejecuta esto localmente
import smtplib

smtp_server = "smtp.titan.email"
smtp_port = 465
email_user = "no-reply@avarstechnology.com"  # ← Tu email completo
email_password = "P3p1t0123$"  # ← La contraseña que pusiste

try:
    server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
    server.login(email_user, email_password)
    print("✅ Autenticación exitosa")
    server.quit()
except Exception as e:
    print(f"❌ Error: {e}")