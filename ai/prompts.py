class PromptBuilder:
    @staticmethod
    def build_response_prompt(texto: str, tenant, menu: list) -> list:
        menu_texto = '\n'.join([f'- {p["nombre"]}: ${p["precio"]}' for p in menu[:20]])
        system_prompt = f'''Eres un asistente de ventas para {tenant["nombre"]}.
Menu:
{menu_texto}
Responde de forma amable y breve.'''
        return [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': texto}
        ]
