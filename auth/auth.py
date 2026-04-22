import uuid
import hashlib
import secrets
import re
import requests
# from utils.email_hostgator import email_sender  # en lugar de email_sender
from datetime import datetime, timedelta
from core.database import db_manager
from core.logger import logger
from utils.email_brevo import email_sender

class AuthManager:
    """Gestión de autenticación de usuarios"""
    
    def __init__(self):
        self.pepper = "MiClaveSecretaSuperSegura2026"  # Cambiar por una variable de entorno
    
    def hash_password(self, password: str) -> str:
        """Hashea una contraseña"""
        salt = secrets.token_hex(16)
        hash_obj = hashlib.sha256((password + salt + self.pepper).encode())
        return f"{salt}:{hash_obj.hexdigest()}"
    
    def verify_password(self, password: str, stored_hash: str) -> bool:
        """Verifica una contraseña"""
        try:
            salt, hash_value = stored_hash.split(':')
            hash_obj = hashlib.sha256((password + salt + self.pepper).encode())
            return hash_obj.hexdigest() == hash_value
        except:
            return False
    
    def validar_email(self, email: str) -> bool:
        """Valida formato de email"""
        patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(patron, email) is not None
    
    def formatear_telefono(self, telefono: str) -> str:
        """Formatea el número de teléfono para WhatsApp"""
        if not telefono:
            return None
        
        # Limpiar el número (quitar espacios, guiones, etc.)
        telefono_limpio = re.sub(r'[\s\-\(\)]', '', str(telefono))
        
        # Si no tiene +, agregarlo
        if not telefono_limpio.startswith('+'):
            # Si empieza con 3 (Colombia sin código país)
            if telefono_limpio.startswith('3') and len(telefono_limpio) == 10:
                telefono_limpio = '+57' + telefono_limpio
            else:
                telefono_limpio = '+' + telefono_limpio
        
        return telefono_limpio
    
    def registrar_usuario(self, email: str, password: str, nombre_completo: str = None, telefono: str = None) -> dict:
        """Registra un nuevo usuario"""
        if not self.validar_email(email):
            return {'success': False, 'error': 'Email inválido'}
        
        if len(password) < 6:
            return {'success': False, 'error': 'La contraseña debe tener al menos 6 caracteres'}
        
        # Validar que el teléfono sea obligatorio
        if not telefono:
            return {'success': False, 'error': 'El número de teléfono es obligatorio para la verificación del negocio'}
        
        # Formatear teléfono
        telefono_formateado = self.formatear_telefono(telefono)
        
        # Verificar si el email ya existe
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM public.usuarios WHERE email = %s", (email,))
                if cur.fetchone():
                    return {'success': False, 'error': 'El email ya está registrado'}
        
        # Crear usuario
        usuario_id = str(uuid.uuid4())
        password_hash = self.hash_password(password)
        codigo_verificacion = secrets.token_hex(4).upper()
        
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        INSERT INTO public.usuarios (id, email, password_hash, nombre_completo, telefono, codigo_verificacion)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (usuario_id, email, password_hash, nombre_completo, telefono_formateado, codigo_verificacion))
                conn.commit()
            
            logger.info(f'Nuevo usuario registrado: {email} con teléfono {telefono_formateado}')
            
            return {
                'success': True,
                'usuario_id': usuario_id,
                'email': email,
                'codigo_verificacion': codigo_verificacion
            }
        except Exception as e:
            logger.error(f'Error registrando usuario: {e}')
            if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
                return {'success': False, 'error': 'El email ya está registrado'}
            return {'success': False, 'error': f'Error al registrar usuario'}
    
    def login(self, email: str, password: str) -> dict:
        """Autentica un usuario"""
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT u.id, u.email, u.password_hash, u.nombre_completo, u.email_verificado, u.activo,
                           rs.nombre as rol_sistema
                    FROM public.usuarios u
                    LEFT JOIN public.roles_sistema rs ON u.rol_sistema_id = rs.id
                    WHERE u.email = %s
                ''', (email,))
                row = cur.fetchone()
                
                if not row:
                    return {'success': False, 'error': 'Email o contraseña incorrectos'}
                
                usuario_id, email_db, password_hash, nombre, email_verificado, activo, rol_sistema = row
                
                if not activo:
                    return {'success': False, 'error': 'Cuenta desactivada. Contacta a soporte.'}
                
                if not self.verify_password(password, password_hash):
                    return {'success': False, 'error': 'Email o contraseña incorrectos'}
                
                # Actualizar último acceso
                cur.execute("UPDATE public.usuarios SET ultimo_acceso = NOW() WHERE id = %s", (usuario_id,))
                conn.commit()
        
        # Obtener negocios del usuario
        negocios = self.get_negocios_usuario(usuario_id)
        
        return {
            'success': True,
            'usuario_id': usuario_id,
            'email': email_db,
            'nombre': nombre,
            'email_verificado': email_verificado,
            'rol_sistema': rol_sistema,
            'negocios': negocios
        }
    
    def get_negocios_usuario(self, usuario_id: str) -> list:
        """Obtiene los negocios asociados a un usuario"""
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT t.id, t.nombre, t.phone_id, rn.nombre as rol, COALESCE(vn.verificado, false) as verificado
                    FROM public.usuario_negocio un
                    JOIN public.tenants t ON un.tenant_id = t.id
                    JOIN public.roles_negocio rn ON un.rol_id = rn.id
                    LEFT JOIN public.verificacion_negocio vn ON t.id = vn.tenant_id
                    WHERE un.usuario_id = %s
                ''', (usuario_id,))
                rows = cur.fetchall()
                return [{'id': r[0], 'nombre': r[1], 'phone_id': r[2], 'rol': r[3], 'verificado': r[4]} for r in rows]
    
    def crear_negocio(self, usuario_id: str, nombre: str, phone_id: str, token: str, tipo_negocio: str = 'restaurante') -> dict:
        """Crea un nuevo negocio para un usuario con verificación pendiente"""
        from tenants.repository import tenant_repo
        from tenants.schema_manager import schema_manager
        
        # Verificar que el nombre del negocio no existe
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM public.tenants WHERE nombre = %s", (nombre,))
                if cur.fetchone():
                    return {'success': False, 'error': 'Ya existe un negocio con ese nombre'}
        
        # Crear tenant
        tenant = tenant_repo.create(nombre, phone_id, token, tipo_negocio)
        schema_manager.create_tenant_schema(tenant['id'], tipo_negocio)
        
        # Asociar usuario al negocio como owner
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                # Obtener rol owner
                cur.execute("SELECT id FROM public.roles_negocio WHERE nombre = 'owner'")
                rol_owner_id = cur.fetchone()[0]
                
                cur.execute('''
                    INSERT INTO public.usuario_negocio (usuario_id, tenant_id, rol_id, invitado_por)
                    VALUES (%s, %s, %s, %s)
                ''', (usuario_id, tenant['id'], rol_owner_id, usuario_id))
            conn.commit()
        
        # Crear registro de verificación
        import secrets
        codigo_verificacion = secrets.token_hex(3).upper()
        
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO public.verificacion_negocio 
                    (tenant_id, metodo_verificacion, codigo_verificacion, codigo_enviado)
                    VALUES (%s, %s, %s, NOW())
                ''', (tenant['id'], 'codigo_verificacion', codigo_verificacion))
            conn.commit()
        
        logger.info(f'Nuevo negocio creado: {nombre} por usuario {usuario_id}')
        
        return {
            'success': True,
            'tenant_id': tenant['id'],
            'nombre': nombre,
            'codigo_verificacion': codigo_verificacion,
            'codigo_enviado': False,  # No enviamos automáticamente para evitar costos
            'mensaje': f'Código de verificación: {codigo_verificacion}'
        }
    
    def enviar_codigo_whatsapp(self, phone_id: str, token: str, codigo: str, telefono_cliente: str) -> bool:
        """Envía el código de verificación por WhatsApp"""
        from whatsapp.client import whatsapp_client
        
        # Crear un objeto tenant simulado para el envío
        tenant = {
            'phone_id': phone_id,
            'token': token
        }
        
        mensaje = f"""*🔐 CÓDIGO DE VERIFICACIÓN*

    Hola, gracias por registrar tu negocio en WhatsApp Bot SaaS.

    Tu código de verificación es:

    *{codigo}*

    Ingresa este código en el panel de control para activar tu asistente de ventas.

    Este código expira en 10 minutos.

    ¿No solicitaste este código? Ignora este mensaje.

    © WhatsApp Bot SaaS - Automatiza tus ventas"""
        
        # Enviar el mensaje
        return whatsapp_client.send_message(tenant, telefono_cliente, mensaje)
    
    def verificar_negocio(self, tenant_id: str, codigo: str) -> dict:
        """Verifica el código ingresado por el usuario (con expiración)"""
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT id, intentos_fallidos, codigo_verificacion, verificado, codigo_enviado
                    FROM public.verificacion_negocio WHERE tenant_id = %s
                ''', (tenant_id,))
                row = cur.fetchone()
                
                if not row:
                    return {'success': False, 'error': 'Negocio no encontrado'}
                
                intentos = row[1] or 0
                codigo_guardado = row[2]
                ya_verificado = row[3]
                fecha_envio = row[4]
                
                if ya_verificado:
                    return {'success': False, 'error': 'El negocio ya está verificado'}
                
                # Verificar expiración (10 minutos)
                if fecha_envio and datetime.now() - fecha_envio > timedelta(minutes=10):
                    return {'success': False, 'error': 'El código ha expirado. Por favor, solicita uno nuevo.'}
                
                if intentos >= 5:
                    return {'success': False, 'error': 'Demasiados intentos fallidos. Solicita un nuevo código.'}
                
                if codigo.upper() == codigo_guardado:
                    cur.execute('''
                        UPDATE public.verificacion_negocio 
                        SET verificado = true, fecha_verificacion = NOW()
                        WHERE tenant_id = %s
                    ''', (tenant_id,))
                    conn.commit()
                    return {'success': True, 'message': 'Negocio verificado exitosamente'}
                else:
                    nuevos_intentos = intentos + 1
                    cur.execute('''
                        UPDATE public.verificacion_negocio 
                        SET intentos_fallidos = %s
                        WHERE tenant_id = %s
                    ''', (nuevos_intentos, tenant_id))
                    conn.commit()
                    
                    restantes = 5 - nuevos_intentos
                    return {'success': False, 'error': f'Código incorrecto. Te quedan {restantes} intentos.'}
    
    # ==================== MÉTODOS PARA SUPER ADMIN ====================
    
    def get_all_usuarios(self) -> list:
        """Obtiene todos los usuarios (solo para super_admin)"""
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT u.id, u.email, u.nombre_completo, u.telefono, u.email_verificado, 
                           u.created_at, u.ultimo_acceso, u.activo, rs.nombre as rol
                    FROM public.usuarios u
                    LEFT JOIN public.roles_sistema rs ON u.rol_sistema_id = rs.id
                    ORDER BY u.created_at DESC
                ''')
                rows = cur.fetchall()
                columns = ['id', 'email', 'nombre', 'telefono', 'email_verificado', 
                          'created_at', 'ultimo_acceso', 'activo', 'rol']
                return [dict(zip(columns, row)) for row in rows]
    
    def get_all_negocios(self) -> list:
        """Obtiene todos los negocios (solo para super_admin)"""
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT t.id, t.nombre, t.phone_id, t.created_at, t.activo,
                           u.email as dueno_email, u.nombre_completo as dueno_nombre,
                           COALESCE(v.verificado, false) as verificado
                    FROM public.tenants t
                    LEFT JOIN public.usuario_negocio un ON t.id = un.tenant_id AND un.rol_id = 1
                    LEFT JOIN public.usuarios u ON un.usuario_id = u.id
                    LEFT JOIN public.verificacion_negocio v ON t.id = v.tenant_id
                    ORDER BY t.created_at DESC
                ''')
                rows = cur.fetchall()
                columns = ['id', 'nombre', 'phone_id', 'created_at', 'activo', 
                          'dueno_email', 'dueno_nombre', 'verificado']
                return [dict(zip(columns, row)) for row in rows]
    
    def actualizar_usuario(self, usuario_id: str, datos: dict) -> dict:
        """Actualiza datos de un usuario (solo super_admin)"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    updates = []
                    params = []
                    
                    if datos.get('nombre'):
                        updates.append("nombre_completo = %s")
                        params.append(datos['nombre'])
                    
                    if datos.get('email'):
                        # Verificar que el email no esté en uso por otro usuario
                        cur.execute("SELECT id FROM public.usuarios WHERE email = %s AND id != %s", 
                                (datos['email'], usuario_id))
                        if cur.fetchone():
                            return {'success': False, 'error': 'El email ya está en uso'}
                        updates.append("email = %s")
                        params.append(datos['email'])
                    
                    if datos.get('telefono'):
                        telefono_formateado = self.formatear_telefono(datos['telefono'])
                        updates.append("telefono = %s")
                        params.append(telefono_formateado)
                    
                    if datos.get('activo') is not None:
                        updates.append("activo = %s")
                        params.append(datos['activo'])
                    
                    if datos.get('rol_sistema'):
                        cur.execute("SELECT id FROM public.roles_sistema WHERE nombre = %s", (datos['rol_sistema'],))
                        rol_row = cur.fetchone()
                        if rol_row:
                            updates.append("rol_sistema_id = %s")
                            params.append(rol_row[0])
                    
                    if not updates:
                        return {'success': False, 'error': 'No hay datos para actualizar'}
                    
                    params.append(usuario_id)
                    query = f"UPDATE public.usuarios SET {', '.join(updates)} WHERE id = %s"
                    cur.execute(query, params)
                conn.commit()
            
            return {'success': True, 'message': 'Usuario actualizado'}
        except Exception as e:
            logger.error(f'Error actualizando usuario: {e}')
            return {'success': False, 'error': str(e)}
    
    def eliminar_usuario(self, usuario_id: str) -> dict:
        """Elimina un usuario y todos sus datos (solo super_admin)"""
        try:
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    # Eliminar relaciones usuario-negocio
                    cur.execute("DELETE FROM public.usuario_negocio WHERE usuario_id = %s", (usuario_id,))
                    # Eliminar el usuario
                    cur.execute("DELETE FROM public.usuarios WHERE id = %s", (usuario_id,))
                conn.commit()
            return {'success': True, 'message': 'Usuario eliminado'}
        except Exception as e:
            logger.error(f'Error eliminando usuario: {e}')
            return {'success': False, 'error': str(e)}
    
    # ==================== MÉTODOS PARA GESTIÓN DE ROLES ====================
    
    def get_rol_negocio(self, usuario_id: str, tenant_id: str) -> dict:
        """Obtiene el rol de un usuario en un negocio específico"""
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT rn.nombre as rol, rn.id as rol_id
                    FROM public.usuario_negocio un
                    JOIN public.roles_negocio rn ON un.rol_id = rn.id
                    WHERE un.usuario_id = %s AND un.tenant_id = %s
                ''', (usuario_id, tenant_id))
                row = cur.fetchone()
                if row:
                    return {'rol': row[0], 'rol_id': row[1]}
                return None
    
    def verificar_permiso(self, usuario_id: str, tenant_id: str, permiso_requerido: str) -> bool:
        """Verifica si un usuario tiene cierto permiso en un negocio"""
        roles_permitidos = {
            'editar_negocio': ['owner'],
            'invitar_usuarios': ['owner', 'admin'],
            'editar_menu': ['owner', 'admin', 'editor'],
            'ver_reportes': ['owner', 'admin', 'editor', 'viewer'],
            'entrenar_ia': ['owner', 'admin', 'editor'],
            'ver_pedidos': ['owner', 'admin', 'editor', 'viewer'],
            'eliminar_negocio': ['owner'],
            'ver_facturacion': ['owner']
        }
        
        roles_permitidos_list = roles_permitidos.get(permiso_requerido, [])
        if not roles_permitidos_list:
            return False
        
        usuario_rol = self.get_rol_negocio(usuario_id, tenant_id)
        if not usuario_rol:
            return False
        
        return usuario_rol['rol'] in roles_permitidos_list
    
    def get_usuarios_negocio(self, tenant_id: str) -> list:
        """Obtiene todos los usuarios de un negocio"""
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT u.id, u.email, u.nombre_completo, rn.nombre as rol,
                           un.invitado_por, un.invitado_en
                    FROM public.usuario_negocio un
                    JOIN public.usuarios u ON un.usuario_id = u.id
                    JOIN public.roles_negocio rn ON un.rol_id = rn.id
                    WHERE un.tenant_id = %s
                    ORDER BY rn.id, u.nombre_completo
                ''', (tenant_id,))
                rows = cur.fetchall()
                return [{'id': r[0], 'email': r[1], 'nombre': r[2], 'rol': r[3], 
                        'invitado_por': r[4], 'invitado_en': r[5]} for r in rows]
    
    def invitar_usuario(self, usuario_invitador_id: str, tenant_id: str, email_invitado: str, rol_nombre: str) -> dict:
        """Invita a un usuario existente a un negocio"""
        # Verificar que el invitador tiene permisos
        if not self.verificar_permiso(usuario_invitador_id, tenant_id, 'invitar_usuarios'):
            return {'success': False, 'error': 'No tienes permisos para invitar usuarios'}
        
        # Verificar que el rol existe
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM public.roles_negocio WHERE nombre = %s", (rol_nombre,))
                rol_row = cur.fetchone()
                if not rol_row:
                    return {'success': False, 'error': 'Rol no válido'}
                rol_id = rol_row[0]
        
        # Buscar al usuario invitado
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM public.usuarios WHERE email = %s", (email_invitado,))
                user_row = cur.fetchone()
                if not user_row:
                    return {'success': False, 'error': 'El usuario no existe. Debe registrarse primero.'}
                usuario_invitado_id = user_row[0]
        
        # Verificar si ya tiene acceso al negocio
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT id FROM public.usuario_negocio 
                    WHERE usuario_id = %s AND tenant_id = %s
                ''', (usuario_invitado_id, tenant_id))
                if cur.fetchone():
                    return {'success': False, 'error': 'El usuario ya tiene acceso a este negocio'}
        
        # Crear la relación
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO public.usuario_negocio (usuario_id, tenant_id, rol_id, invitado_por, invitacion_aceptada)
                    VALUES (%s, %s, %s, %s, true)
                ''', (usuario_invitado_id, tenant_id, rol_id, usuario_invitador_id))
            conn.commit()
        
        logger.info(f'Usuario {email_invitado} invitado al negocio {tenant_id} como {rol_nombre}')
        
        return {'success': True, 'message': f'Usuario invitado exitosamente como {rol_nombre}'}
    
    def remover_usuario(self, usuario_removedor_id: str, tenant_id: str, usuario_a_remover_id: str) -> dict:
        """Remueve un usuario de un negocio"""
        # Verificar permisos
        if not self.verificar_permiso(usuario_removedor_id, tenant_id, 'invitar_usuarios'):
            return {'success': False, 'error': 'No tienes permisos para remover usuarios'}
        
        # No permitir remover al owner si no es el mismo
        rol_removedor = self.get_rol_negocio(usuario_removedor_id, tenant_id)
        rol_a_remover = self.get_rol_negocio(usuario_a_remover_id, tenant_id)
        
        if rol_a_remover and rol_a_remover['rol'] == 'owner' and usuario_removedor_id != usuario_a_remover_id:
            return {'success': False, 'error': 'No puedes remover al propietario del negocio'}
        
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    DELETE FROM public.usuario_negocio 
                    WHERE usuario_id = %s AND tenant_id = %s
                ''', (usuario_a_remover_id, tenant_id))
            conn.commit()
        
        return {'success': True, 'message': 'Usuario removido exitosamente'}
    
    def cambiar_rol_usuario(self, usuario_actual_id: str, tenant_id: str, usuario_id: str, nuevo_rol: str) -> dict:
        """Cambia el rol de un usuario en un negocio"""
        # Verificar permisos
        if not self.verificar_permiso(usuario_actual_id, tenant_id, 'invitar_usuarios'):
            return {'success': False, 'error': 'No tienes permisos para cambiar roles'}
        
        # Verificar que el nuevo rol existe
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM public.roles_negocio WHERE nombre = %s", (nuevo_rol,))
                rol_row = cur.fetchone()
                if not rol_row:
                    return {'success': False, 'error': 'Rol no válido'}
                nuevo_rol_id = rol_row[0]
        
        # No permitir cambiar el rol del owner si no es él mismo
        rol_usuario = self.get_rol_negocio(usuario_id, tenant_id)
        if rol_usuario and rol_usuario['rol'] == 'owner' and usuario_actual_id != usuario_id:
            return {'success': False, 'error': 'No puedes cambiar el rol del propietario'}
        
        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    UPDATE public.usuario_negocio 
                    SET rol_id = %s
                    WHERE usuario_id = %s AND tenant_id = %s
                ''', (nuevo_rol_id, usuario_id, tenant_id))
            conn.commit()
        
        return {'success': True, 'message': f'Rol cambiado a {nuevo_rol}'}

# Instancia global
auth_manager = AuthManager()