from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager
from whatsapp.client import whatsapp_client

class MessageHandler:
    def process(self, phone_id: str, numero: str, texto: str):
        tenant = tenant_repo.find_by_phone_id(phone_id)
        if not tenant:
            return
        menu = schema_manager.get_menu(tenant['id'])
        respuesta = self._responder_tradicional(texto, menu)
        whatsapp_client.send_message(tenant, numero, respuesta)
    
    def _responder_tradicional(self, texto: str, menu: list) -> str:
        if 'menu' in texto.lower():
            return self._formatear_menu(menu)
        return 'Escribe "menu" para ver nuestros productos'
    
    def _formatear_menu(self, menu: list) -> str:
        if not menu:
            return 'Menu no disponible'
        respuesta = 'Menu:\n'
        for p in menu:
            respuesta += f'- {p["nombre"]}: ${p["precio"]}\n'
        return respuesta

message_handler = MessageHandler()