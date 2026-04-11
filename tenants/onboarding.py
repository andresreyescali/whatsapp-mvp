from flask import request, jsonify
from tenants.repository import tenant_repo
from tenants.schema_manager import schema_manager

def register_new_tenant():
    data = request.json
    required = ['nombre', 'phone_id', 'token']
    if not all(k in data for k in required):
        return jsonify({'error': 'Faltan campos requeridos'}), 400
    
    tenant = tenant_repo.create(
        nombre=data['nombre'],
        phone_id=data['phone_id'],
        token=data['token'],
        tipo_negocio=data.get('tipo_negocio', 'restaurante')
    )
    schema_manager.create_tenant_schema(tenant['id'], data.get('tipo_negocio', 'restaurante'))
    return jsonify({'status': 'ok', 'tenant_id': tenant['id']}), 201