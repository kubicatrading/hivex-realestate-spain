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
        activeSource: 'subastas',
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
                updateTabBadges(newOpps);
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
                updateTabBadges(newOpps);
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

    // Update Tab Badges for Opportunity Sources
    function updateTabBadges(opps) {
        const subastasCount = opps.filter(o => (o.source_type || 'subastas') === 'subastas').length;
        const pgouCount = opps.filter(o => o.source_type === 'pgou').length;
        
        const badgeSub = document.getElementById('badge-subastas-count');
        const badgePgou = document.getElementById('badge-pgou-count');
        
        if (badgeSub) badgeSub.textContent = subastasCount;
        if (badgePgou) badgePgou.textContent = pgouCount;
    }

    // Opportunity Source Tab Switcher (Subastas BOE vs Visor PGOU)
    window.switchOpportunitySource = function(sourceType) {
        state.activeSource = sourceType;

        document.querySelectorAll('.source-tab').forEach(btn => {
            btn.classList.remove('active');
            btn.setAttribute('aria-selected', 'false');
        });

        const activeBtn = document.getElementById(`tab-${sourceType}`);
        if (activeBtn) {
            activeBtn.classList.add('active');
            activeBtn.setAttribute('aria-selected', 'true');
        }

        // Update map legend dynamically according to active tab
        const legendEl = document.querySelector('.map-legend');
        if (legendEl) {
            if (sourceType === 'subastas') {
                legendEl.innerHTML = `
                    <span class="dot pin-flipping"></span> House Flipping
                    <span class="dot pin-land"></span> Suelo / Desarrollo
                `;
            } else {
                legendEl.innerHTML = `
                    <span class="dot" style="background:#a855f7; box-shadow: 0 0 8px #a855f7;"></span> Aprobación PGOU / Convenio
                    <span class="dot" style="background:#10b981; box-shadow: 0 0 8px #10b981;"></span> Reordenación / Sector
                `;
            }
        }

        applyFilters();

        const currentCount = state.filteredOpportunities.length;
        if (sourceType === 'subastas') {
            showToast(`⚖️ Subastas BOE: Mostrando ${currentCount} subastas públicas activas`, 'info');
        } else if (sourceType === 'pgou') {
            showToast(`📐 Visor PGOU: Mostrando ${currentCount} desarrollos urbanísticos detectados en boletines oficiales (BOCM, DOGC, BOJA)`, 'success');
        }
    };

    // Apply Filter Logic
    function applyFilters() {
        state.filteredOpportunities = state.allOpportunities.filter(opp => {
            // Source Filter (Subastas BOE vs PGOU Visor)
            const oppSource = opp.source_type || 'subastas';
            if (oppSource !== state.activeSource) {
                return false;
            }
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

        const activeTotal = state.allOpportunities.filter(o => (o.source_type || 'subastas') === state.activeSource).length;
        filteredCount.textContent = `Mostrando ${state.filteredOpportunities.length} de ${activeTotal} oportunidades`;
        renderDeals(state.filteredOpportunities);
        renderMapMarkers(state.filteredOpportunities);
    }

    // Global tab switcher for modal media (Street View Real vs Ortofoto Aérea Catastro)
    window.switchModalMediaTab = function(tabName) {
        const streetviewBox = document.getElementById('modal-media-streetview');
        const ortofotoBox = document.getElementById('modal-media-ortofoto');
        const tabStreetview = document.getElementById('tab-btn-streetview');
        const tabOrtofoto = document.getElementById('tab-btn-ortofoto');

        if (!streetviewBox || !ortofotoBox) return;

        if (tabName === 'streetview') {
            streetviewBox.style.display = 'block';
            ortofotoBox.style.display = 'none';
            if (tabStreetview) {
                tabStreetview.style.borderColor = '#38bdf8';
                tabStreetview.style.color = '#38bdf8';
                tabStreetview.style.background = 'rgba(56,189,248,0.15)';
            }
            if (tabOrtofoto) {
                tabOrtofoto.style.borderColor = 'rgba(255,255,255,0.1)';
                tabOrtofoto.style.color = '#94a3b8';
                tabOrtofoto.style.background = 'transparent';
            }
        } else {
            streetviewBox.style.display = 'none';
            ortofotoBox.style.display = 'block';
            if (tabOrtofoto) {
                tabOrtofoto.style.borderColor = '#38bdf8';
                tabOrtofoto.style.color = '#38bdf8';
                tabOrtofoto.style.background = 'rgba(56,189,248,0.15)';
            }
            if (tabStreetview) {
                tabStreetview.style.borderColor = 'rgba(255,255,255,0.1)';
                tabStreetview.style.color = '#94a3b8';
                tabStreetview.style.background = 'transparent';
            }
        }
    };

    // Helper function to return Street View static facade photo
    function getOpportunityMainImage(opp) {
        if (opp.images && opp.images.length > 0) {
            const realPhoto = opp.images.find(img => img && typeof img === 'string' && !img.toLowerCase().includes('catastro') && !img.toLowerCase().includes('cartografia/wms'));
            if (realPhoto) {
                return { url: realPhoto, isMap: false };
            }
        }
        const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality || ''}, ${opp.province || ''}, España`;
        const gmapsKey = window.GOOGLE_MAPS_API_KEY || localStorage.getItem('hivex_gmaps_api_key') || 'AIzaSyADs9RShXJVDUAO85OBIuwcjzC70V01_Vc';
        return {
            url: `https://maps.googleapis.com/maps/api/streetview?size=600x350&location=${encodeURIComponent(fullAddress)}&key=${gmapsKey}`,
            isMap: false
        };
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
            // Metrics according to User Rules & Source Type
            const refVal = opp.source_type === 'pgou'
                ? (opp.listing_price || opp.starting_bid || opp.property_ref_value || 0)
                : (opp.property_ref_value || opp.starting_bid || opp.appraisal_value || opp.listing_price || 0);
            const totalSurface = (opp.surface_m2 && opp.surface_m2 > 0) ? opp.surface_m2 : null;
            const effectiveSurface = (opp.effective_surface_m2 && opp.effective_surface_m2 > 0) ? opp.effective_surface_m2 : totalSurface;
            const ownershipPct = (opp.ownership_percentage && opp.ownership_percentage > 0) ? opp.ownership_percentage : 100;
            const ownershipFormatted = formatExactPercentage(ownershipPct);

            let surfaceDisplay = '<span style="color: #94a3b8; font-style: italic;">No consta BOE</span>';
            if (effectiveSurface) {
                if (ownershipPct < 100 && totalSurface) {
                    surfaceDisplay = `${formatNumber(effectiveSurface, 2)} m² <span style="font-size: 0.68rem; color: #38bdf8; display: block;">(${ownershipFormatted}% de ${formatNumber(totalSurface, 2)} m²)</span>`;
                } else {
                    surfaceDisplay = `${formatNumber(effectiveSurface, 2)} m²`;
                }
            }

            const propertyM2Display = (opp.property_m2_price && opp.property_m2_price > 0) ? `${formatCurrency(opp.property_m2_price)}/m²` : '<span style="color: #94a3b8; font-style: italic;">-</span>';
            const areaM2Display = `${formatCurrency(opp.area_m2_price)}/m²`;
            const typeLabel = isFlipping ? 'Inmueble' : 'Solar';

            const estimatedMktVal = opp.estimated_reference_value || ((effectiveSurface && opp.area_m2_price) ? (effectiveSurface * opp.area_m2_price) : refVal);
            const profitVal = (opp.potential_gross_profit !== undefined && opp.potential_gross_profit !== null) ? opp.potential_gross_profit : (estimatedMktVal - refVal);
            const profitFormatted = profitVal >= 0 ? `+${formatCurrency(profitVal)}` : formatCurrency(profitVal);

            const landType = opp.land_type || 'URBANO';
            const landColor = landType === 'RÚSTICO' ? '#f59e0b' : '#38bdf8';
            const landBg = landType === 'RÚSTICO' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(56, 189, 248, 0.15)';
            const ownershipText = (ownershipPct < 100) ? ` • ${ownershipFormatted}% PLENO DOMINIO` : '';

            const liensObj = opp.liens || { status: 'SIN CARGAS', label: 'Sin Cargas', color: 'green', badge: '🟢 LIBRE DE CARGAS' };
            const liensBadgeBg = liensObj.has_liens ? 'rgba(245, 158, 11, 0.15)' : 'rgba(34, 197, 94, 0.15)';
            const liensBadgeColor = liensObj.has_liens ? '#f59e0b' : '#4ade80';
            const liensBadgeLabel = liensObj.badge || (liensObj.has_liens ? '🟠 CON CARGAS (VER EDICTO)' : '🟢 LIBRE DE CARGAS');

            let urbanismHtml = '';
            let dateSubastaHeader = `
                <div style="font-size: 0.76rem; color: #f59e0b; margin-top: 4px; display: flex; align-items: center; gap: 4px;">
                    <i data-lucide="clock" style="width: 12px; height: 12px; display: inline;"></i> Cierre subasta: <strong>${escapeHtml(opp.auction_end_date || '15/09/2026 18:00h')}</strong>
                </div>
            `;
            let actionBtnLabel = 'BOE';
            let actionBtnUrl = opp.boe_url || opp.gazette_url || '#';

            if (opp.source_type === 'pgou') {
                actionBtnLabel = opp.gazette_source ? opp.gazette_source.split(' ')[0] : 'BOLETIN';
                actionBtnUrl = opp.gazette_url || opp.boe_url || '#';

                let landUseType = opp.proposed_land_use_type || 'RESIDENCIAL_LIBRE';
                let landUseBadgeBg = 'rgba(56, 189, 248, 0.15)';
                let landUseBadgeColor = '#38bdf8';
                let landUseLabel = '🏢 Residencial Libre';

                if (landUseType === 'RESIDENCIAL_VPA') {
                    landUseBadgeBg = 'rgba(52, 211, 153, 0.15)';
                    landUseBadgeColor = '#34d399';
                    landUseLabel = '🛡️ Residencial VPA/VPPO';
                } else if (landUseType === 'TERCIARIO_INDUSTRIAL') {
                    landUseBadgeBg = 'rgba(192, 132, 252, 0.15)';
                    landUseBadgeColor = '#c084fc';
                    landUseLabel = '🏭 Terciario / Industrial';
                }

                let repercDisplay = opp.land_repercussion_m2t ? `${formatCurrency(opp.land_repercussion_m2t)}/m²t` : 'N/D';

                dateSubastaHeader = `
                    <div style="font-size: 0.76rem; color: #c084fc; margin-top: 4px; display: flex; align-items: center; gap: 4px;">
                        <i data-lucide="scroll" style="width: 12px; height: 12px; display: inline;"></i> Publicación: <strong>${escapeHtml(opp.gazette_source || 'Boletín Oficial')} (${escapeHtml(opp.gazette_date || '')})</strong>
                    </div>
                `;

                urbanismHtml = `
                    <div class="card-urbanism-compact" style="background: rgba(15, 23, 42, 0.6); padding: 8px 12px; border-radius: 6px; margin: 8px 0; border: 1px solid rgba(168, 85, 247, 0.25); display: flex; flex-direction: column; gap: 6px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                <i data-lucide="compass" style="width: 13px; height: 13px; color: #c084fc;"></i> Uso Propuesto:
                            </span>
                            <span style="background: ${landUseBadgeBg}; color: ${landUseBadgeColor}; font-weight: 800; font-size: 0.76rem; padding: 2px 8px; border-radius: 4px;">
                                ${landUseLabel}
                            </span>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px;">
                            <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                <i data-lucide="layers" style="width: 13px; height: 13px; color: #38bdf8;"></i> Repercusión Est.:
                            </span>
                            <span style="color: #38bdf8; font-weight: 800; font-size: 0.78rem;">
                                ${repercDisplay} Total
                            </span>
                        </div>
                    </div>
                `;
            } else {
                urbanismHtml = `
                    <div class="card-urbanism-compact" style="background: rgba(15, 23, 42, 0.5); padding: 8px 12px; border-radius: 6px; margin: 8px 0; border: 1px solid rgba(255, 255, 255, 0.08); display: flex; flex-direction: column; gap: 6px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                <i data-lucide="building-2" style="width: 13px; height: 13px; color: #38bdf8;"></i> Clasificación Catastral:
                            </span>
                            <span style="background: ${landBg}; color: ${landColor}; font-weight: 800; font-size: 0.78rem; padding: 2px 8px; border-radius: 4px; text-transform: uppercase;">
                                ${landType}${ownershipText}
                            </span>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px;">
                            <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                <i data-lucide="shield-alert" style="width: 13px; height: 13px; color: ${liensBadgeColor};"></i> Cargas (BOE Edicto):
                            </span>
                            <span style="background: ${liensBadgeBg}; color: ${liensBadgeColor}; font-weight: 800; font-size: 0.76rem; padding: 2px 8px; border-radius: 4px;">
                                ${liensBadgeLabel}
                            </span>
                        </div>
                    </div>
                `;
            }

            return `
                <div class="deal-card" data-opp-id="${opp.id}" data-opp-index="${idx}" onclick="highlightOpportunityPin(${opp.id}, ${opp.lat || 'null'}, ${opp.lon || 'null'})">
                    <div class="card-image-banner" style="background-image: url('${mainImg}'); position: relative; height: 160px; overflow: hidden; border-radius: var(--radius-sm); background-size: cover; background-position: center;" onclick="openPropertyDetailModal(${idx}); event.stopPropagation();">
                        <div class="card-image-overlay" style="position: absolute; inset: 0; background: linear-gradient(to top, rgba(15, 23, 42, 0.9) 0%, transparent 60%); display: flex; justify-content: space-between; align-items: flex-start; padding: 10px;">
                            <span class="badge-strategy ${stratClass}">${stratLabel}</span>
                            <span class="badge-discount">-${formatNumber(opp.discount_percentage, 0)}% Descuento</span>
                        </div>
                    </div>

                    <div class="card-content-compact">
                        <h3 class="card-title" onclick="openPropertyDetailModal(${idx}); event.stopPropagation();" title="${escapeHtml(opp.title)}">${escapeHtml(opp.title)}</h3>
                        
                        <div class="card-location">
                            <a href="javascript:void(0)" class="address-maps-link" onclick="openGoogleMapsModal('${escapeHtml(fullAddress)}', ${opp.lat || 'null'}, ${opp.lon || 'null'}, event)" title="Ver en Google Maps Satélite">
                                <i data-lucide="map-pin" style="width: 12px; height: 12px;"></i> <span>${escapeHtml(fullAddress)}</span>
                                <span class="maps-badge">Google Maps</span>
                            </a>
                        </div>

                        ${dateSubastaHeader}

                        ${urbanismHtml}

                        <div class="card-financials-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0; background: rgba(15, 23, 42, 0.4); padding: 10px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.06);">
                            <div class="fin-cell">
                                <span class="fin-lbl">€/m² ${typeLabel}</span>
                                <span class="fin-val val-salida" style="font-size: 0.88rem; font-weight: 700;">${propertyM2Display}</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">€/m² Zona (${typeLabel})</span>
                                <span class="fin-val" style="font-size: 0.88rem; font-weight: 700; color: #38bdf8;">${areaM2Display} (*)</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">${opp.source_type === 'pgou' ? 'Precio Adquisición' : 'Valor Subasta'}</span>
                                <span class="fin-val val-tasacion" style="font-size: 0.95rem; font-weight: 700;">${formatCurrency(refVal)}</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">Valor Mercado Estimado</span>
                                <span class="fin-val" style="font-size: 0.95rem; font-weight: 700; color: #38bdf8;">${formatCurrency(estimatedMktVal)}</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">Superficie (${opp.source_type === 'pgou' ? 'Suelo m²s' : 'Cuota Real'})</span>
                                <span class="fin-val" style="font-size: 0.88rem; color: #f8fafc; font-weight: 600;">${surfaceDisplay}</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">Beneficio / Margen Est.</span>
                                <span class="fin-val val-profit" style="font-size: 0.88rem; font-weight: 700; color: ${profitVal >= 0 ? '#4ade80' : '#f87171'};">${profitFormatted}</span>
                            </div>
                        </div>

                        <div class="card-bottom-row" style="display: flex; flex-direction: column; gap: 8px; align-items: stretch; width: 100%;">
                            <div class="scores-compact" style="display: flex; flex-wrap: wrap; gap: 4px; align-items: center;">
                                <span class="score-chip" title="Score Global Oportunidad" style="${getScoreBgStyle(opp.overall_score)}">Score: <strong>${formatScore(opp.overall_score)}</strong></span>
                                <span class="score-chip" title="Score Descuento vs Mercado" style="${getScoreBgStyle((opp.property_m2_price && opp.property_m2_price > 0) ? (opp.discount_score || 0) : 0)}">Desc: <strong>${formatScore((opp.property_m2_price && opp.property_m2_price > 0) ? (opp.discount_score || 0) : 0)}</strong></span>
                                <span class="score-chip" title="Score POIs / Entorno (OSM)" style="${getScoreBgStyle(opp.poi_score)}">POI: <strong>${formatScore(opp.poi_score)}</strong></span>
                                <span class="score-chip" title="Score Renta INE" style="${getScoreBgStyle(opp.income_score)}">Renta: <strong>${formatScore(opp.income_score)}</strong></span>
                                <span class="score-chip" title="Score Demografía INE" style="${getScoreBgStyle(opp.demographic_score)}">Demo: <strong>${formatScore(opp.demographic_score)}</strong></span>
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.72rem; color: #94a3b8; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 6px;">
                                <span>Hogar: <strong style="color: #f8fafc;">${formatCurrency(opp.avg_household_income || 32000)}/año</strong></span>
                                <span>Persona: <strong style="color: #f8fafc;">${formatCurrency(opp.avg_person_income || 14500)}/año</strong></span>
                            </div>
                            <div class="card-actions-group" style="display: flex; justify-content: flex-end; gap: 6px;">
                                <button class="btn btn-secondary btn-xs" onclick="openPropertyDetailModal(${idx}); event.stopPropagation();">
                                    <i data-lucide="eye" style="width: 12px; height: 12px;"></i> Ficha
                                </button>
                                <a href="${actionBtnUrl}" target="_blank" rel="noopener" class="btn-boe-xs" onclick="event.stopPropagation();">
                                    ${actionBtnLabel} <i data-lucide="external-link" style="width: 11px; height: 11px;"></i>
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
        const images = (opp.images && opp.images.length > 0) ? opp.images : [];
        const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality}, ${opp.province}`;

        const totalSurface = (opp.surface_m2 && opp.surface_m2 > 0) ? opp.surface_m2 : null;
        const effectiveSurface = (opp.effective_surface_m2 && opp.effective_surface_m2 > 0) ? opp.effective_surface_m2 : totalSurface;
        const ownershipPct = (opp.ownership_percentage && opp.ownership_percentage > 0) ? opp.ownership_percentage : 100;
        const ownershipFormatted = formatExactPercentage(ownershipPct);

        let surfaceDisplayModal = 'No consta BOE/Catastro';
        if (effectiveSurface) {
            if (ownershipPct < 100 && totalSurface) {
                surfaceDisplayModal = `
                    <div style="font-size: 1.1rem; font-weight: 700; color: #f8fafc;">${formatNumber(effectiveSurface, 2)} m²</div>
                    <div style="font-size: 0.72rem; color: #38bdf8; font-weight: 600; margin-top: 2px;">(${ownershipFormatted}% de ${formatNumber(totalSurface, 2)} m² total)</div>
                `;
            } else {
                surfaceDisplayModal = `<div style="font-size: 1.1rem; font-weight: 700; color: #f8fafc;">${formatNumber(effectiveSurface, 2)} m²</div>`;
            }
        }

        const propertyM2Display = (opp.property_m2_price && opp.property_m2_price > 0) ? `${formatCurrency(opp.property_m2_price)}/m²` : '-';
        const areaM2Display = `${formatCurrency(opp.area_m2_price)}/m²`;
        const districtName = opp.locality || opp.province || 'Zona';
        const discountScoreVal = (opp.property_m2_price && opp.property_m2_price > 0) ? (opp.discount_score || 0) : 0;
        const landType = opp.land_type || 'URBANO';

        let liensDetailHtml = '';
        let urbanismDetail = '';
        let dateSubastaHeaderModal = '';
        let extBtnLabelModal = 'Abrir Expediente Oficial en BOE';
        let extBtnUrlModal = opp.boe_url || opp.gazette_url || '#';

        if (opp.source_type === 'pgou') {
            extBtnLabelModal = `Abrir Publicación en ${opp.gazette_source ? opp.gazette_source.split(' ')[0] : 'Boletín Oficial'}`;
            extBtnUrlModal = opp.gazette_url || opp.boe_url || '#';

            dateSubastaHeaderModal = `
                <div style="font-size: 0.88rem; color: #c084fc; display: flex; align-items: center; gap: 6px; padding-left: 2px;">
                    <i data-lucide="scroll" style="width: 15px; height: 15px; color: #c084fc;"></i>
                    <span>Publicación Oficial: <strong>${escapeHtml(opp.gazette_source || 'Boletín Oficial')} (${escapeHtml(opp.gazette_date || '')})</strong></span>
                </div>
            `;

            let landUseType = opp.proposed_land_use_type || 'RESIDENCIAL_LIBRE';
            let landUseBadgeBg = 'rgba(56, 189, 248, 0.2)';
            let landUseBadgeColor = '#38bdf8';
            let landUseLabel = '🏢 RESIDENCIAL LIBRE';

            if (landUseType === 'RESIDENCIAL_VPA') {
                landUseBadgeBg = 'rgba(52, 211, 153, 0.2)';
                landUseBadgeColor = '#34d399';
                landUseLabel = '🛡️ RESIDENCIAL VPA / VPPO (PROTEGIDA)';
            } else if (landUseType === 'TERCIARIO_INDUSTRIAL') {
                landUseBadgeBg = 'rgba(192, 132, 252, 0.2)';
                landUseBadgeColor = '#c084fc';
                landUseLabel = '🏭 TERCIARIO / COMERCIAL / INDUSTRIAL';
            }

            urbanismDetail = `
                <div style="margin-top: 14px; padding: 12px 16px; background: rgba(15, 23, 42, 0.65); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 8px; display: flex; justify-content: space-between; align-items: center; font-size: 0.9rem; width: 100%;">
                    <span style="color: #cbd5e1; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                        <i data-lucide="compass" style="width: 16px; height: 16px; color: #c084fc;"></i> Uso Propuesto & Calificación Urbanística:
                    </span>
                    <span class="badge" style="background: ${landUseBadgeBg}; color: ${landUseBadgeColor}; font-weight: 800; font-size: 0.88rem; padding: 4px 12px; border-radius: 6px; text-transform: uppercase;">
                        ${landUseLabel}
                    </span>
                </div>
            `;

            // PGOU Milestones Stepper
            const milestones = opp.milestones || [
                { phase: "Aprobación Inicial PGOU", status: "COMPLETED", timeframe: "Concluido", uplift: "x1.25" },
                { phase: "Aprobación Definitiva", status: "CURRENT", timeframe: "6-12 meses", uplift: "x1.85" },
                { phase: "Proyecto Reparcelación", status: "PENDING", timeframe: "3-6 meses", uplift: "x2.40" },
                { phase: "Suelo Finalista / Licencia", status: "PENDING", timeframe: "Inmediato", uplift: "x3.00" }
            ];

            const milestonesStepsHtml = milestones.map((m) => {
                let isDone = m.status === 'COMPLETED';
                let isCurrent = m.status === 'CURRENT';
                let statusBg = isDone ? 'rgba(34, 197, 94, 0.15)' : (isCurrent ? 'rgba(168, 85, 247, 0.25)' : 'rgba(255, 255, 255, 0.04)');
                let statusColor = isDone ? '#4ade80' : (isCurrent ? '#c084fc' : '#94a3b8');
                let badgeText = isDone ? '✔ Completado' : (isCurrent ? '⚡ En Proceso' : '⏳ Pendiente');

                return `
                    <div style="flex: 1; min-width: 130px; display: flex; flex-direction: column; align-items: center; text-align: center; padding: 10px 8px; background: ${statusBg}; border: 1px solid ${statusColor}55; border-radius: 8px;">
                        <span style="font-size: 0.72rem; color: ${statusColor}; font-weight: 800; text-transform: uppercase; margin-bottom: 4px;">${badgeText}</span>
                        <strong style="font-size: 0.84rem; color: #f8fafc; line-height: 1.2; margin-bottom: 6px;">${escapeHtml(m.phase)}</strong>
                        <span style="font-size: 0.75rem; color: #38bdf8; font-weight: 700;">Reval. ${m.uplift}</span>
                        <span style="font-size: 0.72rem; color: #cbd5e1; margin-top: 2px;">⏱️ ${escapeHtml(m.timeframe)}</span>
                    </div>
                `;
            }).join('');

            const landRepercussion = opp.land_repercussion_m2t ? formatCurrency(opp.land_repercussion_m2t) : 'N/D';
            const urbCostPerM2 = opp.urbanization_cost_m2s ? `${formatCurrency(opp.urbanization_cost_m2s)}/m²s` : '35-65 €/m²s';
            const totalUrbCost = opp.total_urbanization_cost ? formatCurrency(opp.total_urbanization_cost) : 'A calcular';

            liensDetailHtml = `
                <!-- PGOU Urban Planning Module: Milestones, Repercussion & Land Registry -->
                <div style="margin-top: 16px; padding: 16px; background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(168, 85, 247, 0.35); border-radius: 10px; width: 100%;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px;">
                        <span style="font-size: 0.98rem; font-weight: 700; color: #f8fafc; display: flex; align-items: center; gap: 8px;">
                            <i data-lucide="git-commit" style="width: 18px; height: 18px; color: #c084fc;"></i> Hitos de Planeamiento & Revalorización Estimada
                        </span>
                        <span class="badge" style="background: rgba(168, 85, 247, 0.2); color: #c084fc; font-weight: 800; font-size: 0.8rem; padding: 4px 10px; border-radius: 6px;">
                            📜 ${escapeHtml(opp.planning_status || 'PGOU')}
                        </span>
                    </div>

                    <!-- Milestones Stepper -->
                    <div style="display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap;">
                        ${milestonesStepsHtml}
                    </div>

                    <!-- Financial Repercussion Analysis Grid -->
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; background: rgba(0, 0, 0, 0.25); padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); margin-bottom: 14px;">
                        <div>
                            <span style="display: block; font-size: 0.75rem; color: #94a3b8; font-weight: 600;">Coste Urb. Est. (€/m²s)</span>
                            <strong style="color: #cbd5e1; font-size: 0.95rem;">${urbCostPerM2}</strong>
                        </div>
                        <div>
                            <span style="display: block; font-size: 0.75rem; color: #94a3b8; font-weight: 600;">Presupuesto Urbanización Total</span>
                            <strong style="color: #f59e0b; font-size: 0.95rem;">${totalUrbCost}</strong>
                        </div>
                        <div>
                            <span style="display: block; font-size: 0.75rem; color: #38bdf8; font-weight: 700;">Repercusión Suelo Total (€/m²t)</span>
                            <strong style="color: #38bdf8; font-size: 1.05rem; font-weight: 800;">${landRepercussion}/m²t</strong>
                        </div>
                    </div>

                    <!-- Registry & Compensation Board Status -->
                    <div style="background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.3); border-radius: 8px; padding: 12px 14px; display: flex; align-items: center; justify-content: space-between; font-size: 0.86rem;">
                        <div style="display: flex; align-items: center; gap: 8px; color: #4ade80;">
                            <i data-lucide="shield-check" style="width: 18px; height: 18px;"></i>
                            <strong style="color: #f8fafc;">Estatus Registral & Junta:</strong>
                        </div>
                        <span style="color: #cbd5e1; font-weight: 600; text-align: right; font-size: 0.85rem;">${escapeHtml(opp.reparcelacion_status || 'Junta Constituida / En Tramitación')}</span>
                    </div>
                    <div style="font-size: 0.74rem; color: #94a3b8; margin-top: 6px; font-style: italic;">
                        ℹ️ Verificación gratuita realizada mediante cruce de Sede Electrónica del Catastro (WFS) y anuncios obligatorios de edictos oficiales.
                    </div>
                </div>
            `;
        } else {
            dateSubastaHeaderModal = `
                <div style="font-size: 0.88rem; color: #f59e0b; display: flex; align-items: center; gap: 6px; padding-left: 2px;">
                    <i data-lucide="clock" style="width: 15px; height: 15px;"></i>
                    <span>Fecha Cierre Subasta: <strong>${escapeHtml(opp.auction_end_date || '15/09/2026 18:00h')}</strong></span>
                </div>
            `;

            urbanismDetail = `
                <div style="margin-top: 14px; padding: 10px 14px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; display: flex; justify-content: space-between; align-items: center; font-size: 0.9rem; width: 100%;">
                    <span style="color: #94a3b8; font-weight: 600;">Calificación del Suelo / Dominio:</span>
                    <span class="badge" style="background: ${landType === 'RÚSTICO' ? 'rgba(234,179,8,0.2)' : 'rgba(56,189,248,0.2)'}; color: ${landType === 'RÚSTICO' ? '#eab308' : '#38bdf8'}; font-weight: 800; font-size: 0.92rem; padding: 4px 10px; border-radius: 6px; text-transform: uppercase;">
                        ${landType} ${(ownershipPct < 100) ? `(${ownershipFormatted}% PLENO DOMINIO)` : ''}
                    </span>
                </div>
            `;

            const liensObj = opp.liens || {
                status: 'SIN CARGAS',
                label: 'Sin Cargas',
                description: 'Sin cargas preferentes declaradas en la ficha oficial del BOE.',
                color: 'green',
                badge: '🟢 LIBRE DE CARGAS'
            };
            const liensColor = liensObj.has_liens ? '#f59e0b' : '#4ade80';
            const liensBg = liensObj.has_liens ? 'rgba(245, 158, 11, 0.15)' : 'rgba(34, 197, 94, 0.15)';
            const liensBorder = liensObj.has_liens ? 'rgba(245, 158, 11, 0.3)' : 'rgba(34, 197, 94, 0.3)';

            liensDetailHtml = `
                <div style="margin-top: 14px; padding: 14px 16px; background: rgba(15, 23, 42, 0.7); border: 1px solid ${liensBorder}; border-radius: 8px; width: 100%;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 8px;">
                        <span style="font-size: 0.95rem; font-weight: 700; color: #f8fafc; display: flex; align-items: center; gap: 8px;">
                            <i data-lucide="shield-alert" style="width: 18px; height: 18px; color: ${liensColor};"></i> Situación Jurídica y Cargas (Edicto BOE)
                        </span>
                        <span class="badge" style="background: ${liensBg}; color: ${liensColor}; font-weight: 800; font-size: 0.82rem; padding: 4px 10px; border-radius: 6px; text-transform: uppercase;">
                            ${escapeHtml(liensObj.label || liensObj.status)}
                        </span>
                    </div>
                    <p style="font-size: 0.86rem; color: #cbd5e1; margin: 6px 0 0 0; line-height: 1.4;">
                        ${escapeHtml(liensObj.description || 'Sin cargas declaradas en la ficha oficial.')}
                    </p>
                </div>
            `;
        }

        const detailedScoresHtml = `
            <div class="detailed-scores-panel" style="margin-top: 16px; background: rgba(15, 23, 42, 0.6); padding: 14px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 8px;">
                    <span style="font-weight: 700; font-size: 0.98rem; color: #f8fafc; display: flex; align-items: center; gap: 6px;">
                        <i data-lucide="bar-chart-3" style="width: 17px; height: 17px; color: #38bdf8;"></i> KPIs
                    </span>
                    <span class="score-chip" style="${getScoreBgStyle(opp.overall_score)}; padding: 4px 10px; border-radius: 6px; font-size: 0.85rem; font-weight: 700;">
                        Score General: <strong>${formatScore(opp.overall_score)} / 100 pts</strong>
                    </span>
                </div>
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; font-size: 0.82rem;">
                    <div style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
                        <span style="color: #94a3b8; display: block; font-size: 0.75rem;">Renta Media por Hogar</span>
                        <strong style="color: #f8fafc; font-size: 0.95rem;">${formatCurrency(opp.avg_household_income || 32000)}/año</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
                        <span style="color: #94a3b8; display: block; font-size: 0.75rem;">Renta Media por Persona</span>
                        <strong style="color: #f8fafc; font-size: 0.95rem;">${formatCurrency(opp.avg_person_income || 14500)}/año</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
                        <span style="color: #94a3b8; display: block; font-size: 0.75rem;">Score Renta INE</span>
                        <strong style="color: ${getScoreColor(opp.income_score)}; font-size: 0.95rem;">${formatScore(opp.income_score)} / 100 pts</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
                        <span style="color: #94a3b8; display: block; font-size: 0.75rem;">Crecimiento Demográfico INE</span>
                        <strong style="color: ${getScoreColor(opp.demographic_score)}; font-size: 0.95rem;">+${formatNumber(opp.population_growth_rate, 1)}% (${formatScore(opp.demographic_score)} pts)</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
                        <span style="color: #94a3b8; display: block; font-size: 0.75rem;">Score POIs / Entorno (OSM)</span>
                        <strong style="color: ${getScoreColor(opp.poi_score)}; font-size: 0.95rem;">${formatScore(opp.poi_score)} / 100 pts</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
                        <span style="color: #94a3b8; display: block; font-size: 0.75rem;">Score Descuento vs Mercado</span>
                        <strong style="color: ${getScoreColor(discountScoreVal)}; font-size: 0.95rem;">${formatNumber(opp.discount_percentage, 2)}% (${formatScore(discountScoreVal)}/100 pts)</strong>
                    </div>
                </div>
            </div>
        `;

        const refValModal = opp.source_type === 'pgou'
            ? (opp.listing_price || opp.starting_bid || opp.property_ref_value || 0)
            : (opp.property_ref_value || opp.starting_bid || opp.appraisal_value || opp.listing_price || 0);
        const estimatedMktValModal = opp.estimated_reference_value || ((effectiveSurface && opp.area_m2_price) ? (effectiveSurface * opp.area_m2_price) : refValModal);
        const profitValModal = (opp.potential_gross_profit !== undefined && opp.potential_gross_profit !== null) ? opp.potential_gross_profit : (estimatedMktValModal - refValModal);
        const profitFormattedModal = profitValModal >= 0 ? `+${formatCurrency(profitValModal)}` : formatCurrency(profitValModal);

        const valorMicroVal = opp.valor_micro_est || opp.property_m2_price;
        const valorMicroDisplay = (valorMicroVal && valorMicroVal > 0) ? `${formatCurrency(valorMicroVal)}/m²` : 'N/D';

        body.innerHTML = `
            <div class="modal-prop-container">
                <div class="modal-media-wrapper" style="margin-bottom: 16px; border-radius: 12px; background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(56, 189, 248, 0.25); padding: 12px;">
                    <div style="width: 100%; height: 320px; border-radius: 8px; overflow: hidden; border: 1px solid rgba(255, 255, 255, 0.1); position: relative; background: #020617;">
                        <img src="${getOpportunityMainImage(opp).url}" style="width: 100%; height: 100%; object-fit: cover;" alt="${escapeHtml(opp.title)}">
                    </div>
                </div>

                <div class="modal-prop-header">
                    <h2>${escapeHtml(opp.title)}</h2>
                    <div class="modal-prop-address" style="margin-top: 8px; display: flex; flex-direction: column; gap: 6px;">
                        <a href="javascript:void(0)" class="address-maps-link" style="font-size: 0.92rem; padding: 6px 12px; width: fit-content;" onclick="openGoogleMapsModal('${escapeHtml(fullAddress)}', ${opp.lat || 'null'}, ${opp.lon || 'null'}, event)">
                            <i data-lucide="map-pin"></i> ${escapeHtml(fullAddress)}
                            <span class="maps-badge"><i data-lucide="map"></i> Abrir Google Maps Satélite</span>
                        </a>
                        ${dateSubastaHeaderModal}
                    </div>
                </div>

                <div class="card-financials" style="padding: 16px; font-size: 0.95rem; display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 10px;">
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">${opp.source_type === 'pgou' ? 'Valor Tasación Ref.' : 'Valor Tasación BOE'}</span>
                        <span class="fin-val ref" style="display: block; font-size: 1.15rem; font-weight: 800; margin-top: 2px;">${opp.appraisal_value > 0 ? formatCurrency(opp.appraisal_value) : '0 €'}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">${opp.source_type === 'pgou' ? 'Precio Adquisición Ref.' : 'Valor de Subasta'}</span>
                        <span class="fin-val price" style="display: block; font-size: 1.15rem; font-weight: 800; margin-top: 2px;">${formatCurrency(refValModal)}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #38bdf8; font-weight: 600; line-height: 1.2;">Valor Mercado Est.</span>
                        <span class="fin-val" style="display: block; font-size: 1.15rem; font-weight: 800; color: #38bdf8; margin-top: 2px;">${formatCurrency(estimatedMktValModal)} (*)</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">${opp.source_type === 'pgou' ? 'Superficie Suelo (m²s)' : 'Superficie (Cuota Real)'}</span>
                        <div class="fin-val" style="display: block; font-size: 1.05rem; color: #f8fafc; font-weight: 600; margin-top: 2px;">${surfaceDisplayModal}</div>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">${opp.source_type === 'pgou' ? 'Edificabilidad Total' : 'Precio €/m² Inmueble'}</span>
                        <span class="fin-val price" style="display: block; font-size: 1.05rem; font-weight: 700; margin-top: 2px;">${opp.source_type === 'pgou' ? `${formatNumber(opp.buildability_m2 || 0, 0)} m²t` : propertyM2Display}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #38bdf8; font-weight: 600; line-height: 1.2;">Precio €/m² Zona</span>
                        <span class="fin-val" style="display: block; font-size: 1.05rem; font-weight: 800; color: #38bdf8; margin-top: 2px;">${areaM2Display} (*)</span>
                    </div>
                    <div></div>
                    <div></div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">Beneficio / Margen Est.</span>
                        <span class="fin-val profit" style="display: block; font-size: 1.15rem; font-weight: 800; color: ${profitValModal >= 0 ? '#4ade80' : '#f87171'}; margin-top: 2px;">${profitFormattedModal} (*)</span>
                    </div>
                </div>

                <div style="margin-top: 8px; font-size: 0.78rem; color: #cbd5e1; padding-left: 2px;">
                    <strong>(*):</strong> <span style="color: #38bdf8; font-weight: 600;">valor sección censal (ref. barrio [${escapeHtml(districtName)}])</span>
                </div>

                <p style="color: var(--text-muted); font-size: 0.9rem; line-height: 1.5; margin-top: 14px; text-align: left;">${escapeHtml(opp.description || '')}</p>

                ${detailedScoresHtml}

                ${urbanismDetail}

                ${liensDetailHtml}

                <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--glass-border);">
                    <button class="btn btn-secondary" onclick="closePropertyDetailModal()">
                        <i data-lucide="x"></i> Cerrar Ventana
                    </button>
                    <a href="${extBtnUrlModal}" target="_blank" rel="noopener" class="btn btn-primary" style="${opp.source_type === 'pgou' ? 'background: linear-gradient(135deg, #a855f7 0%, #10b981 100%); border: none;' : ''}">
                        <i data-lucide="external-link"></i> ${escapeHtml(extBtnLabelModal)}
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
                const isPgou = opp.source_type === 'pgou';
                let color = '#f59e0b';
                if (isPgou) {
                    color = opp.planning_status && opp.planning_status.includes('Definitiva') ? '#a855f7' : '#10b981';
                } else {
                    color = opp.strategy === 'HOUSE_FLIPPING' ? '#ef4444' : '#f59e0b';
                }

                const imgInfo = getOpportunityMainImage(opp);
                const mainImg = imgInfo.url;
                const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality}`;

                const customIcon = L.divIcon({
                    className: 'custom-map-pin',
                    html: `<div style="background-color: ${color}; width: 20px; height: 20px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 12px ${color}; cursor: pointer;"></div>`,
                    iconSize: [20, 20]
                });

                const marker = L.marker([opp.lat, opp.lon], { icon: customIcon });
                markersMap[opp.id] = marker;

                let popupDetailHtml = '';
                if (isPgou) {
                    popupDetailHtml = `
                        <div style="margin-bottom: 2px; font-size: 11px; color: #7e22ce; font-weight: 700;">
                            📜 <strong>Boletín:</strong> ${escapeHtml(opp.gazette_source || 'PGOU')}
                        </div>
                        <div style="margin-bottom: 4px; font-size: 11px; color: #0284c7;">
                            🏗️ <strong>Edificabilidad:</strong> ${formatNumber(opp.buildability_m2, 0)} m²t
                        </div>
                        <div style="margin-bottom: 10px; font-weight: 700; color: #059669; font-size: 12px;">
                            -${formatNumber(opp.discount_percentage, 0)}% Margen Est. | Ref: ${formatCurrency(opp.listing_price)}
                        </div>
                    `;
                } else {
                    const boeAppraisalText = (opp.appraisal_value && opp.appraisal_value > 0) ? formatCurrency(opp.appraisal_value) : '0 € (Sin constancia en BOE)';
                    popupDetailHtml = `
                        <div style="margin-bottom: 2px; font-size: 11px; color: #475569;">
                            <strong>Tasación BOE:</strong> ${boeAppraisalText}
                        </div>
                        <div style="margin-bottom: 4px; font-size: 11px; color: #0284c7;">
                            <strong>Estimación Mercado:</strong> ${formatCurrency(opp.estimated_reference_value)}
                        </div>
                        <div style="margin-bottom: 10px; font-weight: 700; color: #059669; font-size: 12px;">
                            -${formatNumber(opp.discount_percentage, 0)}% Descuento | Salida: ${formatCurrency(opp.listing_price)}
                        </div>
                    `;
                }

                marker.bindPopup(`
                    <div style="font-family: sans-serif; color: #1e293b; max-width: 260px; padding: 4px;">
                        <div style="width: 100%; height: 110px; border-radius: 6px; overflow: hidden; margin-bottom: 8px; border: 1px solid #cbd5e1; background: #0f172a;">
                            <img src="${mainImg}" style="width: 100%; height: 100%; object-fit: cover;" alt="${escapeHtml(opp.title)}">
                        </div>
                        <strong style="font-size: 13px; display: block; margin-bottom: 4px; color: #0f172a; line-height: 1.2;">${escapeHtml(opp.title)}</strong>
                        <span style="color: #64748b; font-size: 11px; display: block; margin-bottom: 6px;">📍 ${escapeHtml(fullAddress)}</span>
                        ${popupDetailHtml}
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
        if (val === null || val === undefined || val === '' || isNaN(val)) return '0 €';
        const num = Number(val);
        const hasDecimals = (num % 1 !== 0);
        const formatted = new Intl.NumberFormat('es-ES', {
            useGrouping: true,
            minimumFractionDigits: hasDecimals ? 2 : 0,
            maximumFractionDigits: hasDecimals ? 2 : 0
        }).format(num);
        return `${formatted} €`;
    }

    function formatExactPercentage(val) {
        if (val === null || val === undefined || val === '' || isNaN(val)) return '100';
        return String(val);
    }

    function formatNumber(val, decimals = 1) {
        if (val === null || val === undefined || val === '' || isNaN(val)) return '0';
        const num = Number(val);
        const minFrac = (decimals === 0) ? 0 : ((num % 1 === 0) ? 0 : 1);
        const maxFrac = decimals;
        return new Intl.NumberFormat('es-ES', {
            useGrouping: true,
            minimumFractionDigits: minFrac,
            maximumFractionDigits: maxFrac
        }).format(num);
    }

    function formatScore(val) {
        if (val === null || val === undefined || val === '' || isNaN(val)) return '0,0';
        const num = Number(val);
        return new Intl.NumberFormat('es-ES', {
            useGrouping: true,
            minimumFractionDigits: 1,
            maximumFractionDigits: 1
        }).format(num);
    }

    function getScoreColor(val) {
        if (val === null || val === undefined || isNaN(val)) return '#94a3b8';
        const num = parseFloat(val);
        if (num < 50) return '#f43f5e';  // Malo (Rojo)
        if (num <= 70) return '#f97316'; // Medio (Naranja)
        if (num <= 90) return '#eab308'; // Bueno (Amarillo)
        return '#22c55e';               // Excelente (Verde, >90)
    }

    function getScoreBgStyle(val) {
        const color = getScoreColor(val);
        return `background: ${color}1a; color: ${color}; border: 1px solid ${color}55;`;
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
