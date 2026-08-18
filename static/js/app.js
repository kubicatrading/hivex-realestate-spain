/**
 * HIVEX Real Estate Spain - Single Page Dashboard Logic with JWT Auth & Data Monitor
 */

document.addEventListener('DOMContentLoaded', () => {
    // Initialize Lucide Icons
    if (window.lucide) {
        lucide.createIcons();
    }

    // App State
    let state = {
        token: localStorage.getItem('hivex_token') || null,
        user: null,
        allOpportunities: [],
        filteredOpportunities: [],
        sourcesData: [],
        activeTab: 'deals',
        currentStrategy: 'ALL',
        minDiscount: 0.10,
        searchQuery: '',
        isLoading: false
    };

    // DOM Elements - Login
    const loginOverlay = document.getElementById('login-overlay');
    const formLogin = document.getElementById('form-login');
    const inputLogin = document.getElementById('input-login');
    const inputPassword = document.getElementById('input-password');
    const loginError = document.getElementById('login-error');
    const btnLoginSubmit = document.getElementById('btn-login-submit');

    // DOM Elements - Navigation & Views
    const dashboardApp = document.getElementById('dashboard-app');
    const btnLogout = document.getElementById('btn-logout');
    const tabButtons = document.querySelectorAll('.tab-btn');
    const viewDeals = document.getElementById('view-deals');
    const viewSources = document.getElementById('view-sources');

    // DOM Elements - Deals View
    const dealsContainer = document.getElementById('deals-container');
    const filteredCount = document.getElementById('filtered-count');
    const selectDiscount = document.getElementById('select-discount');
    const inputSearch = document.getElementById('input-search');
    const stratButtons = document.querySelectorAll('.strat-btn');
    const btnRunPipeline = document.getElementById('btn-run-pipeline');
    
    // DOM Elements - Sources Monitor View
    const sourcesGrid = document.getElementById('sources-grid');
    const btnRefreshSources = document.getElementById('btn-refresh-sources');
    const modalSample = document.getElementById('modal-sample');
    const modalSampleClose = document.getElementById('modal-sample-close');
    const modalSourceName = document.getElementById('modal-source-name');
    const jsonViewerCode = document.getElementById('json-viewer-code');

    // KPI Elements
    const kpiScanned = document.getElementById('kpi-total-scanned');
    const kpiActive = document.getElementById('kpi-active-deals');
    const kpiAvgDiscount = document.getElementById('kpi-avg-discount');
    const kpiTotalProfit = document.getElementById('kpi-total-profit');

    // Initialize Leaflet Map
    let map = null;
    let mapMarkersLayer = null;

    function initMap() {
        if (!map) {
            map = L.map('map').setView([40.4168, -3.7038], 6); // Centered on Madrid / Spain
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
                subdomains: 'abcd',
                maxZoom: 19
            }).addTo(map);

            mapMarkersLayer = L.layerGroup().addTo(map);
        }
    }

    // Authentication Checks
    async function checkAuthSession() {
        if (!state.token) {
            showLoginOverlay();
            return;
        }

        try {
            const res = await fetch('/api/v1/auth/me', {
                headers: { 'Authorization': `Bearer ${state.token}` }
            });

            if (res.ok) {
                const data = await res.json();
                state.user = data.user;
                showDashboard();
            } else {
                logout();
            }
        } catch (e) {
            logout();
        }
    }

    // Login Form Submit Handler
    formLogin.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginError.classList.add('hidden');
        btnLoginSubmit.disabled = true;
        btnLoginSubmit.innerHTML = 'Verificando...';

        const loginVal = inputLogin.value.trim();
        const passVal = inputPassword.value;

        try {
            const res = await fetch('/api/v1/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ login: loginVal, password: passVal })
            });

            const data = await res.json();

            if (res.ok && data.access_token) {
                state.token = data.access_token;
                state.user = data.user;
                localStorage.setItem('hivex_token', data.access_token);
                showDashboard();
                showToast(`¡Bienvenido ${data.user.username}!`, 'success');
            } else {
                loginError.textContent = data.detail || 'Error de autenticación';
                loginError.classList.remove('hidden');
            }
        } catch (err) {
            loginError.textContent = 'Error de conexión con el servidor.';
            loginError.classList.remove('hidden');
        } finally {
            btnLoginSubmit.disabled = false;
            btnLoginSubmit.innerHTML = '<i data-lucide="log-in"></i> Acceder a la Plataforma';
            if (window.lucide) lucide.createIcons();
        }
    });

    // Logout Handler
    function logout() {
        state.token = null;
        state.user = null;
        localStorage.removeItem('hivex_token');
        showLoginOverlay();
    }

    btnLogout.addEventListener('click', logout);

    function showLoginOverlay() {
        loginOverlay.classList.remove('hidden');
        dashboardApp.classList.add('hidden');
    }

    function showDashboard() {
        loginOverlay.classList.add('hidden');
        dashboardApp.classList.remove('hidden');
        setTimeout(() => {
            initMap();
            map.invalidateSize();
            fetchOpportunities();
        }, 100);
    }

    // Tab Navigation Switcher
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const targetTab = btn.dataset.tab;
            state.activeTab = targetTab;

            if (targetTab === 'deals') {
                viewDeals.classList.remove('hidden');
                viewSources.classList.add('hidden');
                setTimeout(() => { if (map) map.invalidateSize(); }, 100);
            } else if (targetTab === 'sources') {
                viewDeals.classList.add('hidden');
                viewSources.classList.remove('hidden');
                fetchSourcesStatus();
            }
        });
    });

    // Fetch Opportunities from Backend API
    async function fetchOpportunities() {
        try {
            state.isLoading = true;
            dealsContainer.innerHTML = '<div style="padding: 20px; color: #94a3b8; text-align: center;">Cargando oportunidades del mercado...</div>';

            const response = await fetch(`/api/v1/opportunities?min_discount=0.0`, {
                headers: { 'Authorization': `Bearer ${state.token}` }
            });

            if (response.status === 401) {
                logout();
                return;
            }

            if (!response.ok) throw new Error('Error al conectar con la API');

            const data = await response.json();
            state.allOpportunities = data.opportunities || [];
            
            updateKPIs(data.opportunities || []);
            applyFilters();
            state.isLoading = false;
        } catch (error) {
            console.error('Fetch error:', error);
            dealsContainer.innerHTML = `<div style="padding: 20px; color: #ef4444; text-align: center;">Error al cargar datos: ${error.message}</div>`;
            showToast('Error al conectar con el servidor', 'error');
            state.isLoading = false;
        }
    }

    // Fetch Data Sources Health Status & Real Sample Payloads
    async function fetchSourcesStatus() {
        try {
            sourcesGrid.innerHTML = '<div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: #94a3b8;">Verificando estado de conectividad con portales web...</div>';

            const response = await fetch('/api/v1/sources/status', {
                headers: { 'Authorization': `Bearer ${state.token}` }
            });

            if (response.status === 401) {
                logout();
                return;
            }

            if (!response.ok) throw new Error('Error consultando el monitor de fuentes');

            const data = await response.json();
            state.sourcesData = data.sources || [];
            renderSourcesMonitor(data.sources || []);
        } catch (err) {
            sourcesGrid.innerHTML = `<div style="grid-column: 1 / -1; padding: 30px; color: #ef4444; text-align: center;">Error al consultar el monitor de fuentes: ${err.message}</div>`;
        }
    }

    btnRefreshSources.addEventListener('click', fetchSourcesStatus);

    // Render Data Sources Cards
    function renderSourcesMonitor(sources) {
        if (sources.length === 0) {
            sourcesGrid.innerHTML = '<div style="grid-column: 1 / -1; color: #94a3b8;">No hay datos de fuentes disponibles.</div>';
            return;
        }

        sourcesGrid.innerHTML = sources.map(src => {
            const isOp = src.status === 'OPERATIONAL';
            const badgeClass = isOp ? 'badge-operational' : 'badge-error';
            const statusText = isOp ? '🟢 Operativo (200 OK)' : '🔴 Error de Conexión';

            return `
                <div class="source-card">
                    <div class="source-header">
                        <div class="source-title">
                            <h3>${escapeHtml(src.name)}</h3>
                            <a href="${src.url}" target="_blank" rel="noopener">
                                ${escapeHtml(src.url)} <i data-lucide="external-link" style="width: 12px; height: 12px;"></i>
                            </a>
                        </div>
                        <span class="badge-status ${badgeClass}">${statusText}</span>
                    </div>

                    <div class="source-meta">
                        <div class="meta-item">
                            <span class="meta-label">Método de Acceso</span>
                            <span class="meta-value">${escapeHtml(src.method)}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Latencia de Red</span>
                            <span class="meta-value latency">${src.latency_ms} ms</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Muestreo Reciente</span>
                            <span class="meta-value">${escapeHtml(src.last_synced)}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Registros Procesados</span>
                            <span class="meta-value">${src.records_count} elementos</span>
                        </div>
                    </div>

                    <button class="btn-inspect" data-source-id="${src.id}">
                        <i data-lucide="code"></i> Ver Muestra de Datos Reales
                    </button>
                </div>
            `;
        }).join('');

        if (window.lucide) lucide.createIcons();

        // Attach event listeners for inspect buttons
        document.querySelectorAll('.btn-inspect').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const sourceId = btn.dataset.sourceId;
                const srcObj = state.sourcesData.find(s => s.id === sourceId);
                if (srcObj) {
                    openSampleModal(srcObj);
                }
            });
        });
    }

    // Open Modal for Raw JSON Payload
    function openSampleModal(srcObj) {
        modalSourceName.textContent = `${srcObj.name} (${srcObj.method})`;
        jsonViewerCode.textContent = JSON.stringify(srcObj.sample_data, null, 2);
        modalSample.classList.remove('hidden');
    }

    modalSampleClose.addEventListener('click', () => {
        modalSample.classList.add('hidden');
    });

    // Calculate & Update Header KPIs
    function updateKPIs(opps) {
        const totalCount = opps.length;
        const activeCount = opps.filter(o => (o.discount_percentage / 100) >= 0.10).length;
        
        let avgDisc = 0;
        let totalProfit = 0;

        if (opps.length > 0) {
            const sumDisc = opps.reduce((acc, curr) => acc + curr.discount_percentage, 0);
            avgDisc = sumDisc / opps.length;
            totalProfit = opps.reduce((acc, curr) => acc + (curr.potential_gross_profit || 0), 0);
        }

        kpiScanned.textContent = totalCount;
        kpiActive.textContent = activeCount;
        kpiAvgDiscount.textContent = `${avgDisc.toFixed(1)}%`;
        kpiTotalProfit.textContent = formatCurrency(totalProfit);
    }

    // Apply Filter Logic
    function applyFilters() {
        state.filteredOpportunities = state.allOpportunities.filter(opp => {
            // Strategy Filter
            if (state.currentStrategy !== 'ALL' && opp.strategy !== state.currentStrategy) {
                return false;
            }
            // Discount Filter
            const discDecimal = opp.discount_percentage / 100;
            if (discDecimal < state.minDiscount) {
                return false;
            }
            // Search Query Filter
            if (state.searchQuery.trim() !== '') {
                const q = state.searchQuery.toLowerCase();
                const title = (opp.title || '').toLowerCase();
                const prov = (opp.province || '').toLowerCase();
                const loc = (opp.locality || '').toLowerCase();
                if (!title.includes(q) && !prov.includes(q) && !loc.includes(q)) {
                    return false;
                }
            }
            return true;
        });

        filteredCount.textContent = `Mostrando ${state.filteredOpportunities.length} de ${state.allOpportunities.length} oportunidades`;
        renderDeals(state.filteredOpportunities);
        renderMapMarkers(state.filteredOpportunities);
    }

    // Render Cards Grid
    function renderDeals(opps) {
        if (opps.length === 0) {
            dealsContainer.innerHTML = `
                <div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: #64748b; background: rgba(0,0,0,0.2); border-radius: 12px;">
                    <i data-lucide="inbox" style="width: 32px; height: 32px; margin-bottom: 8px;"></i>
                    <p>No se encontraron oportunidades con los filtros seleccionados.</p>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        dealsContainer.innerHTML = opps.map(opp => {
            const isFlipping = opp.strategy === 'HOUSE_FLIPPING';
            const stratLabel = isFlipping ? 'House Flipping' : 'Suelo / Desarrollo';
            const stratClass = isFlipping ? 'strat-flipping' : 'strat-land';

            return `
                <div class="deal-card">
                    <div class="card-top">
                        <span class="badge-strategy ${stratClass}">${stratLabel}</span>
                        <span class="badge-discount">-${opp.discount_percentage.toFixed(0)}%</span>
                    </div>

                    <h3 class="card-title">${escapeHtml(opp.title)}</h3>
                    <div class="card-location">
                        <i data-lucide="map-pin" style="width: 14px; height: 14px;"></i>
                        ${escapeHtml(opp.locality)}, ${escapeHtml(opp.province)}
                    </div>

                    <div class="card-financials">
                        <div class="fin-item">
                            <span class="fin-label">Precio Subasta</span>
                            <span class="fin-val price">${formatCurrency(opp.listing_price)}</span>
                        </div>
                        <div class="fin-item">
                            <span class="fin-label">Valor Referencia</span>
                            <span class="fin-val ref">${formatCurrency(opp.estimated_reference_value)}</span>
                        </div>
                        <div class="fin-item">
                            <span class="fin-label">Beneficio Bruto</span>
                            <span class="fin-val profit">+${formatCurrency(opp.potential_gross_profit)}</span>
                        </div>
                    </div>

                    <div class="card-scores">
                        <div class="score-pill">
                            <span>Score Global:</span>
                            <strong>${opp.overall_score}/100</strong>
                        </div>
                        <div class="score-pill">
                            <span>Score POI:</span>
                            <strong>${opp.poi_score}/100</strong>
                        </div>
                    </div>

                    <div class="card-footer">
                        <a href="${opp.boe_url}" target="_blank" rel="noopener" class="btn-boe">
                            Ver en BOE <i data-lucide="external-link" style="width: 12px; height: 14px;"></i>
                        </a>
                    </div>
                </div>
            `;
        }).join('');

        if (window.lucide) lucide.createIcons();
    }

    // Render Pins on Map
    function renderMapMarkers(opps) {
        if (!mapMarkersLayer) return;
        mapMarkersLayer.clearLayers();
        const bounds = [];

        opps.forEach(opp => {
            if (opp.lat && opp.lon) {
                const color = opp.strategy === 'HOUSE_FLIPPING' ? '#ef4444' : '#f59e0b';
                
                const customIcon = L.divIcon({
                    className: 'custom-map-pin',
                    html: `<div style="background-color: ${color}; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 10px ${color};"></div>`,
                    iconSize: [14, 14]
                });

                const marker = L.marker([opp.lat, opp.lon], { icon: customIcon });
                marker.bindPopup(`
                    <div style="font-family: sans-serif; color: #1e293b;">
                        <strong style="font-size: 14px;">${escapeHtml(opp.title)}</strong><br>
                        <span style="color: #64748b; font-size: 12px;">${escapeHtml(opp.locality)}, ${escapeHtml(opp.province)}</span><br>
                        <div style="margin-top: 6px; font-weight: bold; color: #10b981;">
                            -${opp.discount_percentage.toFixed(0)}% Descuento | ${formatCurrency(opp.listing_price)}
                        </div>
                    </div>
                `);

                mapMarkersLayer.addLayer(marker);
                bounds.push([opp.lat, opp.lon]);
            }
        });

        if (bounds.length > 0 && map) {
            map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
        }
    }

    // Trigger Ingestion Pipeline
    btnRunPipeline.addEventListener('click', async () => {
        if (state.isLoading) return;
        
        try {
            state.isLoading = true;
            btnRunPipeline.disabled = true;
            document.getElementById('text-run').textContent = 'Escaneando...';

            showToast('Lanzando captura de subastas en vivo...', 'info');

            const res = await fetch('/api/v1/pipeline/run', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${state.token}` }
            });

            if (res.status === 401) {
                logout();
                return;
            }

            if (!res.ok) throw new Error('Falló la ejecución de la captura');

            const result = await res.json();
            showToast(`¡Escáner completado! Subastas procesadas: ${result.processed_auctions}`, 'success');

            await fetchOpportunities();
        } catch (err) {
            showToast(`Error ejecutando escáner: ${err.message}`, 'error');
        } finally {
            state.isLoading = false;
            btnRunPipeline.disabled = false;
            document.getElementById('text-run').textContent = 'Ejecutar Escáner';
        }
    });

    // Strategy Button Selection
    stratButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            stratButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentStrategy = btn.dataset.strategy;
            applyFilters();
        });
    });

    // Discount Selector Event
    selectDiscount.addEventListener('change', (e) => {
        state.minDiscount = parseFloat(e.target.value);
        applyFilters();
    });

    // Search Input Event
    inputSearch.addEventListener('input', (e) => {
        state.searchQuery = e.target.value;
        applyFilters();
    });

    // Utility Functions
    function formatCurrency(val) {
        return new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(val || 0);
    }

    function escapeHtml(str) {
        return (str || '').replace(/[&<>"']/g, function(m) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m];
        });
    }

    function showToast(message, type = 'info') {
        const toastContainer = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.innerHTML = `<i data-lucide="info" style="width: 18px; height: 18px;"></i> <span>${message}</span>`;
        toastContainer.appendChild(toast);
        if (window.lucide) lucide.createIcons();

        setTimeout(() => {
            toast.remove();
        }, 4000);
    }

    // Initial Auth Check
    checkAuthSession();
});
