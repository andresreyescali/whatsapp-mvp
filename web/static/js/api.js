import { showAlert, getTenantIdFromUrl } from './utils.js';

const API_BASE = window.location.origin;

// Autenticación
export async function login(email, password) {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include'
    });
    return response.json();
}

export async function register(email, password, nombre, telefono) {
    const response = await fetch(`${API_BASE}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, nombre_completo: nombre, telefono }),
        credentials: 'include'
    });
    return response.json();
}

export async function logout() {
    await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', credentials: 'include' });
    window.location.href = '/';
}

// Negocios
export async function getNegociosUsuario() {
    const response = await fetch(`${API_BASE}/api/negocios/usuario`, {
        credentials: 'include'
    });
    if (!response.ok) throw new Error('Error al cargar negocios');
    return response.json();
}

export async function crearNegocio(data) {
    const response = await fetch(`${API_BASE}/api/negocio/registrar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'include'
    });
    return response.json();
}

export async function verificarNegocio(tenantId, codigo) {
    const response = await fetch(`${API_BASE}/api/negocio/verificar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId, codigo }),
        credentials: 'include'
    });
    return response.json();
}

// Menú / Productos
export async function getMenu(tenantId) {
    const response = await fetch(`${API_BASE}/api/tenant/${tenantId}/menu`, {
        credentials: 'include'
    });
    if (!response.ok) throw new Error('Error al cargar menú');
    return response.json();
}

export async function addProducto(tenantId, producto) {
    const response = await fetch(`${API_BASE}/admin/add_product/${tenantId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(producto),
        credentials: 'include'
    });
    return response.json();
}

export async function updateProducto(tenantId, productId, producto) {
    const response = await fetch(`${API_BASE}/admin/update_product/${tenantId}/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(producto),
        credentials: 'include'
    });
    return response.json();
}

export async function deleteProducto(tenantId, productId) {
    const response = await fetch(`${API_BASE}/admin/delete_product/${tenantId}/${productId}`, {
        method: 'DELETE',
        credentials: 'include'
    });
    return response.json();
}

export async function toggleProducto(tenantId, productId, disponible) {
    const response = await fetch(`${API_BASE}/admin/toggle_product/${tenantId}/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ disponible }),
        credentials: 'include'
    });
    return response.json();
}

// Configuración
export async function getConfig(tenantId) {
    const response = await fetch(`${API_BASE}/api/tenant/${tenantId}/config`, {
        credentials: 'include'
    });
    return response.json();
}

export async function updateConfigIA(tenantId, usarIa) {
    const response = await fetch(`${API_BASE}/api/tenant/${tenantId}/config/ia`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ usar_ia: usarIa }),
        credentials: 'include'
    });
    return response.json();
}

// Entrenamiento IA
export async function entrenarIA(tenantId, tipo, texto, imagen) {
    const data = tipo === 'imagen' ? { tipo, imagen } : { tipo, texto };
    const response = await fetch(`${API_BASE}/admin/train/${tenantId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'include'
    });
    return response.json();
}

// Permisos
export async function getPermisos(tenantId) {
    const response = await fetch(`${API_BASE}/api/negocio/${tenantId}/permisos`, {
        credentials: 'include'
    });
    return response.json();
}