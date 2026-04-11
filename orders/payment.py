def generar_link_pago(total: int, referencia: str) -> str:
    return f'https://checkout.wompi.co/l/test_{referencia}_{total}'