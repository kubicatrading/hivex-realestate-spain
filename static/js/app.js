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

    // Fetch Opportunities from Backend API (Supports silent background updates)
    async function fetchOpportunities(isSilent = false) {
        try {
            if (!isSilent && state.allOpportunities.length === 0) {
                state.isLoading = true;
                dealsContainer.innerHTML = '<div style="padding: 20px; color: #94a3b8; text-align: center;">Cargando oportunidades del mercado...</div>';
            }

            const response = await fetch(`/api/v1/opportunities?min_discount=0.0`, {
                headers: { 'Authorization': `Bearer ${state.token}` }
            });

            if (response.status === 401) {
                logout();
                return;
            }

            if (!response.ok) throw new Error('Error al conectar con la API');

            const data = await response.json();
            const newOpps = data.opportunities || [];
            
            // Reconciliación silenciosa si ya existían datos en pantalla
            if (isSilent && state.allOpportunities.length > 0) {
                const oldIds = new Set(state.allOpportunities.map(o => o.id));
                const newIds = new Set(newOpps.map(o => o.id));

                const addedCount = newOpps.filter(o => !oldIds.has(o.id)).length;
                const removedCount = state.allOpportunities.filter(o => !newIds.has(o.id)).length;
                
                state.allOpportunities = newOpps;
                updateKPIs(newOpps);
                applyFilters();

                if (addedCount > 0) {
                    showToast(`✨ Se han incorporado ${addedCount} nueva(s) oportunidad(es) al mercado`, 'success');
                }
                if (removedCount > 0) {
                    showToast(`ℹ️ Se han retirado ${removedCount} oportunidad(es) que ya no están activas`, 'info');
                }
            } else {
                state.allOpportunities = newOpps;
                updateKPIs(newOpps);
                applyFilters();
            }

            state.isLoading = false;
        } catch (error) {
            console.error('Fetch error:', error);
            if (!isSilent) {
                dealsContainer.innerHTML = `<div style="padding: 20px; color: #ef4444; text-align: center;">Error al cargar datos: ${error.message}</div>`;
                showToast('Error al conectar con el servidor', 'error');
            }
            state.isLoading = false;
        }
    }

    // Configurar actualización silenciosa en segundo plano cada 15 minutos (900.000 ms)
    setInterval(() => {
        console.log("Ejecutando refresco silencioso programado cada 15 minutos...");
        fetchOpportunities(true);
    }, 15 * 60 * 1000);

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

    // Helper function to return original image or Cadastral parcel map image if no photo exists
    function getOpportunityMainImage(opp) {
        if (opp.images && opp.images.length > 0 && opp.images[0]) {
            return { url: opp.images[0], isMap: false };
        }
        if (opp.lat && opp.lon) {
            const d = 0.0018;
            const catastroWmsUrl = `https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx?SERVICE=WMS&SRS=EPSG:4326&REQUEST=GetMap&LAYERS=Catastro,PARCELA,ORTOFOTO&STYLES=default&FORMAT=image/png&TRANSPARENT=FALSE&BBOX=${opp.lon-d},${opp.lat-d},${opp.lon+d},${opp.lat+d}&WIDTH=600&HEIGHT=300`;
            return { url: catastroWmsUrl, isMap: true };
        }
        return { url: 'https://images.unsplash.com/photo-1560518883-ce09059eeffa?auto=format&fit=crop&w=800&q=80', isMap: false };
    }

    // Render Opportunity Cards Feed
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

        dealsContainer.innerHTML = opps.map((opp, idx) => {
            const isFlipping = opp.strategy === 'HOUSE_FLIPPING';
            const stratLabel = isFlipping ? 'House Flipping' : 'Suelo / Desarrollo';
            const stratClass = isFlipping ? 'strat-flipping' : 'strat-land';
            
            const imgInfo = getOpportunityMainImage(opp);
            const mainImg = imgInfo.url;
            const imgCount = opp.images ? opp.images.length : 0;
            const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality}, ${opp.province}`;

            // Metrics according to User Rules 5.1-5.4
            const refVal = opp.property_ref_value || opp.starting_bid || opp.appraisal_value || opp.listing_price || 0;
            const surfaceDisplay = (opp.surface_m2 && opp.surface_m2 > 0) ? `${opp.surface_m2} m²` : '<span style="color: #94a3b8; font-style: italic;">No consta</span>';
            const propertyM2Display = (opp.property_m2_price && opp.property_m2_price > 0) ? `${formatCurrency(opp.property_m2_price)}/m²` : '<span style="color: #94a3b8; font-style: italic;">-</span>';
            const areaM2Display = `${formatCurrency(opp.area_m2_price)}/m²*`;
            const typeLabel = isFlipping ? 'Inmueble' : 'Solar';

            const zoningActual = opp.urbanism?.zoning_classification || 'Suelo Urbano Consolidado (SUC)';
            const zoningFutura = opp.urbanism?.urbanization_status || 'Urbano Residencial / Ordenado';

            const urbanismHtml = `
                <div class="card-urbanism-compact" style="background: rgba(15, 23, 42, 0.4); padding: 8px 10px; border-radius: 6px; margin: 8px 0; border: 1px solid rgba(255, 255, 255, 0.05);">
                    <div style="font-size: 0.76rem; color: #38bdf8; font-weight: 600; display: flex; align-items: center; gap: 4px; margin-bottom: 4px;">
                        <i data-lucide="building-2" style="width: 12px; height: 12px;"></i> Calificación PGOU (Actual / Futura)
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.74rem; gap: 6px;">
                        <span style="color: #cbd5e1;" title="Calificación Actual">Actual: <strong>${escapeHtml(zoningActual)}</strong></span>
                        <span style="color: #fbbf24;" title="Calificación Futura / Planeamiento">Futura: <strong>${escapeHtml(zoningFutura)}</strong></span>
                    </div>
                </div>
            `;

            return `
                <div class="deal-card" data-opp-id="${opp.id}" data-opp-index="${idx}" onclick="highlightOpportunityPin(${opp.id}, ${opp.lat || 'null'}, ${opp.lon || 'null'})">
                    <div class="card-image-banner" style="background-image: url('${mainImg}');" onclick="openPropertyDetailModal(${idx}); event.stopPropagation();">
                        <div class="card-image-overlay">
                            <span class="badge-strategy ${stratClass}">${stratLabel}</span>
                            <span class="badge-discount">-${opp.discount_percentage.toFixed(0)}% BOE</span>
                        </div>
                        ${imgCount > 0 
                            ? `<span class="photo-count-badge"><i data-lucide="camera" style="width: 11px; height: 11px;"></i> ${imgCount} foto${imgCount > 1 ? 's' : ''}</span>` 
                            : `<span class="photo-count-badge map-badge"><i data-lucide="map-pin" style="width: 11px; height: 11px;"></i> Mapa Satélite</span>`
                        }
                    </div>

                    <div class="card-content-compact">
                        <h3 class="card-title" onclick="openPropertyDetailModal(${idx}); event.stopPropagation();" title="${escapeHtml(opp.title)}">${escapeHtml(opp.title)}</h3>
                        
                        <div class="card-location">
                            <a href="javascript:void(0)" class="address-maps-link" onclick="openGoogleMapsModal('${escapeHtml(fullAddress)}', ${opp.lat || 'null'}, ${opp.lon || 'null'}, event)" title="Ver en Google Maps Satélite">
                                <i data-lucide="map-pin" style="width: 12px; height: 12px;"></i> <span>${escapeHtml(fullAddress)}</span>
                                <span class="maps-badge">Google Maps</span>
                            </a>
                        </div>

                        ${urbanismHtml}

                        <div class="card-financials-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0;">
                            <div class="fin-cell">
                                <span class="fin-lbl">Valor Subasta / Ref.</span>
                                <span class="fin-val val-tasacion" style="font-size: 0.95rem; font-weight: 700;">${formatCurrency(refVal)}</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">Superficie Total</span>
                                <span class="fin-val" style="font-size: 0.95rem; color: #f8fafc; font-weight: 600;">${surfaceDisplay}</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">€/m² ${typeLabel}</span>
                                <span class="fin-val val-salida" style="font-size: 0.9rem; font-weight: 700;">${propertyM2Display}</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">€/m² Zona (${typeLabel})</span>
                                <span class="fin-val val-profit" style="font-size: 0.9rem; font-weight: 700;">${areaM2Display}</span>
                            </div>
                        </div>
                        <div style="font-size: 0.7rem; color: #94a3b8; font-style: italic; text-align: right; margin-top: -6px; margin-bottom: 8px;">
                            * Promedio de zona (${escapeHtml(opp.province || 'España')})
                        </div>

                        <div class="card-bottom-row">
                            <div class="scores-compact">
                                <span class="score-chip" title="Score Global">Score: <strong>${opp.overall_score}</strong></span>
                                <span class="score-chip poi" title="Servicios y Entorno POI">POI: <strong>${opp.poi_score}</strong></span>
                            </div>

                            <div class="card-actions-group">
                                <button class="btn btn-secondary btn-xs" onclick="openPropertyDetailModal(${idx}); event.stopPropagation();">
                                    <i data-lucide="eye" style="width: 12px; height: 12px;"></i> Ficha
                                </button>
                                <a href="${opp.boe_url}" target="_blank" rel="noopener" class="btn-boe-xs" onclick="event.stopPropagation();">
                                    BOE <i data-lucide="external-link" style="width: 11px; height: 11px;"></i>
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        if (window.lucide) lucide.createIcons();
    }

    // Attach global window function to open Property Detail Modal
    window.openPropertyDetailModal = function(index) {
        const opp = state.filteredOpportunities[index];
        if (!opp) return;

        const modal = document.getElementById('modal-property-detail');
        const body = document.getElementById('modal-prop-body');
        const images = (opp.images && opp.images.length > 0) ? opp.images : ['https://images.unsplash.com/photo-1560518883-ce09059eeffa?auto=format&fit=crop&w=800&q=80'];
        const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality}, ${opp.province}`;

        const surfaceDisplay = (opp.surface_m2 && opp.surface_m2 > 0) ? `${opp.surface_m2} m²` : 'No consta en BOE';
        const propertyM2Display = (opp.property_m2_price && opp.property_m2_price > 0) ? `${formatCurrency(opp.property_m2_price)}/m²` : '-';
        const areaM2Display = `${formatCurrency(opp.area_m2_price)}/m²*`;

        const urbanismDetail = `
            <div class="card-urbanism" style="margin-top: 16px; padding: 16px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;">
                <div class="urb-header" style="font-size: 0.9rem; font-weight: 600; color: #38bdf8; display: flex; align-items: center; gap: 6px;">
                    <i data-lucide="building-2"></i> Calificación del Terreno PGOU (Actual & Futura)
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px;">
                    <div>
                        <span class="meta-label" style="color: #94a3b8; font-size: 0.8rem;">Calificación Actual:</span>
                        <div class="meta-value" style="color: #f8fafc; font-weight: 600;">${escapeHtml(opp.urbanism?.zoning_classification || 'Suelo Urbano Consolidado (SUC-R)')}</div>
                    </div>
                    <div>
                        <span class="meta-label" style="color: #94a3b8; font-size: 0.8rem;">Calificación Futura / Ordenación:</span>
                        <div class="meta-value" style="color: #fbbf24; font-weight: 600;">${escapeHtml(opp.urbanism?.urbanization_status || 'Urbano Residencial / En trámite')}</div>
                    </div>
                    <div>
                        <span class="meta-label" style="color: #94a3b8; font-size: 0.8rem;">Edificabilidad / Coeficiente:</span>
                        <div class="meta-value">${escapeHtml(opp.urbanism?.buildability_ratio || '1.8 m²t/m²s')}</div>
                    </div>
                    <div>
                        <span class="meta-label" style="color: #94a3b8; font-size: 0.8rem;">Usos Permitidos:</span>
                        <div class="meta-value">${escapeHtml(opp.urbanism?.permitted_uses || 'Residencial / Comercial')}</div>
                    </div>
                </div>
            </div>
        `;

        body.innerHTML = `
            <div class="modal-prop-container">
                <div class="modal-gallery-main" id="prop-main-img" style="background-image: url('${images[0]}');"></div>
                ${images.length > 1 ? `
                    <div class="modal-gallery-thumbs">
                        ${images.map((img, i) => `
                            <img src="${img}" class="thumb-img ${i === 0 ? 'active' : ''}" onclick="changeModalMainImg('${img}', this)" alt="Foto ${i+1}">
                        `).join('')}
                    </div>
                ` : ''}

                <div class="modal-prop-header">
                    <h2>${escapeHtml(opp.title)}</h2>
                    <div class="modal-prop-address" style="margin-top: 8px;">
                        <a href="javascript:void(0)" class="address-maps-link" style="font-size: 0.92rem; padding: 6px 12px;" onclick="openGoogleMapsModal('${escapeHtml(fullAddress)}', ${opp.lat || 'null'}, ${opp.lon || 'null'}, event)">
                            <i data-lucide="map-pin"></i> ${escapeHtml(fullAddress)}
                            <span class="maps-badge"><i data-lucide="map"></i> Abrir Google Maps Satélite</span>
                        </a>
                    </div>
                </div>

                <div class="card-financials" style="padding: 16px; font-size: 0.95rem; display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;">
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">Valor de Tasación BOE</span>
                        <span class="fin-val ref" style="display: block; font-size: 1.1rem; font-weight: 700; margin-top: 2px;">${opp.appraisal_value > 0 ? formatCurrency(opp.appraisal_value) : '0 €'}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">Valor de Subasta</span>
                        <span class="fin-val price" style="display: block; font-size: 1.1rem; font-weight: 700; margin-top: 2px;">${opp.starting_bid > 0 ? formatCurrency(opp.starting_bid) : (opp.appraisal_value > 0 ? formatCurrency(opp.appraisal_value) : '0 €')}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">Valor Ref. Tomado</span>
                        <span class="fin-val ref" style="display: block; font-size: 1.1rem; color: #60a5fa; font-weight: 700; margin-top: 2px;">${formatCurrency(opp.property_ref_value || 0)}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">Superficie Ficha</span>
                        <span class="fin-val" style="display: block; font-size: 1.1rem; color: #f8fafc; font-weight: 600; margin-top: 2px;">${surfaceDisplay}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">Precio €/m² Inmueble</span>
                        <span class="fin-val price" style="display: block; font-size: 1.1rem; font-weight: 700; margin-top: 2px;">${propertyM2Display}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">Precio €/m² Zona</span>
                        <span class="fin-val profit" style="display: block; font-size: 1.1rem; font-weight: 700; margin-top: 2px;">${areaM2Display}</span>
                    </div>
                </div>
                <div style="font-size: 0.72rem; color: #94a3b8; font-style: italic; text-align: right; margin-top: -8px; margin-bottom: 12px; padding-right: 16px;">
                    * Promedio estimado de la zona (${escapeHtml(opp.province || 'España')})
                </div>

                <p style="color: var(--text-muted); font-size: 0.9rem; line-height: 1.5;">${escapeHtml(opp.description || '')}</p>

                ${urbanismDetail}

                <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--glass-border);">
                    <button class="btn btn-secondary" onclick="closePropertyDetailModal()">
                        <i data-lucide="x"></i> Cerrar Ventana
                    </button>
                    <a href="${opp.boe_url}" target="_blank" rel="noopener" class="btn btn-primary">
                        <i data-lucide="external-link"></i> Abrir Expediente Oficial en BOE
                    </a>
                </div>
            </div>
        `;

        if (window.lucide) lucide.createIcons();
        modal.classList.remove('hidden');
    };

    window.closePropertyDetailModal = function() {
        const modal = document.getElementById('modal-property-detail');
        if (modal) modal.classList.add('hidden');
    };

    window.openGoogleMapsModal = function(address, lat, lon, event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        const modal = document.getElementById('modal-google-maps');
        const addrSpan = document.getElementById('modal-gmaps-address');
        const linkExt = document.getElementById('link-gmaps-external');
        const iframe = document.getElementById('iframe-gmaps');

        let fullSearch = (address && address.trim() !== '') ? address.trim() : '';
        if (fullSearch && !fullSearch.toLowerCase().includes('españa') && !fullSearch.toLowerCase().includes('spain')) {
            fullSearch += ', España';
        }

        const query = fullSearch || (lat && lon ? `${lat},${lon}` : 'España');
        const encQuery = encodeURIComponent(query);

        addrSpan.textContent = address || query;

        // Embed Satellite Map URL
        window._gmapsMapUrl = `https://maps.google.com/maps?q=${encQuery}&t=k&z=18&ie=UTF8&iwloc=&output=embed`;

        if (iframe) iframe.src = window._gmapsMapUrl;
        if (linkExt) linkExt.href = `https://www.google.com/maps/search/?api=1&query=${encQuery}`;

        modal.classList.remove('hidden');
        if (window.lucide) lucide.createIcons();
    };

    window.switchGmapsTab = function(tab) {
        const iframe = document.getElementById('iframe-gmaps');
        const btnStreet = document.getElementById('tab-btn-streetview');
        const btnMap = document.getElementById('tab-btn-map');

        if (tab === 'streetview') {
            if (iframe) iframe.src = window._gmapsStreetUrl || window._gmapsMapUrl;
            if (btnStreet) { btnStreet.classList.add('active', 'btn-primary'); btnStreet.classList.remove('btn-secondary'); }
            if (btnMap) { btnMap.classList.remove('active', 'btn-primary'); btnMap.classList.add('btn-secondary'); }
        } else {
            if (iframe) iframe.src = window._gmapsMapUrl;
            if (btnMap) { btnMap.classList.add('active', 'btn-primary'); btnMap.classList.remove('btn-secondary'); }
            if (btnStreet) { btnStreet.classList.remove('active', 'btn-primary'); btnStreet.classList.add('btn-secondary'); }
        }
    };

    window.closeGoogleMapsModal = function() {
        const modal = document.getElementById('modal-google-maps');
        const iframe = document.getElementById('iframe-gmaps');
        if (iframe) iframe.src = '';
        if (modal) modal.classList.add('hidden');
    };

    window.changeModalMainImg = function(url, el) {
        document.getElementById('prop-main-img').style.backgroundImage = `url('${url}')`;
        document.querySelectorAll('.thumb-img').forEach(t => t.classList.remove('active'));
        if (el) el.classList.add('active');
    };

    let markersMap = {};

    window.highlightOpportunityPin = function(oppId, lat, lon) {
        document.querySelectorAll('.deal-card').forEach(c => c.classList.remove('card-highlight'));
        const cardEl = document.querySelector(`.deal-card[data-opp-id="${oppId}"]`);
        if (cardEl) cardEl.classList.add('card-highlight');

        const marker = markersMap[oppId];
        if (marker && map) {
            if (lat && lon) {
                map.flyTo([lat, lon], 15, { duration: 0.8 });
            }
            marker.openPopup();

            if (marker._icon) {
                document.querySelectorAll('.custom-map-pin').forEach(p => p.classList.remove('pin-pulse-highlight'));
                const pinDiv = marker._icon.querySelector('div');
                if (pinDiv) {
                    pinDiv.classList.add('pin-pulse-highlight');
                    setTimeout(() => pinDiv.classList.remove('pin-pulse-highlight'), 3500);
                }
            }
        }
    };

    // Modal Close Button Event Listeners
    const modalPropClose = document.getElementById('modal-prop-close');
    if (modalPropClose) {
        modalPropClose.addEventListener('click', closePropertyDetailModal);
    }

    const modalGmapsClose = document.getElementById('modal-gmaps-close');
    if (modalGmapsClose) {
        modalGmapsClose.addEventListener('click', closeGoogleMapsModal);
    }

    const btnGmapsBottomClose = document.getElementById('btn-gmaps-bottom-close');
    if (btnGmapsBottomClose) {
        btnGmapsBottomClose.addEventListener('click', closeGoogleMapsModal);
    }

    // Backdrop & Escape key handler to close active modals
    document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
        backdrop.addEventListener('click', (e) => {
            if (e.target === backdrop) {
                backdrop.classList.add('hidden');
                const iframe = backdrop.querySelector('iframe');
                if (iframe) iframe.src = '';
            }
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-backdrop').forEach(b => {
                b.classList.add('hidden');
                const iframe = b.querySelector('iframe');
                if (iframe) iframe.src = '';
            });
        }
    });

    // Render Pins on Map with Interactivity
    function renderMapMarkers(opps) {
        if (!mapMarkersLayer) return;
        mapMarkersLayer.clearLayers();
        markersMap = {};
        const bounds = [];

        opps.forEach((opp, idx) => {
            if (opp.lat && opp.lon) {
                const color = opp.strategy === 'HOUSE_FLIPPING' ? '#ef4444' : '#f59e0b';
                const imgInfo = getOpportunityMainImage(opp);
                const mainImg = imgInfo.url;
                const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality}`;

                const customIcon = L.divIcon({
                    className: 'custom-map-pin',
                    html: `<div style="background-color: ${color}; width: 18px; height: 18px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 10px ${color}; cursor: pointer;"></div>`,
                    iconSize: [18, 18]
                });

                const marker = L.marker([opp.lat, opp.lon], { icon: customIcon });
                markersMap[opp.id] = marker;

                marker.bindPopup(`
                    <div style="font-family: sans-serif; color: #1e293b; max-width: 250px; padding: 4px;">
                        <img src="${mainImg}" style="width: 100%; height: 110px; object-fit: cover; border-radius: 6px; margin-bottom: 8px; border: 1px solid #cbd5e1;">
                        <strong style="font-size: 13px; display: block; margin-bottom: 4px; color: #0f172a; line-height: 1.2;">${escapeHtml(opp.title)}</strong>
                        <span style="color: #64748b; font-size: 11px; display: block; margin-bottom: 6px;">📍 ${escapeHtml(fullAddress)}</span>
                        <div style="margin-bottom: 4px; font-size: 11px; color: #475569;">
                            <strong>Tasación BOE:</strong> ${formatCurrency(opp.estimated_reference_value)}
                        </div>
                        <div style="margin-bottom: 10px; font-weight: 700; color: #059669; font-size: 12px;">
                            -${opp.discount_percentage.toFixed(0)}% Descuento | Salida: ${formatCurrency(opp.listing_price)}
                        </div>
                        <button onclick="openPropertyDetailModal(${idx})" style="width: 100%; padding: 7px 12px; background: #2563eb; color: #ffffff; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; box-shadow: 0 2px 4px rgba(37,99,235,0.3);">
                            🔍 Ver Ficha Completa
                        </button>
                    </div>
                `);

                // Al pulsar la chincheta: resaltar tarjeta en el panel y hacer scroll
                marker.on('click', () => {
                    document.querySelectorAll('.deal-card').forEach(c => c.classList.remove('card-highlight'));
                    const cardEl = document.querySelector(`.deal-card[data-opp-id="${opp.id}"]`);
                    if (cardEl) {
                        cardEl.classList.add('card-highlight');
                        cardEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                });

                mapMarkersLayer.addLayer(marker);
                bounds.push([opp.lat, opp.lon]);
            }
        });

        if (bounds.length > 0 && map) {
            map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
        }
    }

    // Trigger Ingestion Pipeline (Silent non-blocking execution)
    btnRunPipeline.addEventListener('click', async () => {
        try {
            btnRunPipeline.disabled = true;
            document.getElementById('text-run').textContent = 'Escaneando...';

            showToast('🔍 Escáner activado. Rastreando el BOE en segundo plano sin interrumpir la pantalla...', 'info');

            // 1. Lanzar la captura en segundo plano en el servidor
            const res = await fetch('/api/v1/pipeline/run', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${state.token}` }
            });

            if (res.status === 401) {
                logout();
                return;
            }

            if (!res.ok) throw new Error('Falló la activación del escáner');

            // 2. Ejecutar lectura silenciosa inmediata sin alterar los resultados cargados
            await fetchOpportunities(true);

            // 3. Consultas de reconciliación silenciosa progresivas a los 4s, 10s y 18s
            setTimeout(() => fetchOpportunities(true), 4000);
            setTimeout(() => fetchOpportunities(true), 10000);
            setTimeout(() => {
                fetchOpportunities(true);
                btnRunPipeline.disabled = false;
                document.getElementById('text-run').textContent = 'Ejecutar Escáner';
            }, 18000);

        } catch (err) {
            showToast(`Error activando escáner: ${err.message}`, 'error');
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
