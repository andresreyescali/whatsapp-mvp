def generar_link_pago(total: int, referencia: str) -> str:
    """Genera un link de pago (ejemplo con Wompi)"""
    # Esto es un ejemplo - reemplazar con tu integración real de pagos
    return f"https://checkout.wompi.co/l/test_{referencia}_{total}"