import { showLoader, hideLoader, showAlert, escapeHtml, formatPrice, checkAuth } from './utils.js';
import { getNegociosUsuario, crearNegocio, verificarNegocio, logout } from './api.js';

// Estado
let currentUser = null;
let negocios = [];

// Elementos DOM
const userInfoEl = document.getElementById('userInfo');
const negociosContainer = document.getElementById('negociosContainer');
const totalNegociosEl = document.getElementById('totalNegocios');
const verificadosEl = document.getElementById('verificados');
const modalCrear = document.getElementById('modalCrear');
const formCrearNegocio = document.getElementById('formCrearNegocio');

// Inicializar
async function init() {
    showLoader();
    try {
        currentUser = await checkAuth();
        if (currentUser) {
            await cargarNegocios();
            actualizarUI();
        }
    } catch (error) {
        console.error('Error al iniciar:', error);
        showAlert('Error al cargar el dashboard', 'error');
    } finally {
        hideLoader();
    }
}

async function cargarNegocios() {
    try {
        negocios = await getNegociosUsuario();
        renderNegocios();
        
        if (totalNegociosEl) totalNegociosEl.innerText = negocios.length;
        if (verificadosEl) verificadosEl.innerText = negocios.filter(n => n.verificado).length;
    } catch (error) {
        console.error('Error cargando negocios:', error);
        if (negociosContainer) {
            negociosContainer.innerHTML = '<div class="alert alert-error">❌ Error al cargar los negocios</div>';
        }
    }
}

function renderNegocios() {
    if (!negociosContainer) return;
    
    if (negocios.length === 0) {
        negociosContainer.innerHTML = `
            <div class="card text-center">
                <p>📭 No tienes negocios registrados.</p>
                <button class="btn btn-primary" onclick="abrirModalCrear()">+ Crear mi primer negocio</button>
            </div>
        `;
        return;
    }
    
    negociosContainer.innerHTML = `
        <div class="negocios-grid">
            ${negocios.map(negocio => `
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">${escapeHtml(negocio.nombre)}</h3>
                        <span class="badge ${negocio.verificado ? 'badge-success' : 'badge-warning'}">
                            ${negocio.verificado ? '✅ Verificado' : '⚠️ Pendiente'}
                        </span>
                    </div>
                    <div class="card-body">
                        <p><strong>📞 Teléfono:</strong> ${negocio.phone_id || 'No configurado'}</p>
                        <div class="d-flex gap-2 mt-3">
                            <a href="/admin/menu?tenant_id=${negocio.id}" class="btn btn-sm">📋 Menú</a>
                            <a href="/panel/${negocio.id}" class="btn btn-sm btn-outline">📊 Panel</a>
                            ${!negocio.verificado ? `
                                <button class="btn btn-sm btn-primary" onclick="verificarNegocio('${negocio.id}')">🔐 Verificar</button>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function actualizarUI() {
    if (userInfoEl && currentUser) {
        userInfoEl.innerHTML = `
            <span>👤 ${escapeHtml(currentUser.nombre || currentUser.email)}</span>
            <button class="btn btn-sm btn-outline" onclick="cerrarSesion()">Salir</button>
        `;
    }
}

// Funciones globales para onclick
window.abrirModalCrear = function() {
    if (modalCrear) modalCrear.classList.add('active');
};

window.cerrarModalCrear = function() {
    if (modalCrear) modalCrear.classList.remove('active');
    if (formCrearNegocio) formCrearNegocio.reset();
};

window.verificarNegocio = async function(tenantId) {
    const codigo = prompt('Ingresa el código de verificación que recibiste por email:');
    if (!codigo) return;
    
    showLoader();
    try {
        const result = await verificarNegocio(tenantId, codigo);
        if (result.success) {
            showAlert('✅ Negocio verificado exitosamente', 'success');
            await cargarNegocios();
        } else {
            showAlert(result.error || 'Código incorrecto', 'error');
        }
    } catch (error) {
        showAlert('Error al verificar el negocio', 'error');
    } finally {
        hideLoader();
    }
};

window.cerrarSesion = async function() {
    await logout();
};

// Formulario crear negocio
if (formCrearNegocio) {
    formCrearNegocio.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const data = {
            nombre: document.getElementById('nombreNegocio').value,
            phone_id: document.getElementById('phoneId').value,
            token: document.getElementById('token').value,
            tipo_negocio: document.getElementById('tipoNegocio').value
        };
        
        const submitBtn = e.target.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Registrando...';
        showLoader();
        
        try {
            const result = await crearNegocio(data);
            if (result.success) {
                showAlert('✅ Negocio creado exitosamente. Revisa tu email para el código de verificación.', 'success');
                cerrarModalCrear();
                await cargarNegocios();
            } else {
                showAlert(result.error || 'Error al crear el negocio', 'error');
            }
        } catch (error) {
            showAlert('Error de conexión', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Registrar';
            hideLoader();
        }
    });
}

// Inicializar
document.addEventListener('DOMContentLoaded', init);