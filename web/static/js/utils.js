// ==================== UTILIDADES GLOBALES ====================

// Mostrar/ocultar loader
export function showLoader() {
    let loader = document.getElementById('globalLoader');
    if (!loader) {
        loader = document.createElement('div');
        loader.id = 'globalLoader';
        loader.className = 'loader-overlay';
        loader.innerHTML = '<div class="loader"></div>';
        document.body.appendChild(loader);
    }
    loader.classList.add('active');
}

export function hideLoader() {
    const loader = document.getElementById('globalLoader');
    if (loader) loader.classList.remove('active');
}

// Mostrar alertas
export function showAlert(message, type = 'info') {
    const container = document.getElementById('alertContainer');
    if (!container) return;
    
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;
    alertDiv.innerHTML = `
        <span>${message}</span>
        <button style="margin-left:auto;background:none;border:none;cursor:pointer;" onclick="this.parentElement.remove()">✕</button>
    `;
    container.appendChild(alertDiv);
    
    setTimeout(() => alertDiv.remove(), 5000);
}

// Escape HTML
export function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Formatear precio
export function formatPrice(price) {
    return new Intl.NumberFormat('es-CO', {
        style: 'currency',
        currency: 'COP',
        minimumFractionDigits: 0
    }).format(price);
}

// Formatear fecha
export function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('es-CO', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Obtener tenant_id de la URL
export function getTenantIdFromUrl() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('tenant_id');
}

// Verificar autenticación
export async function checkAuth() {
    try {
        const response = await fetch('/api/usuario/perfil', {
            credentials: 'include'
        });
        if (!response.ok) {
            window.location.href = '/';
            return false;
        }
        const user = await response.json();
        return user;
    } catch (error) {
        window.location.href = '/';
        return false;
    }
}