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
        token: sessionStorage.getItem('hivex_token') || localStorage.getItem('hivex_token') || null,
        user: null,
        allOpportunities: [],
        filteredOpportunities: [],
        sourcesData: [],
        activeTab: 'deals',
        currentStrategy: 'ALL',
        minDiscount: 0.0,
        searchQuery: '',
        activeSource: 'subastas',
        onlySynergyPGOU: false,
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
        if (typeof L === 'undefined') {
            console.warn('Leaflet (L) no disponible todavía.');
            return null;
        }
        const mapContainer = document.getElementById('map');
        if (!mapContainer) return null;

        if (!map) {
            try {
                if (mapContainer._leaflet_id) {
                    mapContainer._leaflet_id = null;
                }
                map = L.map('map', {
                    preferCanvas: true,
                    zoomControl: true,
                    attributionControl: true
                }).setView([40.4168, -3.7038], 6); // Centered on Madrid / Spain

                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                    subdomains: 'abc',
                    maxZoom: 19
                }).addTo(map);

                mapMarkersLayer = L.layerGroup().addTo(map);

                map.on('click', () => {
                    if (typeof window.unspiderify === 'function') window.unspiderify();
                });
                map.on('zoomstart', () => {
                    if (typeof window.unspiderify === 'function') window.unspiderify();
                });

                window.map = map;
                window.mapMarkersLayer = mapMarkersLayer;
            } catch (err) {
                console.error('Error al inicializar Leaflet map:', err);
            }
        }

        if (map && typeof map.invalidateSize === 'function') {
            setTimeout(() => {
                try { map.invalidateSize(); } catch(e) {}
            }, 80);
        }
        return map;
    }

    // Carga directa de ficha de oportunidad desde enlace de alerta de Telegram (?opp_id=...)
    async function loadAndDisplayDirectOpportunity(oppId) {
        if (!oppId || window._openedDeepLinkOpp) return;
        window._openedDeepLinkOpp = true;

        try {
            // 1. Si ya se habían cargado oportunidades en memoria, abrirla directamente
            if (state.allOpportunities && state.allOpportunities.length > 0) {
                const found = state.allOpportunities.find(o => String(o.id) === String(oppId) || String(o.id_subasta) === String(oppId));
                if (found) {
                    window.openPropertyDetailModal(found);
                    return;
                }
            }

            // 2. Si no está en memoria, consultar endpoint específico
            const headers = state.token ? { 'Authorization': `Bearer ${state.token}` } : {};
            const res = await fetch(`/api/v1/opportunities/${encodeURIComponent(oppId)}`, { headers });
            if (res.ok) {
                const opp = await res.json();
                if (opp && (opp.id || opp.title)) {
                    const loginOverlay = document.getElementById('login-overlay');
                    if (loginOverlay) loginOverlay.classList.add('hidden');
                    window.openPropertyDetailModal(opp);
                }
            }
        } catch (err) {
            console.error('Error cargando oportunidad directa por ID:', err);
        }
    }

    // Authentication Checks
    async function checkAuthSession() {
        const urlParams = new URLSearchParams(window.location.search);
        const directOppId = urlParams.get('opp_id');
        if (directOppId) {
            loadAndDisplayDirectOpportunity(directOppId);
        }

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
        
        const loginVal = inputLogin.value.trim();
        const passVal = inputPassword.value;

        if (!loginVal || !passVal) {
            loginError.textContent = 'Por favor, introduce usuario y contraseña.';
            loginError.classList.remove('hidden');
            return;
        }

        btnLoginSubmit.disabled = true;
        btnLoginSubmit.innerHTML = 'Verificando credenciales...';

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
                sessionStorage.setItem('hivex_token', data.access_token);
                localStorage.setItem('hivex_token', data.access_token);
                showDashboard();
                showToast(`¡Bienvenido ${data.user.username}!`, 'success');
            } else {
                loginError.textContent = data.detail || 'Credenciales no válidas. Verifique usuario y contraseña.';
                loginError.classList.remove('hidden');
            }
        } catch (err) {
            loginError.textContent = 'Error de conexión con el servidor de autenticación.';
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
        sessionStorage.removeItem('hivex_token');
        localStorage.removeItem('hivex_token');
        state.allOpportunities = [];
        state.filteredOpportunities = [];
        if (dealsContainer) dealsContainer.innerHTML = '';
        showLoginOverlay();
    }

    btnLogout.addEventListener('click', logout);

    function showLoginOverlay() {
        loginOverlay.classList.remove('hidden');
        dashboardApp.classList.add('hidden');
        inputLogin.value = '';
        inputPassword.value = '';
        loginError.classList.add('hidden');
        if (window.lucide) lucide.createIcons();
    }

    function showDashboard() {
        loginOverlay.classList.add('hidden');
        dashboardApp.classList.remove('hidden');
        inputLogin.value = '';
        inputPassword.value = '';
        setTimeout(() => {
            initMap();
            if (map && typeof map.invalidateSize === 'function') {
                try { map.invalidateSize(); } catch(e) {}
            }
            fetchOpportunities();
        }, 80);
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
                setTimeout(() => { if (map && typeof map.invalidateSize === 'function') map.invalidateSize(); }, 80);
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
            const newOpps = Array.isArray(data) ? data : (data.opportunities || []);
            
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

            const urlParams = new URLSearchParams(window.location.search);
            const directOppId = urlParams.get('opp_id');
            if (directOppId && !window._openedDeepLinkOpp) {
                loadAndDisplayDirectOpportunity(directOppId);
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

    // Calculate & Update Header KPIs (Exclusively for Subastas Públicas BOE)
    function updateKPIs(opps) {
        const subastas = (opps || []).filter(o => (o.source_type || 'subastas') === 'subastas');
        const activeSubastas = subastas.filter(o => (o.discount_percentage / 100) >= 0.10);
        
        const totalCount = subastas.length;
        const activeCount = activeSubastas.length;
        
        let avgDisc = 0;
        let totalProfit = 0;

        if (activeSubastas.length > 0) {
            const sumDisc = activeSubastas.reduce((acc, curr) => acc + curr.discount_percentage, 0);
            avgDisc = sumDisc / activeSubastas.length;
            totalProfit = activeSubastas.reduce((acc, curr) => acc + (curr.potential_gross_profit || 0), 0);
        }

        if (kpiScanned) kpiScanned.textContent = totalCount;
        if (kpiActive) kpiActive.textContent = activeCount;
        if (kpiAvgDiscount) kpiAvgDiscount.textContent = `${avgDisc.toFixed(1)}%`;
        if (kpiTotalProfit) kpiTotalProfit.textContent = formatCurrency(totalProfit);
    }

    // Update Tab Badges for Opportunity Sources (Subastas counts active discount filter; PGOU ignores discount filter)
    function updateTabBadges() {
        const q = (state.searchQuery || '').trim().toLowerCase();

        const subastasCount = state.allOpportunities.filter(o => {
            const isSub = (o.source_type || 'subastas') === 'subastas';
            if (!isSub) return false;
            if (state.currentStrategy !== 'ALL' && o.strategy !== state.currentStrategy) return false;
            if (state.minDiscount > 0.0 && (o.discount_percentage / 100) < state.minDiscount) return false;
            if (q !== '') {
                const title = (o.title || '').toLowerCase();
                const prov = (o.province || '').toLowerCase();
                const loc = (o.locality || '').toLowerCase();
                if (!title.includes(q) && !prov.includes(q) && !loc.includes(q)) return false;
            }
            return true;
        }).length;

        const pgouCount = state.allOpportunities.filter(o => {
            const isPgou = o.source_type === 'pgou';
            if (!isPgou) return false;
            if (state.currentStrategy !== 'ALL' && o.strategy !== state.currentStrategy) return false;
            if (q !== '') {
                const title = (o.title || '').toLowerCase();
                const prov = (o.province || '').toLowerCase();
                const loc = (o.locality || '').toLowerCase();
                if (!title.includes(q) && !prov.includes(q) && !loc.includes(q)) return false;
            }
            return true;
        }).length;
        
        const edictosCount = state.allOpportunities.filter(o => {
            const isEdicto = o.source_type === 'edictos';
            if (!isEdicto) return false;
            if (state.currentStrategy !== 'ALL' && o.strategy !== state.currentStrategy) return false;
            if (q !== '') {
                const title = (o.title || '').toLowerCase();
                const prov = (o.province || '').toLowerCase();
                const loc = (o.locality || '').toLowerCase();
                if (!title.includes(q) && !prov.includes(q) && !loc.includes(q)) return false;
            }
            return true;
        }).length;

        const marketCount = state.allOpportunities.filter(o => {
            const isMkt = o.source_type === 'market';
            if (!isMkt) return false;
            if (state.onlySynergyPGOU && !o.has_pgou_synergy) return false;
            if (state.currentStrategy !== 'ALL' && o.strategy !== state.currentStrategy) return false;
            if (state.minDiscount > 0.0 && ((o.discount_percentage || 0) / 100) < state.minDiscount) return false;
            if (q !== '') {
                const title = (o.title || '').toLowerCase();
                const prov = (o.province || '').toLowerCase();
                const loc = (o.locality || '').toLowerCase();
                if (!title.includes(q) && !prov.includes(q) && !loc.includes(q)) return false;
            }
            return true;
        }).length;
        
        const badgeSub = document.getElementById('badge-subastas-count');
        const badgePgou = document.getElementById('badge-pgou-count');
        const badgeEdictos = document.getElementById('badge-edictos-count');
        const badgeMarket = document.getElementById('badge-market-count');
        
        if (badgeSub) badgeSub.textContent = subastasCount;
        if (badgePgou) badgePgou.textContent = pgouCount;
        if (badgeEdictos) badgeEdictos.textContent = edictosCount;
        if (badgeMarket) badgeMarket.textContent = marketCount;
    }

    // Toggle PGOU Synergy Filter for Market Tab
    window.toggleSynergyFilter = function() {
        state.onlySynergyPGOU = !state.onlySynergyPGOU;
        const btn = document.getElementById('btn-toggle-synergy');
        if (btn) {
            if (state.onlySynergyPGOU) {
                btn.classList.add('active');
                btn.innerHTML = `<i data-lucide="check" style="width: 13px; height: 13px;"></i> <span>🎯 Sinergia PGOU (Activo)</span>`;
                showToast('🎯 Mostrando exclusivamente inmuebles de Market con Sinergia en PGOU', 'info');
            } else {
                btn.classList.remove('active');
                btn.innerHTML = `<i data-lucide="crosshair" style="width: 13px; height: 13px;"></i> <span>⚡ Solo con Sinergia PGOU</span>`;
            }
            if (window.lucide) lucide.createIcons();
        }
        applyFilters();
    };

    // Jump from Market synergy card to PGOU sector viewer
    window.jumpToPgouSector = function(pgouId) {
        closePropertyDetailModal();
        switchOpportunitySource('pgou');
        setTimeout(() => {
            const target = state.allOpportunities.find(o => o.id === pgouId || (o.source_type === 'pgou' && (o.title || '').includes(pgouId)));
            if (target) {
                highlightOpportunityPin(target.id, target.lat, target.lon);
            }
        }, 350);
    };

    // Opportunity Source Tab Switcher (Subastas BOE vs Visor PGOU vs Edictos/Reg. vs Market)
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

        // Show/hide PGOU synergy filter button in toolbar when relevant
        const synergyFilterGroup = document.getElementById('filter-group-synergy');
        if (synergyFilterGroup) {
            synergyFilterGroup.style.display = (sourceType === 'market' || sourceType === 'subastas') ? 'flex' : 'none';
        }

        // Ensure Leaflet map recalculates its dimensions and renders tiles crisply
        if (typeof map !== 'undefined' && map) {
            setTimeout(() => {
                try { map.invalidateSize(); } catch(e) {}
            }, 60);
        }

        // Update map legend dynamically according to active tab
        const legendEl = document.querySelector('.map-legend');
        if (legendEl) {
            if (sourceType === 'subastas') {
                legendEl.innerHTML = `
                    <span class="dot pin-flipping"></span> House Flipping
                    <span class="dot pin-land"></span> Suelo / Desarrollo
                `;
            } else if (sourceType === 'pgou') {
                legendEl.innerHTML = `
                    <span class="dot" style="background:#a855f7; box-shadow: 0 0 8px #a855f7;"></span> Aprobación PGOU / Convenio
                    <span class="dot" style="background:#10b981; box-shadow: 0 0 8px #10b981;"></span> Reordenación / Sector
                `;
            } else if (sourceType === 'edictos') {
                legendEl.innerHTML = `
                    <span class="dot" style="background:#eab308; box-shadow: 0 0 8px #eab308;"></span> Herencia Yacente (TEJU)
                    <span class="dot" style="background:#6366f1; box-shadow: 0 0 8px #6366f1;"></span> División Cosa Común (Proindiviso)
                `;
            } else if (sourceType === 'market') {
                legendEl.innerHTML = `
                    <span class="dot" style="background:#10b981; box-shadow: 0 0 8px #10b981;"></span> Inmueble en Venta (Market)
                    <span class="dot" style="background:#a855f7; box-shadow: 0 0 8px #a855f7;"></span> 🎯 Con Sinergia PGOU
                `;
            }
        }

        applyFilters();

        const currentCount = state.filteredOpportunities.length;
        if (sourceType === 'subastas') {
            showToast(`⚖️ Subastas BOE: Mostrando ${currentCount} subastas públicas activas`, 'info');
        } else if (sourceType === 'pgou') {
            showToast(`📐 Visor PGOU: Mostrando ${currentCount} desarrollos urbanísticos detectados en boletines oficiales (BOCM, DOGC, BOJA)`, 'success');
        } else if (sourceType === 'edictos') {
            showToast(`⚖️ Edictos y Registros: Mostrando ${currentCount} herencias y procedimientos de proindiviso`, 'info');
        } else if (sourceType === 'market') {
            showToast(`🏪 Market: Mostrando ${currentCount} oportunidades en portales inmobiliarios (menor precio garantizado y cruce PGOU)`, 'success');
        }
    };

    // Delegación directa al escáner unificado de la plataforma
    window.syncMarketOpportunities = function() {
        if (btnRunPipeline) btnRunPipeline.click();
    };

    // Apply Filter Logic
    function applyFilters() {
        state.filteredOpportunities = state.allOpportunities.filter(opp => {
            // Source Filter (Subastas BOE vs PGOU Visor vs Edictos/Reg. vs Market)
            const oppSource = opp.source_type || 'subastas';
            if (oppSource !== state.activeSource) {
                return false;
            }
            // Sinergia PGOU Filter (for Market)
            if (state.activeSource === 'market' && state.onlySynergyPGOU && !opp.has_pgou_synergy) {
                return false;
            }
            // Strategy Filter
            if (state.currentStrategy !== 'ALL' && opp.strategy !== state.currentStrategy) {
                return false;
            }
            // Discount Filter (Subastas, Edictos, and Market; PGOU ignores auction discount filter)
            if ((oppSource === 'subastas' || oppSource === 'edictos' || oppSource === 'market') && state.minDiscount > 0.0) {
                const discDecimal = (opp.discount_percentage || 0) / 100;
                if (discDecimal < state.minDiscount) {
                    return false;
                }
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

        updateTabBadges();
        const activeTotal = state.allOpportunities.filter(o => (o.source_type || 'subastas') === state.activeSource).length;
        if (filteredCount) {
            filteredCount.textContent = `Mostrando ${state.filteredOpportunities.length} de ${activeTotal} oportunidades`;
        }
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

    // Helper function to return verified photo list or Street View static facade photo
    function getOpportunityImagesList(opp) {
        let list = [];
        if (opp.images && Array.isArray(opp.images) && opp.images.length > 0) {
            const valid = opp.images.filter(img => img && typeof img === 'string' && !img.toLowerCase().includes('catastro') && !img.toLowerCase().includes('cartografia/wms'));
            if (valid.length > 0) {
                list = [...valid];
            }
        }
        const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality || ''}, ${opp.province || ''}, España`;
        const gmapsKey = window.GOOGLE_MAPS_API_KEY || localStorage.getItem('hivex_gmaps_api_key') || 'AIzaSyADs9RShXJVDUAO85OBIuwcjzC70V01_Vc';
        const streetViewUrl = `https://maps.googleapis.com/maps/api/streetview?size=600x350&location=${encodeURIComponent(fullAddress)}&key=${gmapsKey}`;
        
        if (list.length === 0) {
            return [streetViewUrl];
        }
        return list;
    }

    // Helper function to return Street View or main facade photo
    function getOpportunityMainImage(opp) {
        const imgs = getOpportunityImagesList(opp);
        return { url: imgs[0], isMap: false };
    }

    // Global Carousel Handlers for Cards
    window.cardCarouselState = window.cardCarouselState || {};

    window.cardCarouselNav = function(event, idx, dir) {
        if (event) {
            event.stopPropagation();
            event.preventDefault();
        }
        const opps = window._lastOpportunities || [];
        const opp = opps[idx];
        if (!opp) return;
        const imgs = getOpportunityImagesList(opp);
        if (imgs.length <= 1) return;

        let cur = window.cardCarouselState[idx] || 0;
        cur = (cur + dir + imgs.length) % imgs.length;
        window.cardCarouselState[idx] = cur;

        const imgEl = document.getElementById(`card-carousel-img-${idx}`);
        const numEl = document.getElementById(`card-carousel-num-${idx}`);
        if (imgEl) {
            imgEl.style.backgroundImage = `url('${imgs[cur]}')`;
        }
        if (numEl) {
            numEl.textContent = cur + 1;
        }
    };

    // Global Modal Gallery Handlers
    window.modalGalleryState = {
        images: [],
        currentIndex: 0,
        portal: 'Idealista'
    };

    window.modalGalleryNav = function(dir) {
        if (!window.modalGalleryState || !window.modalGalleryState.images || window.modalGalleryState.images.length <= 1) return;
        const len = window.modalGalleryState.images.length;
        let nextIdx = (window.modalGalleryState.currentIndex + dir + len) % len;
        window.modalGalleryGoTo(nextIdx);
    };

    window.modalGalleryGoTo = function(targetIdx) {
        if (!window.modalGalleryState || !window.modalGalleryState.images) return;
        const images = window.modalGalleryState.images;
        if (targetIdx < 0 || targetIdx >= images.length) return;
        window.modalGalleryState.currentIndex = targetIdx;

        const mainImg = document.getElementById('modal-gallery-active-img');
        const numEl = document.getElementById('modal-gallery-cur-num');
        if (mainImg) {
            mainImg.style.opacity = '0.3';
            setTimeout(() => {
                mainImg.src = images[targetIdx];
                mainImg.style.opacity = '1';
            }, 80);
        }
        if (numEl) {
            numEl.textContent = targetIdx + 1;
        }
        const srcEl = document.getElementById('modal-gallery-source-name');
        if (srcEl) {
            const isGmaps = images[targetIdx] && images[targetIdx].includes('maps.googleapis.com');
            srcEl.textContent = isGmaps ? '• Google Street View' : `• Fuente: ${window.modalGalleryState.portal || 'Idealista'}`;
        }

        // Highlight active thumbnail and scroll into view
        document.querySelectorAll('.gallery-thumb-item').forEach((el, i) => {
            if (i === targetIdx) {
                el.classList.add('active');
                el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
            } else {
                el.classList.remove('active');
            }
        });
    };

    // Keyboard navigation listener (Left / Right arrows)
    if (!window._modalGalleryKeyAttached) {
        window._modalGalleryKeyAttached = true;
        window.addEventListener('keydown', (e) => {
            const modal = document.getElementById('property-detail-modal');
            if (modal && modal.style.display !== 'none' && !modal.classList.contains('hidden')) {
                if (e.key === 'ArrowLeft') {
                    window.modalGalleryNav(-1);
                } else if (e.key === 'ArrowRight') {
                    window.modalGalleryNav(1);
                }
            }
        });
    }

    // Render Opportunity Cards Feed
    function renderDeals(opps) {
        window._lastOpportunities = opps;
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
            
            let subastaTypeBadge = isFlipping ? '🏠 VIVIENDA' : '📐 SOLAR';
            if (opp.property_type) {
                const pt = opp.property_type.toLowerCase();
                if (pt.includes('vivienda') || pt.includes('piso') || pt.includes('chalet') || pt.includes('casa') || pt.includes('residencial')) {
                    subastaTypeBadge = '🏠 VIVIENDA';
                } else if (pt.includes('solar') || pt.includes('suelo') || pt.includes('terreno') || pt.includes('parcela')) {
                    subastaTypeBadge = '📐 SOLAR';
                } else if (pt.includes('local') || pt.includes('comercial')) {
                    subastaTypeBadge = '🏬 LOCAL';
                } else if (pt.includes('nave') || pt.includes('industrial')) {
                    subastaTypeBadge = '🏭 NAVE';
                } else if (pt.includes('garaje') || pt.includes('parking')) {
                    subastaTypeBadge = '🚗 GARAJE';
                } else {
                    subastaTypeBadge = `🏠 ${opp.property_type.toUpperCase()}`;
                }
            }
            const subastaBadgeBg = isFlipping ? '#e11d48' : '#d97706';
            
            const oppImages = getOpportunityImagesList(opp);
            const mainImg = oppImages[0];
            const imgCount = oppImages.length;
            const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality}, ${opp.province}`;
            const refVal = (opp.source_type === 'pgou' || opp.source_type === 'edictos')
                ? (opp.listing_price || opp.starting_bid || opp.property_ref_value || 0)
                : (opp.property_ref_value || opp.starting_bid || opp.appraisal_value || opp.listing_price || 0);
            const totalSurface = (opp.surface_m2 && opp.surface_m2 > 0) ? opp.surface_m2 : null;
            const effectiveSurface = (opp.effective_surface_m2 && opp.effective_surface_m2 > 0) ? opp.effective_surface_m2 : totalSurface;
            const ownershipPct = (opp.ownership_percentage && opp.ownership_percentage > 0) ? opp.ownership_percentage : 100;
            const ownershipFormatted = formatExactPercentage(ownershipPct);

            const isSurfaceMissing = Boolean(opp.is_surface_missing || !effectiveSurface);

            let surfaceDisplay = '<span style="color: #f59e0b; font-weight: 700; font-size: 0.80rem;">⚠️ Sin constancia BOE</span>';
            if (effectiveSurface && !isSurfaceMissing) {
                const estBadge = opp.is_surface_estimated ? '<span style="font-size: 0.68rem; color: #c084fc; font-weight: 700; margin-left: 3px;" title="Superficie estimada">(est.)</span>' : '';
                if (ownershipPct < 100 && totalSurface) {
                    surfaceDisplay = `${formatNumber(effectiveSurface, 2)} m² ${estBadge}<span style="font-size: 0.68rem; color: #38bdf8; display: block;">(${ownershipFormatted}% de ${formatNumber(totalSurface, 2)} m²)</span>`;
                } else {
                    surfaceDisplay = `${formatNumber(effectiveSurface, 2)} m² ${estBadge}`;
                }
            }

            const propertyM2Display = (!isSurfaceMissing && opp.property_m2_price && opp.property_m2_price > 0) ? `${formatCurrency(opp.property_m2_price)}/m²` : '<span style="color: #94a3b8; font-style: italic;">-</span>';
            const areaM2Display = `${formatCurrency(opp.area_m2_price)}/m²`;
            const typeLabel = isFlipping ? 'Inmueble' : 'Solar';

            const estimatedMktVal = isSurfaceMissing ? null : (opp.estimated_reference_value || ((effectiveSurface && opp.area_m2_price) ? (effectiveSurface * opp.area_m2_price) : null));
            const profitVal = isSurfaceMissing ? null : ((opp.potential_gross_profit !== undefined && opp.potential_gross_profit !== null) ? opp.potential_gross_profit : (estimatedMktVal ? (estimatedMktVal - refVal) : null));
            const profitFormatted = isSurfaceMissing ? '<span style="color: #f59e0b; font-size: 0.78rem; font-weight: 700;">Requiere Nota Simple</span>' : (profitVal >= 0 ? `+${formatCurrency(profitVal)}` : formatCurrency(profitVal));

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
                actionBtnLabel = opp.gazette_code || (opp.gazette_source ? opp.gazette_source.split(' ')[0] : 'BOLETIN');
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
                        <i data-lucide="layers" style="width: 12px; height: 12px; display: inline;"></i> Ámbito: <strong>${escapeHtml(opp.gazette_code || opp.planning_status || 'Planeamiento Urbanístico')}</strong>
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
            } else if (opp.source_type === 'edictos') {
                const isHerencia = opp.category === 'HERENCIA_YACENTE';
                actionBtnLabel = isHerencia ? 'TEJU BOE' : 'SUB. JUDICIAL';
                actionBtnUrl = opp.boe_url || (opp.teju_boe_code && /^BOE-[A-Z]-\d{4}-\d+$/i.test(opp.teju_boe_code) ? `https://www.boe.es/diario_boe/txt.php?id=${opp.teju_boe_code}` : (opp.expediente_num ? `https://www.boe.es/buscar/edictos_judiciales.php?campo%5B0%5D=DOC&dato%5B0%5D=${encodeURIComponent(opp.expediente_num)}&accion=Buscar` : 'https://www.boe.es/buscar/edictos_judiciales.php'));

                dateSubastaHeader = `
                    <div style="font-size: 0.76rem; color: ${isHerencia ? '#fbbf24' : '#818cf8'}; margin-top: 4px; display: flex; align-items: center; gap: 4px;">
                        <i data-lucide="scale" style="width: 12px; height: 12px; display: inline;"></i> <strong>${escapeHtml(opp.proceedings_type || 'Procedimiento Edictal')}</strong>
                    </div>
                `;

                urbanismHtml = `
                    <div class="card-urbanism-compact" style="background: rgba(15, 23, 42, 0.6); padding: 8px 12px; border-radius: 6px; margin: 8px 0; border: 1px solid ${isHerencia ? 'rgba(251, 191, 36, 0.3)' : 'rgba(129, 140, 248, 0.3)'}; display: flex; flex-direction: column; gap: 6px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                <i data-lucide="landmark" style="width: 13px; height: 13px; color: ${isHerencia ? '#fbbf24' : '#818cf8'};"></i> Origen:
                            </span>
                            <span style="background: ${isHerencia ? 'rgba(251, 191, 36, 0.15)' : 'rgba(129, 140, 248, 0.15)'}; color: ${isHerencia ? '#fbbf24' : '#818cf8'}; font-weight: 700; font-size: 0.74rem; padding: 2px 8px; border-radius: 4px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(opp.court_or_notary || '')}">
                                ${escapeHtml(opp.court_or_notary || 'Notaría / Juzgado')}
                            </span>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px;">
                            <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                <i data-lucide="file-text" style="width: 13px; height: 13px; color: #38bdf8;"></i> Autos / Cuota:
                            </span>
                            <span style="color: #38bdf8; font-weight: 800; font-size: 0.76rem;">
                                ${escapeHtml(opp.expediente_num || 'TEJU')} • <strong>${ownershipFormatted}%</strong>
                            </span>
                        </div>
                    </div>
                `;
            } else if (opp.source_type === 'market') {
                actionBtnLabel = `Ver en ${escapeHtml(opp.primary_portal || 'Portal')}`;
                actionBtnUrl = opp.portal_url || opp.boe_url || '#';

                dateSubastaHeader = `
                    <div style="font-size: 0.76rem; color: #34d399; margin-top: 4px; display: flex; align-items: center; gap: 4px;">
                        <i data-lucide="store" style="width: 12px; height: 12px; display: inline;"></i> Portal: <strong>${escapeHtml(opp.primary_portal || 'Idealista')}</strong> • Publicado: ${escapeHtml(opp.created_at || 'Reciente')}
                    </div>
                `;

                if (opp.has_pgou_synergy) {
                    urbanismHtml = `
                        <div class="card-urbanism-compact" style="background: rgba(168, 85, 247, 0.12); padding: 8px 12px; border-radius: 6px; margin: 8px 0; border: 1px solid rgba(168, 85, 247, 0.4); display: flex; flex-direction: column; gap: 6px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="font-size: 0.76rem; color: #c084fc; font-weight: 700; display: flex; align-items: center; gap: 6px;">
                                    <i data-lucide="crosshair" style="width: 13px; height: 13px; color: #c084fc;"></i> 🎯 Sinergia PGOU:
                                </span>
                                <span style="background: rgba(168, 85, 247, 0.25); color: #f3e8ff; font-weight: 800; font-size: 0.74rem; padding: 2px 8px; border-radius: 4px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(opp.pgou_title || '')}">
                                    ${escapeHtml(opp.pgou_title || 'Sector')}
                                </span>
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 4px;">
                                <span style="font-size: 0.74rem; color: #94a3b8;">Revalorización prevista:</span>
                                <span style="color: #34d399; font-weight: 800; font-size: 0.76rem;">${escapeHtml(opp.pgou_uplift || 'Plusvalía Urbanística')}</span>
                            </div>
                        </div>
                    `;
                } else {
                    urbanismHtml = `
                        <div class="card-urbanism-compact" style="background: rgba(15, 23, 42, 0.5); padding: 8px 12px; border-radius: 6px; margin: 8px 0; border: 1px solid rgba(255, 255, 255, 0.08); display: flex; flex-direction: column; gap: 6px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                    <i data-lucide="store" style="width: 13px; height: 13px; color: #34d399;"></i> Mercado Residencial:
                                </span>
                                <span style="background: rgba(16, 185, 129, 0.15); color: #34d399; font-weight: 800; font-size: 0.78rem; padding: 2px 8px; border-radius: 4px;">
                                    VENTA DIRECTA
                                </span>
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px;">
                                <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                    <i data-lucide="layers" style="width: 13px; height: 13px; color: #38bdf8;"></i> Precios Distintos:
                                </span>
                                <span style="color: #38bdf8; font-weight: 800; font-size: 0.76rem;">
                                    ${escapeHtml(opp.x_publicacion || 'x1')} (${opp.distinct_prices_count || 1} precios)
                                </span>
                            </div>
                        </div>
                    `;
                }
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
                        ${opp.idufir ? `
                        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px;">
                            <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                <i data-lucide="shield-check" style="width: 13px; height: 13px; color: #c084fc;"></i> IDUFIR / CRU:
                            </span>
                            <span style="background: rgba(168, 85, 247, 0.15); color: #c084fc; font-weight: 800; font-size: 0.74rem; padding: 2px 8px; border-radius: 4px; letter-spacing: 0.5px;">
                                ${escapeHtml(opp.idufir)}
                            </span>
                        </div>
                        ` : ''}
                        ${opp.is_lotes ? `
                        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px;">
                            <span style="font-size: 0.76rem; color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                <i data-lucide="package" style="width: 13px; height: 13px; color: #818cf8;"></i> Modalidad:
                            </span>
                            <span style="background: rgba(99, 102, 241, 0.2); color: #a5b4fc; font-weight: 800; font-size: 0.74rem; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(99, 102, 241, 0.3);">
                                ${escapeHtml(opp.lote_badge || '📦 LOTE INDEPENDIENTE')}
                            </span>
                        </div>
                        ` : ''}
                    </div>
                `;
            }

            return `
                <div class="deal-card ${opp.is_new ? 'deal-card-new' : ''}" data-opp-id="${opp.id}" data-opp-index="${idx}" onclick="highlightOpportunityPin(${opp.id}, ${opp.lat || 'null'}, ${opp.lon || 'null'})">
                    <div class="card-image-banner" id="card-carousel-${idx}" style="position: relative; height: 160px; overflow: hidden; border-radius: var(--radius-sm); background: #020617;" onclick="openPropertyDetailModal(${idx}); event.stopPropagation();">
                        <div class="card-carousel-img" id="card-carousel-img-${idx}" style="position: absolute; inset: 0; background-image: url('${mainImg}'); background-size: cover; background-position: center; transition: background-image 0.25s ease;"></div>
                        ${imgCount > 1 ? `
                            <button type="button" class="card-carousel-btn card-carousel-prev" onclick="window.cardCarouselNav(event, ${idx}, -1)" title="Foto anterior" aria-label="Foto anterior">
                                <i data-lucide="chevron-left"></i>
                            </button>
                            <button type="button" class="card-carousel-btn card-carousel-next" onclick="window.cardCarouselNav(event, ${idx}, 1)" title="Foto siguiente" aria-label="Foto siguiente">
                                <i data-lucide="chevron-right"></i>
                            </button>
                            <div class="card-carousel-counter" id="card-carousel-counter-${idx}">
                                <i data-lucide="camera" style="width: 11px; height: 11px;"></i> <span id="card-carousel-num-${idx}">1</span>/${imgCount}
                            </div>
                        ` : ''}
                        <div class="card-image-overlay" style="position: absolute; inset: 0; background: linear-gradient(to top, rgba(15, 23, 42, 0.9) 0%, transparent 60%); display: flex; justify-content: space-between; align-items: flex-start; padding: 10px; pointer-events: none;">
                            ${opp.source_type === 'pgou' ? `
                                <div style="display: flex; gap: 5px; align-items: center; flex-wrap: wrap;">
                                    <span class="badge-strategy" style="background: #9333ea; color: #fff; font-weight: 700; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">📐 DESARROLLO SUELO</span>
                                    ${opp.is_new ? '<span class="badge-new-pill" title="Nueva oportunidad incorporada recientemente"><i data-lucide="sparkles"></i> New!</span>' : ''}
                                </div>
                                <span class="badge-discount" style="background: rgba(168, 85, 247, 0.25); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); font-weight: 700;">${escapeHtml(opp.planning_status || 'PGOU')}</span>
                            ` : (opp.source_type === 'edictos' ? `
                                <div style="display: flex; gap: 5px; align-items: center; flex-wrap: wrap;">
                                    <span class="badge-strategy" style="background: ${opp.category === 'HERENCIA_YACENTE' ? '#b45309' : '#4338ca'}; color: #fff; font-weight: 700; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">${opp.category === 'HERENCIA_YACENTE' ? '⚖️ HERENCIA YACENTE' : '👥 COSA COMÚN'}</span>
                                    ${opp.is_new ? '<span class="badge-new-pill" title="Nueva oportunidad incorporada recientemente"><i data-lucide="sparkles"></i> New!</span>' : ''}
                                </div>
                                ${opp.discount_percentage > 0 ? `
                                    <span class="badge-discount" style="background: #10b981; color: #fff; font-weight: 800; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">-${formatNumber(opp.discount_percentage, 0)}% Descuento</span>
                                ` : `
                                    <span class="badge-discount" style="background: rgba(100, 116, 139, 0.4); color: #cbd5e1; font-weight: 600; border: 1px solid rgba(148, 163, 184, 0.25);">Edicto s/ Tipo</span>
                                `}
                            ` : (opp.source_type === 'market' ? `
                                <div style="display: flex; gap: 5px; align-items: center; flex-wrap: wrap;">
                                    <span class="badge-strategy" style="background: #059669; color: #fff; font-weight: 700; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">${subastaTypeBadge}</span>
                                    ${opp.is_new ? '<span class="badge-new-pill" title="Nueva oportunidad incorporada recientemente"><i data-lucide="sparkles"></i> New!</span>' : ''}
                                    <span class="badge-xpublicacion" title="Contabiliza publicaciones con precios distintos"><i data-lucide="layers" style="width: 12px; height: 12px;"></i> xPublicación: ${escapeHtml(opp.x_publicacion || 'x1')}</span>
                                    ${opp.has_pgou_synergy ? `<span class="badge-synergy" title="Inmueble con Sinergia Urbanística PGOU"><i data-lucide="crosshair" style="width: 12px; height: 12px;"></i> 🎯 SINERGIA PGOU</span>` : ''}
                                </div>
                                ${opp.discount_percentage > 0 ? `
                                    <span class="badge-discount" style="background: #10b981; color: #fff; font-weight: 800; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">-${formatNumber(opp.discount_percentage, 1)}% dto.</span>
                                ` : `
                                    <span class="badge-discount" style="background: rgba(100, 116, 139, 0.4); color: #cbd5e1; font-weight: 600; border: 1px solid rgba(148, 163, 184, 0.25);">Precio Inicial</span>
                                `}
                            ` : `
                                <div style="display: flex; gap: 5px; align-items: center; flex-wrap: wrap;">
                                    <span class="badge-strategy" style="background: ${subastaBadgeBg}; color: #fff; font-weight: 700; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">${subastaTypeBadge}</span>
                                    ${opp.is_new ? '<span class="badge-new-pill" title="Nueva oportunidad incorporada recientemente"><i data-lucide="sparkles"></i> New!</span>' : ''}
                                    ${opp.is_lotes ? `
                                        <span class="badge-lote" title="Subasta por lotes independientes. Puja y adjudicación separada.">
                                             <i data-lucide="package"></i> LOTE ${opp.lot_number || 1}
                                        </span>
                                    ` : ''}
                                </div>
                                ${opp.is_surface_missing ? `
                                    <span class="badge-discount" style="background: rgba(245, 158, 11, 0.25); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.5); font-weight: 700; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">⚠️ Requiere Nota Simple</span>
                                ` : (opp.discount_percentage > 0 ? `
                                    <span class="badge-discount" style="background: #10b981; color: #fff; font-weight: 800; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">-${formatNumber(opp.discount_percentage, 0)}% Descuento</span>
                                ` : `
                                    <span class="badge-discount" style="background: rgba(100, 116, 139, 0.4); color: #cbd5e1; font-weight: 600; border: 1px solid rgba(148, 163, 184, 0.25);">Subasta s/ Tipo</span>
                                `)}
                            `))}
                        </div>
                    </div>

                    <div class="card-content-compact">
                        <h3 class="card-title" onclick="openPropertyDetailModal(${idx}); event.stopPropagation();" title="${escapeHtml(opp.title)}">${escapeHtml(opp.title)}</h3>
                        
                        <div class="card-location">
                            <a href="javascript:void(0)" class="address-maps-link" onclick="openGoogleMapsForCard(${idx}, event)" title="Ver en Google Maps Satélite">
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
                                <span class="fin-lbl">${opp.source_type === 'market' ? 'Precio de Venta' : (opp.source_type === 'pgou' ? 'Precio Adquisición' : (opp.source_type === 'edictos' ? 'Salida / Tipo' : 'Valor Subasta'))}</span>
                                <span class="fin-val val-tasacion" style="font-size: 0.95rem; font-weight: 700; color: ${opp.source_type === 'market' ? '#38bdf8' : '#f8fafc'};">${formatCurrency(opp.source_type === 'market' ? opp.listing_price : refVal)}</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">${opp.source_type === 'market' ? 'Bajada Anuncio' : 'Valor Mercado Estimado'}</span>
                                <span class="fin-val" style="font-size: 0.88rem; font-weight: 700; color: ${opp.source_type === 'market' ? (opp.price_drop_amount > 0 ? '#4ade80' : '#cbd5e1') : (isSurfaceMissing ? '#f59e0b' : '#38bdf8')};">
                                    ${opp.source_type === 'market' ? (opp.price_drop_amount > 0 ? `-${formatNumber(opp.price_drop_percentage, 1)}% (-${formatCurrency(opp.price_drop_amount)})` : '0% (Salida)') : (isSurfaceMissing ? '<span style="font-size: 0.76rem; font-weight: 700;">Pendiente Nota Simple</span>' : formatCurrency(estimatedMktVal))}
                                </span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl">Superficie (${opp.source_type === 'market' ? 'Construida' : (opp.source_type === 'pgou' ? 'Suelo m²s' : (opp.source_type === 'edictos' ? 'Útil / Cuota' : 'Cuota Real'))})</span>
                                <span class="fin-val" style="font-size: 0.88rem; color: #f8fafc; font-weight: 600;">${surfaceDisplay}</span>
                            </div>
                            <div class="fin-cell">
                                <span class="fin-lbl" style="color: ${opp.source_type === 'pgou' ? getScoreColor(opp.overall_score) : '#94a3b8'}; font-weight: 700;">${opp.source_type === 'pgou' ? 'SCORE GENERAL ENTORNO' : (opp.source_type === 'edictos' ? 'Margen Bruto Est.' : (opp.source_type === 'market' ? 'Margen vs Ref. Barrio' : 'Beneficio / Margen Est.'))}</span>
                                <span class="fin-val val-profit" style="font-size: 0.88rem; font-weight: 800; color: ${opp.source_type === 'pgou' ? getScoreColor(opp.overall_score) : (profitVal >= 0 ? '#4ade80' : '#f87171')};">
                                    ${opp.source_type === 'pgou' ? `${formatScore(opp.overall_score)} / 100 pts` : (opp.source_type === 'market' ? `${profitFormatted} ${opp.discount_vs_market > 0 ? `<span style="font-size: 0.74rem; font-weight: 700; color: #38bdf8;">(-${formatNumber(opp.discount_vs_market, 1)}% dto. mkt)</span>` : ''}` : profitFormatted)}
                                </span>
                            </div>
                        </div>

                        <div class="card-bottom-row" style="display: flex; flex-direction: column; gap: 8px; align-items: stretch; width: 100%;">
                            <div class="scores-compact" style="display: flex; flex-wrap: wrap; gap: 4px; align-items: center;">
                                <span class="score-chip" title="Score Global Oportunidad" style="${getScoreBgStyle(opp.overall_score)}">Score: <strong>${formatScore(opp.overall_score)}</strong></span>
                                ${renderBtlBadge(opp, 'card')}
                                ${opp.source_type === 'pgou' ? '' : `<span class="score-chip" title="Score Descuento vs Mercado" style="${getScoreBgStyle((opp.property_m2_price && opp.property_m2_price > 0) ? (opp.discount_score || 0) : 0)}">Desc: <strong>${formatScore((opp.property_m2_price && opp.property_m2_price > 0) ? (opp.discount_score || 0) : 0)}</strong></span>`}
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
                                ${actionBtnUrl && actionBtnUrl !== '#' ? `
                                <a href="${actionBtnUrl}" target="_blank" rel="noopener" class="btn-boe-xs" onclick="event.stopPropagation();">
                                    ${actionBtnLabel} <i data-lucide="external-link" style="width: 11px; height: 11px;"></i>
                                </a>
                                ` : ''}
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
        let opp = null;
        if (typeof index === 'object' && index !== null) {
            opp = index;
        } else if (state.filteredOpportunities && state.filteredOpportunities[index]) {
            opp = state.filteredOpportunities[index];
        } else if (state.allOpportunities && state.allOpportunities[index]) {
            opp = state.allOpportunities[index];
        } else if (window._lastOpportunities && window._lastOpportunities[index]) {
            opp = window._lastOpportunities[index];
        }
        if (!opp) return;

        window._activeModalOpp = opp;

        const modal = document.getElementById('modal-property-detail');
        const body = document.getElementById('modal-prop-body');
        const images = (opp.images && opp.images.length > 0) ? opp.images : [];
        const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality}, ${opp.province}`;

        const totalSurface = (opp.surface_m2 && opp.surface_m2 > 0) ? opp.surface_m2 : null;
        const effectiveSurface = (opp.effective_surface_m2 && opp.effective_surface_m2 > 0) ? opp.effective_surface_m2 : totalSurface;
        const ownershipPct = (opp.ownership_percentage && opp.ownership_percentage > 0) ? opp.ownership_percentage : 100;
        const ownershipFormatted = formatExactPercentage(ownershipPct);

        const isSurfaceMissingModal = Boolean(opp.is_surface_missing || !effectiveSurface);
        let surfaceDisplayModal = '<span style="color: #f59e0b; font-weight: 700; font-size: 0.95rem;">⚠️ Sin constancia en BOE</span>';
        if (effectiveSurface && !isSurfaceMissingModal) {
            const estBadgeModal = opp.is_surface_estimated ? '<span style="font-size: 0.74rem; color: #c084fc; font-weight: 700; margin-left: 4px;" title="Superficie estimada">(est.)</span>' : '';
            if (ownershipPct < 100 && totalSurface) {
                surfaceDisplayModal = `
                    <div style="font-size: 1.1rem; font-weight: 700; color: #f8fafc;">${formatNumber(effectiveSurface, 2)} m² ${estBadgeModal}</div>
                    <div style="font-size: 0.72rem; color: #38bdf8; font-weight: 600; margin-top: 2px;">(${ownershipFormatted}% de ${formatNumber(totalSurface, 2)} m² total)</div>
                `;
            } else {
                surfaceDisplayModal = `<div style="font-size: 1.1rem; font-weight: 700; color: #f8fafc;">${formatNumber(effectiveSurface, 2)} m² ${estBadgeModal}</div>`;
            }
        }

        const propertyM2Display = (opp.property_m2_price && opp.property_m2_price > 0) ? `${formatCurrency(opp.property_m2_price)}/m²` : '-';
        let districtName = '';
        if (opp.census_tract_data && opp.census_tract_data.district) {
            districtName = opp.census_tract_data.district;
        } else if (opp.area_m2_price_label && opp.area_m2_price_label.includes('[')) {
            const m = opp.area_m2_price_label.match(/\[(.*?)\]/);
            districtName = m ? m[1] : opp.area_m2_price_label;
        } else if (opp.district) {
            districtName = opp.district;
        } else if (opp.neighborhood) {
            districtName = opp.neighborhood;
        } else {
            districtName = opp.locality ? `${opp.locality}${opp.province && opp.province !== opp.locality ? ' (' + opp.province + ')' : ''}` : (opp.province || 'Zona');
        }

        if (opp.postal_code && !districtName.includes(opp.postal_code)) {
            districtName = `${districtName} (CP ${opp.postal_code})`;
        }
        const areaM2Display = `${formatCurrency(opp.area_m2_price)}/m²`;
        const discountScoreVal = (opp.property_m2_price && opp.property_m2_price > 0) ? (opp.discount_score || 0) : 0;
        const landType = opp.land_type || 'URBANO';

        let liensDetailHtml = '';
        let urbanismDetail = '';
        let dateSubastaHeaderModal = '';
        let extBtnLabelModal = 'Abrir Expediente Oficial en BOE';
        let extBtnUrlModal = opp.boe_url || opp.gazette_url || '#';
        if (opp.is_lotes) {
            extBtnLabelModal = `📦 Abrir Ficha Lote ${opp.lot_number || 1} en BOE Oficial`;
            if (opp.lote_boe_url) {
                extBtnUrlModal = opp.lote_boe_url;
            }
        }

        if (opp.source_type === 'pgou') {
            extBtnLabelModal = `Abrir Boletín Oficial (${opp.gazette_source ? opp.gazette_source.split(' ')[0] : 'BOCM'})`;
            extBtnUrlModal = opp.gazette_url || opp.boe_url || '#';

            dateSubastaHeaderModal = `
                <div style="font-size: 0.88rem; color: #c084fc; display: flex; align-items: center; gap: 6px; padding-left: 2px;">
                    <i data-lucide="layers" style="width: 15px; height: 15px; color: #c084fc;"></i>
                    <span>Ámbito / Expediente: <strong>${escapeHtml(opp.gazette_code || opp.planning_status || 'Planeamiento Urbanístico')}</strong></span>
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
                        <i data-lucide="compass" style="width: 16px; height: 16px; color: #c084fc;"></i> Uso Propuesto:
                    </span>
                    <span class="badge" style="background: ${landUseBadgeBg}; color: ${landUseBadgeColor}; font-weight: 800; font-size: 0.88rem; padding: 4px 12px; border-radius: 6px; text-transform: uppercase;">
                        ${landUseLabel}
                    </span>
                </div>
            `;

            // PGOU Milestones Stepper
            const milestones = opp.milestones || [
                { phase: "Aprobación Inicial PGOU", status: "COMPLETED", timeframe: "Concluido", uplift: "x1.25" },
                { phase: "Aprobación Definitiva (BOCM)", status: "CURRENT", timeframe: "Concluido", uplift: "x1.85" },
                { phase: "Inscripción Proyecto Reparcelación", status: "PENDING", timeframe: "3-6 meses", uplift: "x2.40" },
                { phase: "Licencia Directa / Obra Nueva", status: "PENDING", timeframe: "9-12 meses", uplift: "x3.00" }
            ];

            const milestonesStepsHtml = milestones.map((m) => {
                let isDone = m.status === 'COMPLETED';
                let isCurrent = m.status === 'CURRENT';
                let statusBg = isDone ? 'rgba(34, 197, 94, 0.15)' : (isCurrent ? 'rgba(168, 85, 247, 0.25)' : 'rgba(255, 255, 255, 0.04)');
                let statusColor = isDone ? '#4ade80' : (isCurrent ? '#c084fc' : '#94a3b8');
                let badgeText = isDone ? '✔ COMPLETADO' : (isCurrent ? '⚡ EN PROCESO' : '⌛ PENDIENTE');

                return `
                    <div style="flex: 1; min-width: 130px; display: flex; flex-direction: column; align-items: center; justify-content: space-between; text-align: center; padding: 10px 8px; background: ${statusBg}; border: 1px solid ${statusColor}55; border-radius: 8px;">
                        <span style="font-size: 0.72rem; color: ${statusColor}; font-weight: 800; text-transform: uppercase; margin-bottom: 6px;">${badgeText}</span>
                        <div style="display: flex; align-items: center; justify-content: center; min-height: 3.6em; line-height: 1.2em; margin-bottom: 6px; width: 100%;">
                            <strong style="font-size: 0.82rem; color: #f8fafc; text-align: center;">${escapeHtml(m.phase)}</strong>
                        </div>
                        <span style="font-size: 0.75rem; color: #38bdf8; font-weight: 800; display: block; margin-bottom: 2px;">Reval. ${m.uplift}</span>
                        <span style="font-size: 0.72rem; color: #cbd5e1;">⏱️ ${escapeHtml(m.timeframe)}</span>
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
                            <i data-lucide="git-commit" style="width: 18px; height: 18px; color: #c084fc;"></i> Hitos de Planeamiento
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
                            <span style="font-size: 0.65rem; color: #38bdf8; display: block; margin-top: 2px;">(*): ${escapeHtml(opp.urbanization_cost_source || 'Promedio Meso CP')}</span>
                        </div>
                        <div>
                            <span style="display: block; font-size: 0.75rem; color: #94a3b8; font-weight: 600;">Presupuesto Urb. Total</span>
                            <strong style="color: #f59e0b; font-size: 0.95rem;">${totalUrbCost}</strong>
                        </div>
                        <div>
                            <span style="display: block; font-size: 0.75rem; color: #38bdf8; font-weight: 700;">Repercusión Total (€/m²t)</span>
                            <strong style="color: #38bdf8; font-size: 1.05rem; font-weight: 800;">${landRepercussion}/m²t (*)</strong>
                        </div>
                    </div>

                    <!-- Registry & Compensation Board Status -->
                    <div style="background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.3); border-radius: 8px; padding: 12px 14px; display: flex; align-items: center; justify-content: space-between; font-size: 0.86rem;">
                        <div style="display: flex; align-items: center; gap: 8px; color: #4ade80;">
                            <i data-lucide="shield-check" style="width: 18px; height: 18px;"></i>
                            <strong style="color: #f8fafc;">Estatus:</strong>
                        </div>
                        <span style="color: #cbd5e1; font-weight: 600; text-align: right; font-size: 0.85rem;">${escapeHtml(opp.reparcelacion_status || 'Junta Constituida / En Tramitación')}</span>
                    </div>
                    <div style="font-size: 0.74rem; color: #94a3b8; margin-top: 6px; font-style: italic;">
                        ℹ️ Verificación gratuita realizada mediante cruce de Sede Electrónica del Catastro (WFS) y anuncios obligatorios de edictos oficiales.
                    </div>
                </div>
            `;
        } else if (opp.source_type === 'edictos') {
            const isHerencia = opp.category === 'HERENCIA_YACENTE';
            extBtnLabelModal = isHerencia ? 'Abrir Anuncio Oficial en TEJU - BOE' : 'Abrir Subasta Judicial de Condominio';
            extBtnUrlModal = opp.boe_url || (opp.teju_boe_code && /^BOE-[A-Z]-\d{4}-\d+$/i.test(opp.teju_boe_code) ? `https://www.boe.es/diario_boe/txt.php?id=${opp.teju_boe_code}` : (opp.expediente_num ? `https://www.boe.es/buscar/edictos_judiciales.php?campo%5B0%5D=DOC&dato%5B0%5D=${encodeURIComponent(opp.expediente_num)}&accion=Buscar` : 'https://www.boe.es/buscar/edictos_judiciales.php'));

            dateSubastaHeaderModal = `
                <div style="font-size: 0.88rem; color: ${isHerencia ? '#fbbf24' : '#818cf8'}; display: flex; align-items: center; gap: 6px; padding-left: 2px;">
                    <i data-lucide="scale" style="width: 15px; height: 15px;"></i>
                    <span>Expediente / Edicto: <strong>${escapeHtml(opp.expediente_num || opp.teju_boe_code || 'Edicto Judicial/Notarial')}</strong></span>
                </div>
            `;

            urbanismDetail = `
                <div style="margin-top: 14px; padding: 12px 16px; background: rgba(15, 23, 42, 0.65); border: 1px solid ${isHerencia ? 'rgba(251, 191, 36, 0.3)' : 'rgba(129, 140, 248, 0.3)'}; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; font-size: 0.9rem; width: 100%;">
                    <span style="color: #cbd5e1; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                        <i data-lucide="landmark" style="width: 16px; height: 16px; color: ${isHerencia ? '#fbbf24' : '#818cf8'};"></i> Origen Legal:
                    </span>
                    <span class="badge" style="background: ${isHerencia ? 'rgba(251, 191, 36, 0.2)' : 'rgba(129, 140, 248, 0.2)'}; color: ${isHerencia ? '#fbbf24' : '#818cf8'}; font-weight: 800; font-size: 0.85rem; padding: 4px 12px; border-radius: 6px;">
                        ${escapeHtml(opp.court_or_notary || 'Juzgado / Notaría')}
                    </span>
                </div>
            `;

            // Edictos Milestones Stepper
            const milestones = opp.milestones || [
                { phase: "Publicación Edicto TEJU", status: "COMPLETED", timeframe: "Concluido", uplift: "Base" },
                { phase: "Fin Plazo Comparecencia Herederos", status: "CURRENT", timeframe: "30 días", uplift: "+15%" },
                { phase: "Declaración Abintestato / Subasta", status: "PENDING", timeframe: "2-3 meses", uplift: "+35%" },
                { phase: "Adjudicación y Posesión Judicial", status: "PENDING", timeframe: "4-6 meses", uplift: "+50%" }
            ];

            const milestonesStepsHtml = milestones.map((m) => {
                let isDone = m.status === 'COMPLETED';
                let isCurrent = m.status === 'CURRENT';
                let statusBg = isDone ? 'rgba(34, 197, 94, 0.15)' : (isCurrent ? 'rgba(251, 191, 36, 0.25)' : 'rgba(255, 255, 255, 0.04)');
                let statusColor = isDone ? '#4ade80' : (isCurrent ? '#fbbf24' : '#94a3b8');
                let badgeText = isDone ? '✔ COMPLETADO' : (isCurrent ? '⚡ EN PROCESO' : '⌛ PENDIENTE');

                return `
                    <div style="flex: 1; min-width: 130px; display: flex; flex-direction: column; align-items: center; justify-content: space-between; text-align: center; padding: 10px 8px; background: ${statusBg}; border: 1px solid ${statusColor}55; border-radius: 8px;">
                        <span style="font-size: 0.72rem; color: ${statusColor}; font-weight: 800; text-transform: uppercase; margin-bottom: 6px;">${badgeText}</span>
                        <div style="display: flex; align-items: center; justify-content: center; min-height: 3.6em; line-height: 1.2em; margin-bottom: 6px; width: 100%;">
                            <strong style="font-size: 0.82rem; color: #f8fafc; text-align: center;">${escapeHtml(m.phase)}</strong>
                        </div>
                        <span style="font-size: 0.75rem; color: #38bdf8; font-weight: 800; display: block; margin-bottom: 2px;">Margen ${escapeHtml(m.uplift || '')}</span>
                        <span style="font-size: 0.72rem; color: #cbd5e1;">⏱️ ${escapeHtml(m.timeframe)}</span>
                    </div>
                `;
            }).join('');

            liensDetailHtml = `
                <!-- Edictos & Proindivisos Module: Milestones, Legal Proceedings & Strategy -->
                <div style="margin-top: 16px; padding: 16px; background: rgba(15, 23, 42, 0.75); border: 1px solid ${isHerencia ? 'rgba(251, 191, 36, 0.35)' : 'rgba(129, 140, 248, 0.35)'}; border-radius: 10px; width: 100%;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px;">
                        <span style="font-size: 0.98rem; font-weight: 700; color: #f8fafc; display: flex; align-items: center; gap: 8px;">
                            <i data-lucide="git-commit" style="width: 18px; height: 18px; color: ${isHerencia ? '#fbbf24' : '#818cf8'};"></i> Fases del Procedimiento Legal
                        </span>
                        <span class="badge" style="background: ${isHerencia ? 'rgba(251, 191, 36, 0.2)' : 'rgba(129, 140, 248, 0.2)'}; color: ${isHerencia ? '#fbbf24' : '#818cf8'}; font-weight: 800; font-size: 0.8rem; padding: 4px 10px; border-radius: 6px;">
                            ${escapeHtml(opp.category_label || (isHerencia ? '⚖️ Herencia Yacente' : '👥 Proindiviso'))}
                        </span>
                    </div>

                    <!-- Milestones Stepper -->
                    <div style="display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap;">
                        ${milestonesStepsHtml}
                    </div>

                    <!-- Legal & Operational Summary -->
                    <div style="background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; font-size: 0.86rem; color: #e2e8f0; line-height: 1.45;">
                        <div style="margin-bottom: 6px;"><strong style="color: #fbbf24;">Estado Jurídico:</strong> ${escapeHtml(opp.legal_status || 'En tramitación procesal')}</div>
                        <div><strong style="color: #38bdf8;">Tesis Operativa:</strong> ${escapeHtml(opp.opportunity_summary || 'Monitoreo preventivo mediante edictos judiciales y notariales')}</div>
                    </div>
                    <div style="font-size: 0.74rem; color: #94a3b8; margin-top: 6px; font-style: italic;">
                        ℹ️ Monitoreo preventivo de Edictos Judiciales Únicos (TEJU-BOE) y subastas de disolución de condominio (Art. 400 CC) sin coste en notas simples registrales.
                    </div>
                </div>
            `;
        } else if (opp.source_type === 'market') {
            extBtnLabelModal = `Ver Inmueble en ${escapeHtml(opp.primary_portal || 'Portal Inmobiliario')}`;
            extBtnUrlModal = opp.portal_url || opp.boe_url || '#';

            dateSubastaHeaderModal = `
                <div style="font-size: 0.88rem; color: #34d399; display: flex; align-items: center; gap: 6px; padding-left: 2px;">
                    <i data-lucide="store" style="width: 15px; height: 15px;"></i>
                    <span>Portal Principal: <strong>${escapeHtml(opp.primary_portal || 'Idealista')}</strong> • Modalidad: <strong>Venta Directa de Mercado</strong></span>
                </div>
            `;

            // Publications multichannel table (Matiz 2)
            const pubs = opp.publications || [];
            let pubsRowsHtml = '';
            let pubsCardsHtml = '';
            if (pubs.length > 0) {
                pubsRowsHtml = pubs.map(p => {
                    const isMin = p.is_minimum || p.price === opp.listing_price;
                    const diffPrice = p.price - opp.listing_price;
                    return `
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.82rem;">
                            <td style="padding: 8px 10px; font-weight: 700; color: #f8fafc; white-space: nowrap;">
                                ${escapeHtml(p.portal || 'Portal')}
                            </td>
                            <td style="padding: 8px 10px; font-weight: 800; color: ${isMin ? '#34d399' : '#cbd5e1'}; white-space: nowrap;">
                                ${formatCurrency(p.price)}
                            </td>
                            <td style="padding: 8px 10px; white-space: nowrap;">
                                ${isMin 
                                    ? '<span style="background: rgba(16, 185, 129, 0.2); color: #34d399; padding: 2px 8px; border-radius: 4px; font-weight: 800; font-size: 0.72rem; border: 1px solid rgba(16, 185, 129, 0.3); white-space: nowrap;">🏆 MENOR PRECIO</span>' 
                                    : `<span style="color: #f87171; font-size: 0.76rem; font-weight: 600; white-space: nowrap;">+${formatCurrency(diffPrice)}</span>`}
                            </td>
                            <td style="padding: 8px 10px; color: #94a3b8; font-size: 0.78rem; white-space: nowrap;">
                                ${escapeHtml(p.agency || 'Agencia')}
                            </td>
                            <td style="padding: 8px 10px; text-align: right; white-space: nowrap;">
                                <a href="${p.url || '#'}" target="_blank" rel="noopener noreferrer" class="btn-boe-xs" style="padding: 3px 8px; font-size: 0.72rem; display: inline-flex; align-items: center; gap: 4px; white-space: nowrap;">
                                    Ver en ${escapeHtml(p.portal || 'Portal')} <i data-lucide="external-link" style="width: 10px; height: 10px;"></i>
                                </a>
                            </td>
                        </tr>
                    `;
                }).join('');

                pubsCardsHtml = pubs.map(p => {
                    const isMin = p.is_minimum || p.price === opp.listing_price;
                    const diffPrice = p.price - opp.listing_price;
                    return `
                        <div class="multicanal-card-row" style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; box-sizing: border-box;">
                            <!-- Fila 1: Portal y Estado -->
                            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255, 255, 255, 0.06); padding-bottom: 6px; margin-bottom: 8px;">
                                <div style="font-weight: 800; font-size: 0.92rem; color: #f8fafc; display: flex; align-items: center; gap: 6px; white-space: nowrap;">
                                    <i data-lucide="store" style="width: 15px; height: 15px; color: #38bdf8;"></i>
                                    <span>${escapeHtml(p.portal || 'Portal')}</span>
                                </div>
                                <div>
                                    ${isMin 
                                        ? '<span style="background: rgba(16, 185, 129, 0.2); color: #34d399; padding: 2px 8px; border-radius: 4px; font-weight: 800; font-size: 0.72rem; border: 1px solid rgba(16, 185, 129, 0.3); white-space: nowrap;">🏆 MENOR PRECIO</span>' 
                                        : `<span style="color: #f87171; font-size: 0.76rem; font-weight: 600; white-space: nowrap;">+${formatCurrency(diffPrice)} vs mín.</span>`}
                                </div>
                            </div>
                            <!-- Fila 2: Celdas uniformes en fila (50% / 50%) -->
                            <div class="two-cols-equal-grid" style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-bottom: 8px;">
                                <div style="background: rgba(0, 0, 0, 0.2); padding: 6px 8px; border-radius: 6px; display: flex; flex-direction: column; justify-content: center; min-height: 48px; box-sizing: border-box;">
                                    <span style="font-size: 0.70rem; color: #94a3b8; text-transform: uppercase; font-weight: 600; white-space: nowrap; margin-bottom: 2px;">Precio Anunciado</span>
                                    <strong style="font-size: 0.98rem; font-weight: 800; color: ${isMin ? '#34d399' : '#cbd5e1'}; white-space: nowrap;">
                                        ${formatCurrency(p.price)}
                                    </strong>
                                </div>
                                <div style="background: rgba(0, 0, 0, 0.2); padding: 6px 8px; border-radius: 6px; display: flex; flex-direction: column; justify-content: center; min-height: 48px; box-sizing: border-box;">
                                    <span style="font-size: 0.70rem; color: #94a3b8; text-transform: uppercase; font-weight: 600; white-space: nowrap; margin-bottom: 2px;">Comercializadora</span>
                                    <span style="font-size: 0.82rem; color: #e2e8f0; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(p.agency || 'Agencia')}">
                                        ${escapeHtml(p.agency || 'Agencia')}
                                    </span>
                                </div>
                            </div>
                            <!-- Fila 3: Botón Enlace directo completo sin cortes -->
                            <div>
                                <a href="${p.url || '#'}" target="_blank" rel="noopener noreferrer" class="btn-boe-xs" style="width: 100%; box-sizing: border-box; justify-content: center; padding: 7px 12px; font-size: 0.82rem; font-weight: 700; display: flex; align-items: center; gap: 6px; white-space: nowrap; border-radius: 6px; text-decoration: none;">
                                    <span>Ver publicación en ${escapeHtml(p.portal || 'Portal')}</span> <i data-lucide="external-link" style="width: 13px; height: 13px;"></i>
                                </a>
                            </div>
                        </div>
                    `;
                }).join('');
            } else {
                pubsRowsHtml = `
                    <tr>
                        <td colspan="5" style="padding: 10px; text-align: center; color: #94a3b8; font-size: 0.8rem; white-space: nowrap;">
                            Publicación única detectada en ${escapeHtml(opp.primary_portal || 'Portal')} por ${formatCurrency(opp.listing_price)}
                        </td>
                    </tr>
                `;
                pubsCardsHtml = `
                    <div style="padding: 12px; text-align: center; color: #94a3b8; font-size: 0.82rem; background: rgba(0,0,0,0.2); border-radius: 6px;">
                        Publicación única detectada en ${escapeHtml(opp.primary_portal || 'Portal')} por ${formatCurrency(opp.listing_price)}
                    </div>
                `;
            }

            // Sinergia PGOU Banner & Section (Matiz 3)
            let synergySectionHtml = '';
            if (opp.has_pgou_synergy) {
                synergySectionHtml = `
                    <div style="margin-top: 14px; padding: 14px 16px; background: rgba(168, 85, 247, 0.12); border: 1px solid rgba(168, 85, 247, 0.45); border-radius: 10px; width: 100%; box-sizing: border-box;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px; border-bottom: 1px solid rgba(168, 85, 247, 0.25); padding-bottom: 8px;">
                            <span style="font-size: 0.95rem; font-weight: 800; color: #f3e8ff; display: flex; align-items: center; gap: 8px;">
                                <i data-lucide="crosshair" style="width: 18px; height: 18px; color: #c084fc;"></i> 🎯 SINERGIA URBANÍSTICA DETECTADA: ${escapeHtml(opp.pgou_title || 'Sector PGOU')}
                            </span>
                            <span style="background: rgba(168, 85, 247, 0.25); color: #c084fc; font-weight: 800; font-size: 0.78rem; padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(168, 85, 247, 0.4); white-space: nowrap;">
                                ${escapeHtml(opp.pgou_status || 'En Desarrollo')}
                            </span>
                        </div>
                        <div style="font-size: 0.85rem; color: #e2e8f0; line-height: 1.45; margin-bottom: 10px;">
                            ${escapeHtml(opp.synergy_reason || 'Inmueble situado en el ámbito directo de planeamiento urbanístico.')}
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; background: rgba(0, 0, 0, 0.2); padding: 8px 12px; border-radius: 6px;">
                            <div>
                                <span style="font-size: 0.75rem; color: #94a3b8; display: block;">Revalorización prevista por transformación urbanística:</span>
                                <strong style="color: #34d399; font-size: 0.95rem;">${escapeHtml(opp.pgou_uplift || '+25-40% Plusvalía')}</strong>
                            </div>
                            <button class="btn" onclick="jumpToPgouSector('${opp.pgou_id || ''}')" style="background: linear-gradient(135deg, #9333ea 0%, #6366f1 100%); color: #fff; border: none; font-weight: 700; font-size: 0.8rem; padding: 6px 14px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 6px; box-shadow: 0 2px 8px rgba(147, 51, 234, 0.4); white-space: nowrap;">
                                <i data-lucide="map" style="width: 14px; height: 14px;"></i> Abrir Ficha en Visor PGOU
                            </button>
                        </div>
                    </div>
                `;
            }

            urbanismDetail = `
                ${synergySectionHtml}
                <div style="margin-top: 14px; padding: 14px; background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px; width: 100%; box-sizing: border-box;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 8px; flex-wrap: wrap;">
                        <span style="font-weight: 700; font-size: 0.92rem; color: #f8fafc; display: flex; align-items: center; gap: 6px; white-space: nowrap;">
                            <i data-lucide="layers" style="width: 16px; height: 16px; color: #38bdf8; flex-shrink: 0;"></i> <span>Análisis Multicanal (${escapeHtml(opp.x_publicacion || 'x1')})</span>
                        </span>
                        <span class="badge-xpublicacion" style="font-size: 0.76rem; white-space: nowrap; margin-left: auto;">
                            ${opp.distinct_prices_count || 1} precios detectados
                        </span>
                    </div>

                    <!-- Vista de Escritorio: Tabla tradicional con protección nowrap -->
                    <div class="multicanal-desktop-view multicanal-table-container" style="overflow-x: auto; width: 100%; max-width: 100%; -webkit-overflow-scrolling: touch;">
                        <table class="multicanal-table" style="width: 100%; border-collapse: collapse; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); color: #94a3b8; font-size: 0.74rem;">
                                    <th style="padding: 6px 10px; white-space: nowrap;">Portal</th>
                                    <th style="padding: 6px 10px; white-space: nowrap;">Precio Anunciado</th>
                                    <th style="padding: 6px 10px; white-space: nowrap;">Estado</th>
                                    <th style="padding: 6px 10px; white-space: nowrap;">Comercializadora</th>
                                    <th style="padding: 6px 10px; text-align: right; white-space: nowrap;">Enlace</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${pubsRowsHtml}
                            </tbody>
                        </table>
                    </div>

                    <!-- Vista Móvil / Dispositivos: Celdas por filas para evitar cortes de literales -->
                    <div class="multicanal-mobile-view">
                        ${pubsCardsHtml}
                    </div>

                    <div style="font-size: 0.74rem; color: #94a3b8; margin-top: 8px; line-height: 1.4; font-style: italic;">
                        ℹ️ <strong>Regla de Conteo xPublicación</strong>: Si el inmueble se anuncia en diferentes portales al mismo precio, no incrementa el contador. Solo computan importes numéricamente diferentes. HIVEX muestra siempre el precio mínimo garantizado.
                    </div>
                </div>
            `;

            liensDetailHtml = `
                <div style="margin-top: 14px; padding: 12px 14px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 8px; width: 100%;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 0.88rem; font-weight: 700; color: #f8fafc; display: flex; align-items: center; gap: 6px;">
                            <i data-lucide="badge-check" style="width: 16px; height: 16px; color: #34d399;"></i> Modalidad de Adquisición
                        </span>
                        <span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #34d399; font-weight: 800; font-size: 0.78rem; padding: 3px 8px; border-radius: 4px;">
                            VENTA DIRECTA LIBRE
                        </span>
                    </div>
                    <p style="font-size: 0.82rem; color: #cbd5e1; margin: 6px 0 0 0;">
                        Inmueble comercializado en portales inmobiliarios sin cargas procesales de subasta judicial activa. Verificación catastral y de linderos disponible.
                    </p>
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
                <div style="margin-top: 14px; padding: 12px 14px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; display: flex; flex-direction: column; gap: 8px; font-size: 0.9rem; width: 100%;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="color: #94a3b8; font-weight: 600;">Calificación del Suelo / Dominio:</span>
                        <span class="badge" style="background: ${landType === 'RÚSTICO' ? 'rgba(234,179,8,0.2)' : 'rgba(56,189,248,0.2)'}; color: ${landType === 'RÚSTICO' ? '#eab308' : '#38bdf8'}; font-weight: 800; font-size: 0.92rem; padding: 4px 10px; border-radius: 6px; text-transform: uppercase;">
                            ${landType} ${(ownershipPct < 100) ? `(${ownershipFormatted}% PLENO DOMINIO)` : ''}
                        </span>
                    </div>
                    ${opp.idufir ? `
                    <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 6px;">
                        <span style="color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                            <i data-lucide="shield-check" style="width: 15px; height: 15px; color: #c084fc;"></i> Código Registral Único (CRU / IDUFIR):
                        </span>
                        <span style="background: rgba(168, 85, 247, 0.15); color: #c084fc; font-weight: 800; font-size: 0.82rem; padding: 3px 10px; border-radius: 6px; letter-spacing: 0.5px;">
                            ${escapeHtml(opp.idufir)}
                        </span>
                    </div>
                    ` : ''}
                    ${opp.refcat ? `
                    <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 6px;">
                        <span style="color: #94a3b8; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                            <i data-lucide="map-pin" style="width: 15px; height: 15px; color: #38bdf8;"></i> Referencia Catastral (SEC):
                        </span>
                        <span style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-weight: 800; font-size: 0.82rem; padding: 3px 10px; border-radius: 6px; letter-spacing: 0.5px;">
                            ${escapeHtml(opp.refcat)}
                        </span>
                    </div>
                    ` : ''}
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

        const discountScoreBoxHtml = opp.source_type === 'pgou'
            ? `<div class="kpi-metric-box" style="background: rgba(168, 85, 247, 0.08); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(168, 85, 247, 0.25); display: flex; flex-direction: column; justify-content: space-between; min-height: 74px; height: 100%; box-sizing: border-box; width: 100%;">
                    <span class="kpi-metric-label" style="color: #c084fc; display: flex; align-items: flex-start; min-height: 2.3em; font-size: 0.74rem; font-weight: 600; line-height: 1.2; margin-bottom: 4px;">Enfoque Inversor PGOU</span>
                    <strong class="kpi-metric-val" style="color: #c084fc; font-size: 0.90rem; white-space: nowrap;">📍 Entorno Revalorizable</strong>
               </div>`
            : (opp.source_type === 'edictos'
                ? `<div class="kpi-metric-box" style="background: rgba(251, 191, 36, 0.08); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(251, 191, 36, 0.25); display: flex; flex-direction: column; justify-content: space-between; min-height: 74px; height: 100%; box-sizing: border-box; width: 100%;">
                        <span class="kpi-metric-label" style="color: #fbbf24; display: flex; align-items: flex-start; min-height: 2.3em; font-size: 0.74rem; font-weight: 600; line-height: 1.2; margin-bottom: 4px;">Estrategia Legal & Descuento</span>
                        <strong class="kpi-metric-val" style="color: #4ade80; font-size: 0.95rem; white-space: nowrap;">-${formatNumber(opp.discount_percentage, 0)}% vs Mercado</strong>
                   </div>`
                : (opp.source_type === 'market'
                    ? `<div class="kpi-metric-box" style="background: rgba(16, 185, 129, 0.08); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(16, 185, 129, 0.25); min-width: 0; display: flex; flex-direction: column; justify-content: space-between; min-height: 74px; height: 100%; box-sizing: border-box; width: 100%;">
                            <div class="kpi-metric-label" style="display: flex; justify-content: space-between; align-items: flex-start; min-height: 2.3em; width: 100%; margin-bottom: 4px;">
                                <span style="color: #34d399; font-weight: 600; font-size: 0.74rem; line-height: 1.2;">Bajada en Portal</span>
                                ${opp.price_drop_date ? `<span style="font-size: 0.65rem; color: #94a3b8; white-space: nowrap; margin-left: 4px;">${escapeHtml(opp.price_drop_date)}</span>` : ''}
                            </div>
                            <strong class="kpi-metric-val" style="color: #34d399; font-size: 0.92rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                                ${opp.price_drop_amount > 0 ? `-${formatNumber(opp.price_drop_percentage, 1)}% (-${formatCurrency(opp.price_drop_amount)})` : '0% (Salida)'}
                            </strong>
                       </div>`
                    : `<div class="kpi-metric-box" style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04); min-width: 0; display: flex; flex-direction: column; justify-content: space-between; min-height: 74px; height: 100%; box-sizing: border-box; width: 100%;">
                            <span class="kpi-metric-label" style="color: #94a3b8; display: flex; align-items: flex-start; min-height: 2.3em; font-size: 0.74rem; line-height: 1.2; margin-bottom: 4px;">Score Descuento vs Mercado</span>
                            <strong class="kpi-metric-val" style="color: ${getScoreColor(discountScoreVal)}; font-size: 0.95rem; white-space: nowrap;">${formatNumber(opp.discount_percentage, 2)}% (${formatScore(discountScoreVal)}/100 pts)</strong>
                       </div>`));

        const detailedScoresHtml = `
            <div class="detailed-scores-panel" style="margin-top: 16px; background: rgba(15, 23, 42, 0.6); padding: 14px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08); box-sizing: border-box;">
                <div class="kpis-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 8px; gap: 8px; width: 100%;">
                    <div class="kpis-title" style="font-weight: 700; font-size: 0.98rem; color: #f8fafc; display: flex; align-items: center; gap: 6px; white-space: nowrap; flex-shrink: 0;">
                        <i data-lucide="bar-chart-3" style="width: 17px; height: 17px; color: #38bdf8; flex-shrink: 0;"></i> <span>KPIs ${opp.source_type === 'pgou' ? '(Entorno Urbano)' : ''}</span>
                    </div>
                    <div class="kpis-header-badges" style="display: flex; flex-direction: column; align-items: flex-end; justify-content: center; gap: 4px; margin-left: auto; flex-shrink: 0;">
                        <span class="score-chip" style="${getScoreBgStyle(opp.overall_score)}; padding: 3px 8px; border-radius: 6px; font-size: 0.78rem; font-weight: 700; white-space: nowrap; text-align: right; display: inline-block;">
                            Score General: <strong>${formatScore(opp.overall_score)} / 100 pts</strong>
                        </span>
                        ${renderBtlBadge(opp, 'modal')}
                    </div>
                </div>
                <div class="two-cols-equal-grid" style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; font-size: 0.82rem; width: 100%; box-sizing: border-box;">
                    <div class="kpi-metric-box" style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04); min-width: 0; display: flex; flex-direction: column; justify-content: space-between; min-height: 74px; height: 100%; box-sizing: border-box; width: 100%;">
                        <span class="kpi-metric-label" style="color: #94a3b8; display: flex; align-items: flex-start; min-height: 2.3em; font-size: 0.74rem; line-height: 1.2; margin-bottom: 4px;">Renta Media por Hogar</span>
                        <strong class="kpi-metric-val" style="color: #f8fafc; font-size: 0.95rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${formatCurrency(opp.avg_household_income || 32000)}/año</strong>
                    </div>
                    <div class="kpi-metric-box" style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04); min-width: 0; display: flex; flex-direction: column; justify-content: space-between; min-height: 74px; height: 100%; box-sizing: border-box; width: 100%;">
                        <span class="kpi-metric-label" style="color: #94a3b8; display: flex; align-items: flex-start; min-height: 2.3em; font-size: 0.74rem; line-height: 1.2; margin-bottom: 4px;">Renta Media por Persona</span>
                        <strong class="kpi-metric-val" style="color: #f8fafc; font-size: 0.95rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${formatCurrency(opp.avg_person_income || 14500)}/año</strong>
                    </div>
                    <div class="kpi-metric-box" style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04); min-width: 0; display: flex; flex-direction: column; justify-content: space-between; min-height: 74px; height: 100%; box-sizing: border-box; width: 100%;">
                        <span class="kpi-metric-label" style="color: #94a3b8; display: flex; align-items: flex-start; min-height: 2.3em; font-size: 0.74rem; line-height: 1.2; margin-bottom: 4px;">Score Renta INE</span>
                        <strong class="kpi-metric-val" style="color: ${getScoreColor(opp.income_score)}; font-size: 0.95rem; white-space: nowrap;">${formatScore(opp.income_score)} / 100 pts</strong>
                    </div>
                    <div class="kpi-metric-box" style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04); min-width: 0; display: flex; flex-direction: column; justify-content: space-between; min-height: 74px; height: 100%; box-sizing: border-box; width: 100%;">
                        <span class="kpi-metric-label" style="color: #94a3b8; display: flex; align-items: flex-start; min-height: 2.3em; font-size: 0.74rem; line-height: 1.2; margin-bottom: 4px;">Crecimiento Demográfico INE</span>
                        <strong class="kpi-metric-val" style="color: ${getScoreColor(opp.demographic_score)}; font-size: 0.95rem; white-space: nowrap;">+${formatNumber(opp.population_growth_rate, 1)}% (${formatScore(opp.demographic_score)} pts)</strong>
                    </div>
                    <div class="kpi-metric-box" style="background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04); min-width: 0; display: flex; flex-direction: column; justify-content: space-between; min-height: 74px; height: 100%; box-sizing: border-box; width: 100%;">
                        <span class="kpi-metric-label" style="color: #94a3b8; display: flex; align-items: flex-start; min-height: 2.3em; font-size: 0.74rem; line-height: 1.2; margin-bottom: 4px;">Score POIs / Entorno (OSM)</span>
                        <strong class="kpi-metric-val" style="color: ${getScoreColor(opp.poi_score)}; font-size: 0.95rem; white-space: nowrap;">${formatScore(opp.poi_score)} / 100 pts</strong>
                    </div>
                    ${discountScoreBoxHtml}
                    ${(!isSolarOpportunity(opp) && opp.rental_yield !== undefined && opp.rental_yield !== null) ? `
                    <div class="kpi-btl-box" style="background: rgba(255,255,255,0.03); padding: 8px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04); grid-column: span 2; min-width: 0; box-sizing: border-box; min-height: 58px; display: flex; flex-direction: column; justify-content: center;">
                        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                            <div>
                                <span style="color: #94a3b8; display: block; font-size: 0.74rem; line-height: 1.2; margin-bottom: 2px;">Rentabilidad Bruta Alquiler (BTL)</span>
                                <div style="display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap;">
                                    <strong style="color: ${getBtlStyle(opp.rental_yield).color}; font-size: 1.05rem; white-space: nowrap;">
                                        ${Number(opp.rental_yield).toFixed(2).replace('.', ',')}% anual
                                    </strong>
                                    <span style="font-size: 0.74rem; color: #94a3b8; white-space: nowrap;">(${Math.round(opp.btl_score !== undefined && opp.btl_score !== null ? opp.btl_score : (opp.yield_score || 0))} pts)</span>
                                </div>
                            </div>
                            ${opp.estimated_monthly_rent ? `
                            <div style="text-align: right; flex-shrink: 0;">
                                <span style="color: #94a3b8; display: block; font-size: 0.74rem; line-height: 1.2; margin-bottom: 2px;">Alquiler Est. Mercado</span>
                                <strong style="color: #38bdf8; font-size: 0.98rem; white-space: nowrap;">${formatCurrency(opp.estimated_monthly_rent)}/mes</strong>
                            </div>
                            ` : ''}
                        </div>
                    </div>
                    ` : ''}
                </div>
            </div>
        `;

        const refValModal = (opp.source_type === 'pgou' || opp.source_type === 'edictos')
            ? (opp.listing_price || opp.starting_bid || opp.property_ref_value || 0)
            : (opp.property_ref_value || opp.starting_bid || opp.appraisal_value || opp.listing_price || 0);
        const estimatedMktValModal = isSurfaceMissingModal ? null : (opp.estimated_reference_value || ((effectiveSurface && opp.area_m2_price) ? (effectiveSurface * opp.area_m2_price) : null));
        const profitValModal = isSurfaceMissingModal ? null : ((opp.potential_gross_profit !== undefined && opp.potential_gross_profit !== null) ? opp.potential_gross_profit : (estimatedMktValModal ? (estimatedMktValModal - refValModal) : null));
        const profitFormattedModal = isSurfaceMissingModal ? '<span style="color: #f59e0b; font-size: 0.85rem; font-weight: 700;">Requiere Nota Simple</span>' : (profitValModal >= 0 ? `+${formatCurrency(profitValModal)}` : formatCurrency(profitValModal));

        const valorMicroVal = isSurfaceMissingModal ? null : (opp.valor_micro_est || opp.property_m2_price);
        const valorMicroDisplay = (valorMicroVal && valorMicroVal > 0) ? `${formatCurrency(valorMicroVal)}/m²` : '<span style="color: #94a3b8; font-style: italic;">-</span>';

        const registryServiceHtml = (opp.source_type === 'pgou' || opp.source_type === 'market') ? '' : `
            <div class="card-registry-module" style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(168, 85, 247, 0.35); border-radius: 10px; padding: 14px 16px; margin-top: 14px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="background: rgba(168, 85, 247, 0.2); color: #c084fc; padding: 4px 8px; border-radius: 6px; font-size: 0.82rem; font-weight: 800; display: flex; align-items: center; gap: 5px;">
                            <i data-lucide="building"></i> REGISTRO DE LA PROPIEDAD
                        </span>
                        <span style="font-size: 0.78rem; color: #94a3b8;">Servicio Web Colegio de Registradores</span>
                    </div>
                    <span style="font-size: 0.75rem; color: #38bdf8; background: rgba(56, 189, 248, 0.1); padding: 3px 8px; border-radius: 4px; border: 1px solid rgba(56, 189, 248, 0.25); font-weight: 600;">
                        Tarifa Arancelaria: 9,02 € + IVA (Abono en cuenta)
                    </span>
                </div>

                <div style="font-size: 0.82rem; color: #cbd5e1; margin-bottom: 10px; line-height: 1.4;">
                    ${isSurfaceMissingModal ? `
                        <div style="background: rgba(245, 158, 11, 0.12); border-left: 3px solid #f59e0b; padding: 8px 10px; border-radius: 0 4px 4px 0; margin-bottom: 8px; color: #fbbf24;">
                            <strong>Dato métrico no disponible en edicto:</strong> La subasta no especifica los m² en el BOE. Solicita la Nota Simple telemática para verificar la superficie registral exacta, linderos y cargas subsistentes antes de ofertar.
                        </div>
                    ` : `
                        <span>Verifica titularidad registral fehaciente, cargas registrales previas y liquidación de embargos directamente en el Registro de la Propiedad competente.</span>
                    `}
                    <div style="display: flex; gap: 16px; margin-top: 6px; font-size: 0.78rem; color: #94a3b8; flex-wrap: wrap;">
                        <span><strong>IDUFIR / CRU:</strong> <span style="color: #f8fafc; font-family: monospace;">${escapeHtml(opp.idufir || 'No consta en edicto (búsqueda por Finca)')}</span></span>
                        <span><strong>Ref. Catastral:</strong> <span style="color: #f8fafc; font-family: monospace;">${escapeHtml(opp.refcat || 'Pendiente')}</span></span>
                        <span><strong>Juzgado / Origen:</strong> <span style="color: #f8fafc;">${escapeHtml(opp.court_or_notary || opp.locality || 'Juzgado competente')}</span></span>
                    </div>
                </div>

                <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 10px;">
                    <button class="btn" onclick="requestNotaSimpleOnDemand(${index})" id="btn-request-nota-${index}" style="background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%); color: #fff; border: none; font-weight: 700; font-size: 0.82rem; padding: 8px 16px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 6px; box-shadow: 0 2px 8px rgba(124, 58, 237, 0.4);">
                        <i data-lucide="file-check"></i> Solicitar Nota Simple a Demanda (9,02 €)
                    </button>
                    <div id="nota-simple-status-${index}" style="font-size: 0.76rem; color: #94a3b8; display: flex; align-items: center; gap: 6px;">
                        <span>Cargo directo en cuenta de abonado registral</span>
                    </div>
                </div>
            </div>
        `;

        const modalImages = getOpportunityImagesList(opp);
        window.modalGalleryState = {
            images: modalImages,
            currentIndex: 0,
            portal: opp.primary_portal || 'Idealista'
        };

        const modalGalleryHtml = `
            <div class="modal-media-wrapper modal-gallery-box" style="margin-bottom: 16px; border-radius: 12px; background: rgba(15, 23, 42, 0.95); border: 1px solid rgba(56, 189, 248, 0.3); padding: 12px; position: relative;">
                <div class="modal-gallery-main" id="modal-gallery-main-view">
                    <img id="modal-gallery-active-img" src="${modalImages[0]}" alt="${escapeHtml(opp.title)}">
                    
                    ${modalImages.length > 1 ? `
                        <button type="button" class="modal-gallery-btn modal-gallery-prev" onclick="window.modalGalleryNav(-1)" title="Foto anterior (←)" aria-label="Foto anterior">
                            <i data-lucide="chevron-left"></i>
                        </button>
                        <button type="button" class="modal-gallery-btn modal-gallery-next" onclick="window.modalGalleryNav(1)" title="Foto siguiente (→)" aria-label="Foto siguiente">
                            <i data-lucide="chevron-right"></i>
                        </button>
                        <div class="modal-gallery-counter-badge" id="modal-gallery-counter">
                            <i data-lucide="camera" style="width: 13px; height: 13px; display: inline;"></i> 
                            <span>Foto <strong id="modal-gallery-cur-num">1</strong> de ${modalImages.length}</span>
                            <span id="modal-gallery-source-name" style="opacity: 0.8; margin-left: 6px;">• Fuente: ${escapeHtml(opp.primary_portal || 'Idealista')}</span>
                        </div>
                    ` : `
                        <div class="modal-gallery-counter-badge">
                            <i data-lucide="camera" style="width: 13px; height: 13px; display: inline;"></i> 
                            <span>Foto 1 de 1 • Fuente: ${modalImages[0] && modalImages[0].includes('maps.googleapis.com') ? 'Google Street View (Fachada)' : escapeHtml(opp.primary_portal || 'Idealista')}</span>
                        </div>
                    `}
                </div>

                ${modalImages.length > 1 ? `
                    <div class="modal-gallery-thumbnails" id="modal-gallery-thumbs">
                        ${modalImages.map((imgUrl, thumbIdx) => `
                            <div class="gallery-thumb-item ${thumbIdx === 0 ? 'active' : ''}" id="gallery-thumb-${thumbIdx}" onclick="window.modalGalleryGoTo(${thumbIdx})" title="Ver foto ${thumbIdx + 1}">
                                <img src="${imgUrl}" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" alt="Miniatura ${thumbIdx + 1}">
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
            </div>
        `;

        body.innerHTML = `
            <div class="modal-prop-container">
                ${modalGalleryHtml}

                <div class="modal-prop-header">
                    <div style="margin-bottom: 10px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        ${opp.is_new ? `
                            <span class="badge-new-pill" style="font-size: 0.78rem; padding: 4px 10px;">
                                <i data-lucide="sparkles"></i> New! Incorporada recientemente
                            </span>
                        ` : ''}
                        ${opp.source_type === 'market' ? `
                            <span class="badge-xpublicacion" style="font-size: 0.82rem; padding: 5px 12px; border-radius: 6px;">
                                <i data-lucide="layers"></i> xPublicación: ${escapeHtml(opp.x_publicacion || 'x1')}
                            </span>
                            ${opp.has_pgou_synergy ? `
                                <span class="badge-synergy" style="font-size: 0.82rem; padding: 5px 12px; border-radius: 6px;">
                                    <i data-lucide="crosshair"></i> 🎯 SINERGIA PGOU
                                </span>
                            ` : ''}
                        ` : ''}
                        ${opp.is_lotes ? `
                            <span class="badge-lote" style="font-size: 0.84rem; padding: 5px 12px; border-radius: 6px;">
                                <i data-lucide="package"></i> ${escapeHtml(opp.lote_badge || 'SUBASTA POR LOTES · ADJUDICACIÓN INDEPENDIENTE')}
                            </span>
                            <span style="font-size: 0.78rem; color: #a5b4fc; background: rgba(99, 102, 241, 0.1); border: 1px solid rgba(99, 102, 241, 0.25); padding: 4px 8px; border-radius: 4px;">
                                ⚖️ LEC Art. 643: Puja y adjudicación independiente por lote
                            </span>
                        ` : ''}
                    </div>
                    <h2>${escapeHtml(opp.title)}</h2>
                    <div class="modal-prop-address" style="margin-top: 8px; display: flex; flex-direction: column; gap: 6px;">
                        <a href="javascript:void(0)" class="address-maps-link" style="font-size: 0.92rem; padding: 6px 12px; width: fit-content;" onclick="openGoogleMapsFromModal(event)">
                            <i data-lucide="map-pin"></i> ${escapeHtml(fullAddress)}
                            <span class="maps-badge"><i data-lucide="map"></i> Abrir Google Maps Satélite</span>
                        </a>
                        ${dateSubastaHeaderModal}
                    </div>
                </div>

                <div class="card-financials" style="padding: 16px; font-size: 0.95rem; display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 10px;">
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">${opp.source_type === 'market' ? 'Bajada Anuncio (Portal)' : (opp.source_type === 'pgou' ? 'Valor Tasación Ref.' : 'Valor Tasación BOE')}</span>
                        <span class="fin-val ref" style="display: block; font-size: 1.15rem; font-weight: 800; margin-top: 2px; color: ${opp.source_type === 'market' ? '#4ade80' : 'inherit'};">
                            ${opp.source_type === 'market' ? (opp.price_drop_amount > 0 ? `-${formatNumber(opp.price_drop_percentage, 1)}% rebaja` : '0% (Salida)') : (opp.appraisal_value > 0 ? formatCurrency(opp.appraisal_value) : '0 €')}
                        </span>
                        ${opp.source_type === 'market' && opp.price_drop_amount > 0 ? `<div style="font-size: 0.74rem; color: #34d399; font-weight: 600;">Bajada: -${formatCurrency(opp.price_drop_amount)}</div>` : ''}
                        ${opp.source_type === 'market' && opp.price_drop_date ? `<div style="font-size: 0.72rem; color: #94a3b8;">Fecha rebaja: ${escapeHtml(opp.price_drop_date)}</div>` : ''}
                        ${opp.source_type === 'market' && opp.original_listing_price && opp.original_listing_price > opp.listing_price ? `<div style="font-size: 0.70rem; color: #64748b;">Salida: ${formatCurrency(opp.original_listing_price)}</div>` : ''}
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">${opp.source_type === 'market' ? 'Precio de Venta' : (opp.source_type === 'pgou' ? 'Precio Adquisición Ref.' : (opp.source_type === 'edictos' ? 'Salida / Tipo Estimado' : 'Valor de Subasta'))}</span>
                        <span class="fin-val price" style="display: block; font-size: 1.15rem; font-weight: 800; margin-top: 2px; color: ${opp.source_type === 'market' ? '#38bdf8' : 'inherit'};">${formatCurrency(opp.source_type === 'market' ? opp.listing_price : refValModal)}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: ${isSurfaceMissingModal ? '#f59e0b' : '#38bdf8'}; font-weight: 600; line-height: 1.2;">Valor Mercado Est.</span>
                        <span class="fin-val" style="display: block; font-size: 1.15rem; font-weight: 800; color: ${isSurfaceMissingModal ? '#f59e0b' : '#38bdf8'}; margin-top: 2px;">${isSurfaceMissingModal ? '<span style="font-size: 0.82rem; font-weight: 700;">Pendiente Nota Simple</span>' : `${formatCurrency(estimatedMktValModal)} (*)`}</span>
                    </div>
                    <div class="fin-item" style="display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 4px;">
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: #94a3b8; font-weight: 600; line-height: 1.2;">${opp.source_type === 'market' ? 'Superficie Construida' : (opp.source_type === 'pgou' ? 'Superficie Suelo (m²s)' : (opp.source_type === 'edictos' ? 'Superficie Útil / Cuota' : 'Superficie (Cuota Real)'))}</span>
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
                        <span class="fin-label" style="display: block; font-size: 0.8rem; color: ${opp.source_type === 'pgou' ? getScoreColor(opp.overall_score) : '#94a3b8'}; font-weight: 700; line-height: 1.2;">${opp.source_type === 'pgou' ? 'SCORE GENERAL ENTORNO' : (opp.source_type === 'edictos' ? 'Margen Bruto Est.' : (opp.source_type === 'market' ? 'Margen vs Ref. Barrio' : 'Beneficio / Margen Est.'))}</span>
                        <span class="fin-val profit" style="display: block; font-size: 1.15rem; font-weight: 800; color: ${opp.source_type === 'pgou' ? getScoreColor(opp.overall_score) : (profitValModal >= 0 ? '#4ade80' : '#f87171')}; margin-top: 2px;">${opp.source_type === 'pgou' ? `${formatScore(opp.overall_score)} / 100 pts` : `${profitFormattedModal} (*)`}</span>
                        ${opp.source_type === 'market' && opp.discount_vs_market > 0 ? `<div style="font-size: 0.74rem; color: #38bdf8; font-weight: 700; margin-top: 2px;">-${formatNumber(opp.discount_vs_market, 1)}% dto. vs mercado</div>` : ''}
                    </div>
                </div>

                <div style="margin-top: 8px; font-size: 0.78rem; color: #cbd5e1; padding-left: 2px;">
                    <strong>(*):</strong> <span style="color: #38bdf8; font-weight: 600;">valor sección censal (ref. barrio: ${escapeHtml(districtName)})</span>
                </div>

                <p style="color: var(--text-muted); font-size: 0.9rem; line-height: 1.5; margin-top: 14px; text-align: left;">${escapeHtml(opp.description || '')}</p>

                ${detailedScoresHtml}

                ${urbanismDetail}

                ${liensDetailHtml}

                ${registryServiceHtml}

                <div style="display: flex; justify-content: flex-end; align-items: center; gap: 12px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--glass-border);">
                    <button class="btn btn-secondary" onclick="closePropertyDetailModal()">
                        <i data-lucide="x"></i> Cerrar Ventana
                    </button>
                    ${extBtnUrlModal && extBtnUrlModal !== '#' ? `
                    <a href="${extBtnUrlModal}" target="_blank" rel="noopener" class="btn btn-primary">
                        <i data-lucide="external-link"></i> ${escapeHtml(extBtnLabelModal)}
                    </a>
                    ` : ''}
                </div>
            </div>
        `;

        if (window.lucide) lucide.createIcons();
        modal.classList.remove('hidden');

        // Soporte de navegación táctil (swipe) para smartphones y tablets
        const mainViewEl = document.getElementById('modal-gallery-main-view');
        if (mainViewEl) {
            let touchStartX = 0;
            let touchEndX = 0;
            mainViewEl.addEventListener('touchstart', (e) => {
                if (e.changedTouches && e.changedTouches[0]) {
                    touchStartX = e.changedTouches[0].screenX;
                }
            }, { passive: true });
            mainViewEl.addEventListener('touchend', (e) => {
                if (e.changedTouches && e.changedTouches[0]) {
                    touchEndX = e.changedTouches[0].screenX;
                    if (touchEndX < touchStartX - 40) {
                        window.modalGalleryNav(1); // Deslizar izquierda -> siguiente
                    } else if (touchEndX > touchStartX + 40) {
                        window.modalGalleryNav(-1); // Deslizar derecha -> anterior
                    }
                }
            }, { passive: true });
        }
    };

    window.closePropertyDetailModal = function() {
        const modal = document.getElementById('modal-property-detail');
        if (modal) modal.classList.add('hidden');
        if (!state.token) {
            showLoginOverlay();
        }
    };

    window.requestNotaSimpleOnDemand = async function(idx) {
        let opp = null;
        if (typeof idx === 'object' && idx !== null) {
            opp = idx;
        } else if (state.filteredOpportunities && state.filteredOpportunities[idx]) {
            opp = state.filteredOpportunities[idx];
        } else if (state.allOpportunities && state.allOpportunities[idx]) {
            opp = state.allOpportunities[idx];
        } else if (window._lastOpportunities && window._lastOpportunities[idx]) {
            opp = window._lastOpportunities[idx];
        }
        if (!opp) return;

        const btn = document.getElementById(`btn-request-nota-${idx}`);
        const statusDiv = document.getElementById(`nota-simple-status-${idx}`);

        const confirmMsg = `¿Deseas tramitar la solicitud telemática de Nota Simple oficial para ${opp.id_subasta || opp.title}?\n\n• Identificador: ${opp.idufir || opp.refcat || 'Datos de finca/edicto'}\n• Arancel regulado: 9,02 € (+ 21% IVA = 10,91 €)\n• Facturación: Cargo en cuenta de abonado del Colegio de Registradores\n\n¿Continuar con la solicitud a demanda?`;
        if (!confirm(confirmMsg)) return;

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = `<i data-lucide="loader-2" class="spin"></i> Tramitando con Registro...`;
            if (window.lucide) lucide.createIcons();
        }

        try {
            const token = localStorage.getItem('token');
            const resp = await fetch(`/api/v1/opportunities/${opp.id}/request-nota-simple`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { 'Authorization': `Bearer ${token}` } : {})
                },
                body: JSON.stringify({
                    motivo: "Interés legítimo de inversión inmobiliaria en procedimiento de subasta pública"
                })
            });

            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                throw new Error(errData.detail || 'Error al conectar con la pasarela del Colegio de Registradores');
            }

            const resData = await resp.json();
            if (statusDiv) {
                statusDiv.innerHTML = `
                    <div style="background: rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.3); padding: 8px 12px; border-radius: 6px; color: #4ade80; display: flex; flex-direction: column; gap: 4px; width: 100%; margin-top: 6px;">
                        <span style="font-weight: 700; display: flex; align-items: center; gap: 6px;"><i data-lucide="check-circle" style="width: 14px; height: 14px;"></i> Solicitud telemática tramitada con éxito</span>
                        <span style="font-size: 0.74rem; color: #cbd5e1;">Nº Expediente: <strong style="font-family: monospace; color: #fff;">${escapeHtml(resData.expediente_id || 'REG-2026-0084')}</strong> • Cuenta abono: <strong>${escapeHtml(resData.billing_account || 'ABONO-REG-0001')}</strong></span>
                        <span style="font-size: 0.72rem; color: #94a3b8;">${escapeHtml(resData.mensaje || 'En tramitación telemática. Los datos registrales y superficie se volcarán al expediente.')}</span>
                    </div>
                `;
                if (window.lucide) lucide.createIcons();
            }
            if (btn) {
                btn.style.background = '#059669';
                btn.innerHTML = `<i data-lucide="check"></i> Solicitada (Expediente en curso)`;
                if (window.lucide) lucide.createIcons();
            }
        } catch (err) {
            if (statusDiv) {
                statusDiv.innerHTML = `<span style="color: #f87171; font-weight: 600;">⚠️ ${escapeHtml(err.message)}</span>`;
            }
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = `<i data-lucide="file-check"></i> Reintentar Solicitud`;
                if (window.lucide) lucide.createIcons();
            }
        }
    };

    window.openGoogleMapsForCard = function(idx, event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        const opps = window._lastOpportunities || (state && state.filteredOpportunities) || [];
        const opp = opps[idx];
        if (!opp) return;
        const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality || ''}, ${opp.province || ''}, España`;
        window.openGoogleMapsModal(fullAddress, opp.lat, opp.lon, event);
    };

    window.openGoogleMapsFromModal = function(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        const opp = window._activeModalOpp;
        if (!opp) return;
        const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality || ''}, ${opp.province || ''}, España`;
        window.openGoogleMapsModal(fullAddress, opp.lat, opp.lon, event);
    };

    window.openGoogleMapsModal = function(address, lat, lon, event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        const modal = document.getElementById('modal-google-maps');
        if (!modal) return;
        const addrSpan = document.getElementById('modal-gmaps-address');
        const linkExt = document.getElementById('link-gmaps-external');
        const iframe = document.getElementById('iframe-gmaps');

        let fullSearch = (address && typeof address === 'string' && address.trim() !== '') ? address.trim() : '';
        if (fullSearch && !fullSearch.toLowerCase().includes('españa') && !fullSearch.toLowerCase().includes('spain')) {
            fullSearch += ', España';
        }

        const query = fullSearch || (lat && lon ? `${lat},${lon}` : 'España');
        const encQuery = encodeURIComponent(query);

        if (addrSpan) addrSpan.textContent = address || query;

        const gmapsKey = window.GOOGLE_MAPS_API_KEY || localStorage.getItem('hivex_gmaps_api_key') || 'AIzaSyADs9RShXJVDUAO85OBIuwcjzC70V01_Vc';

        // Official Google Maps Embed API with Satellite view
        if (gmapsKey) {
            window._gmapsMapUrl = `https://www.google.com/maps/embed/v1/search?key=${gmapsKey}&q=${encQuery}&maptype=satellite`;
        } else {
            window._gmapsMapUrl = `https://maps.google.com/maps?q=${encQuery}&t=k&z=18&ie=UTF8&iwloc=&output=embed`;
        }

        if (iframe) iframe.src = window._gmapsMapUrl;

        modal.classList.remove('hidden');
        modal.style.display = 'flex';
        modal.style.zIndex = '10005';

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
        if (modal) {
            modal.classList.add('hidden');
            modal.style.display = 'none';
        }
    };

    window.changeModalMainImg = function(url, el) {
        document.getElementById('prop-main-img').style.backgroundImage = `url('${url}')`;
        document.querySelectorAll('.thumb-img').forEach(t => t.classList.remove('active'));
        if (el) el.classList.add('active');
    };

    let markersMap = {};
    let clustersByOppId = {};
    let currentSpiderLayer = null;
    let currentSpiderClusterKey = null;

    window.unspiderify = function() {
        if (currentSpiderLayer && map) {
            map.removeLayer(currentSpiderLayer);
            currentSpiderLayer = null;
        }
        currentSpiderClusterKey = null;
    };

    function buildPopupHtml(opp, idx) {
        const isPgou = opp.source_type === 'pgou';
        const isEdictos = opp.source_type === 'edictos';
        const isMarket = opp.source_type === 'market';
        const imgInfo = getOpportunityMainImage(opp);
        const mainImg = imgInfo.url;
        const fullAddress = opp.full_address || `${opp.address || ''}, ${opp.locality || ''}`;

        let loteHeaderHtml = '';
        if (opp.is_lotes || opp.is_new || (isMarket && (opp.x_publicacion || opp.has_pgou_synergy))) {
            loteHeaderHtml = `
                <div style="margin-bottom: 6px; display: flex; gap: 5px; align-items: center; flex-wrap: wrap;">
                    ${opp.is_new ? `
                        <span style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: #fff; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 12px; box-shadow: 0 1px 4px rgba(16,185,129,0.4); display: inline-flex; align-items: center; gap: 3px;">
                            ✨ New!
                        </span>
                    ` : ''}
                    ${isMarket && opp.x_publicacion ? `
                        <span style="background: rgba(14, 165, 233, 0.15); color: #0284c7; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(14, 165, 233, 0.3);">
                            xPublicación: ${escapeHtml(opp.x_publicacion)}
                        </span>
                    ` : ''}
                    ${isMarket && opp.has_pgou_synergy ? `
                        <span style="background: rgba(168, 85, 247, 0.15); color: #7e22ce; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(168, 85, 247, 0.3);">
                            🎯 PGOU
                        </span>
                    ` : ''}
                    ${opp.is_lotes ? `
                        <span style="background: linear-gradient(135deg, #6366f1, #4f46e5); color: #fff; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; box-shadow: 0 1px 4px rgba(99,102,241,0.4); display: inline-flex; align-items: center; gap: 4px;">
                            📦 LOTE ${opp.lot_number || 1} · PUJA INDEPENDIENTE
                        </span>
                    ` : ''}
                </div>
            `;
        }

        let popupDetailHtml = '';
        if (isPgou) {
            let landUseProposed = 'Residencial';
            if (opp.proposed_land_use === 'PROTECTED_HOUSING') {
                landUseProposed = 'Residencial VPA / VPPO (Protegida)';
            } else if (opp.proposed_land_use === 'FREE_HOUSING') {
                landUseProposed = 'Residencial Libre';
            } else if (opp.proposed_land_use === 'TERTIARY_INDUSTRIAL') {
                landUseProposed = 'Terciario / Industrial';
            } else if (opp.proposed_land_use) {
                landUseProposed = opp.proposed_land_use;
            }
            const planningStatus = opp.planning_status || 'PGOU';
            const scoreCol = getScoreColor(opp.overall_score);
            popupDetailHtml = `
                <div style="margin-bottom: 3px; font-size: 11px; color: #6b21a8; font-weight: 700;">
                    🧭 <strong>Uso Propuesto:</strong> ${escapeHtml(landUseProposed)}
                </div>
                <div style="margin-bottom: 3px; font-size: 11px; color: #0369a1; font-weight: 700;">
                    📜 <strong>Estatus:</strong> ${escapeHtml(planningStatus)}
                </div>
                <div style="margin-bottom: 10px; font-weight: 800; color: ${scoreCol}; font-size: 12px;">
                    ⭐ <strong>Score General:</strong> ${formatScore(opp.overall_score)} / 100 pts
                </div>
            `;
        } else if (isEdictos) {
            const isHerencia = opp.category === 'HERENCIA_YACENTE';
            popupDetailHtml = `
                <div style="margin-bottom: 3px; font-size: 11px; color: ${isHerencia ? '#b45309' : '#4338ca'}; font-weight: 700;">
                    ⚖️ <strong>Procedimiento:</strong> ${escapeHtml(opp.proceedings_type || 'Edicto')}
                </div>
                <div style="margin-bottom: 3px; font-size: 11px; color: #0284c7; font-weight: 700;">
                    🏛️ <strong>Origen:</strong> ${escapeHtml(opp.court_or_notary || 'Notaría / Juzgado')}
                </div>
                <div style="margin-bottom: 10px; font-weight: 700; color: #059669; font-size: 12px;">
                    -${formatNumber(opp.discount_percentage, 0)}% Descuento | Salida: ${formatCurrency(opp.listing_price || opp.starting_bid || opp.property_ref_value)}
                </div>
            `;
        } else if (isMarket) {
            popupDetailHtml = `
                <div style="margin-bottom: 3px; font-size: 11px; color: #059669; font-weight: 700;">
                    🛒 <strong>Portal:</strong> ${escapeHtml(opp.primary_portal || 'Portal Inmobiliario')}
                </div>
                ${opp.has_pgou_synergy ? `
                    <div style="margin-bottom: 3px; font-size: 11px; color: #7e22ce; font-weight: 700;">
                        🎯 <strong>Sinergia PGOU:</strong> ${escapeHtml(opp.pgou_title || 'Sector Urb.')} (${escapeHtml(opp.pgou_uplift || '+Plusvalía')})
                    </div>
                ` : ''}
                <div style="margin-bottom: 3px; font-size: 11px; color: #0284c7;">
                    <strong>% dto. bajada:</strong> ${opp.discount_percentage > 0 ? `-${formatNumber(opp.discount_percentage, 1)}% dto.` : '0% (Precio Inicial)'}
                </div>
                <div style="margin-bottom: 10px; font-weight: 800; color: #0284c7; font-size: 12px;">
                    Precio Venta: ${formatCurrency(opp.listing_price)}
                </div>
            `;
        } else {
            const boeAppraisalText = (opp.appraisal_value && opp.appraisal_value > 0) ? formatCurrency(opp.appraisal_value) : '0 € (Sin constancia en BOE)';
            const mktEstPopup = opp.is_surface_missing ? '<span style="color: #d97706; font-weight: 700;">Pendiente Nota Simple</span>' : formatCurrency(opp.estimated_reference_value);
            const discountBadgePopup = opp.is_surface_missing
                ? '<span style="color: #d97706; font-weight: 700;">⚠️ Requiere Nota Simple</span>'
                : (opp.discount_percentage > 0 ? `-${formatNumber(opp.discount_percentage, 0)}% Descuento` : 'Subasta s/ Tipo');
            popupDetailHtml = `
                <div style="margin-bottom: 2px; font-size: 11px; color: #475569;">
                    <strong>Tasación BOE:</strong> ${boeAppraisalText}
                </div>
                <div style="margin-bottom: 4px; font-size: 11px; color: #0284c7;">
                    <strong>Estimación Mercado:</strong> ${mktEstPopup}
                </div>
                <div style="margin-bottom: 10px; font-weight: 700; color: ${opp.is_surface_missing ? '#d97706' : (opp.discount_percentage > 0 ? '#059669' : '#64748b')}; font-size: 12px;">
                    ${discountBadgePopup} | Salida: ${formatCurrency(opp.listing_price || opp.starting_bid)}
                </div>
            `;
        }

        return `
            <div style="font-family: sans-serif; color: #1e293b; max-width: 260px; padding: 4px;">
                <div style="width: 100%; height: 110px; border-radius: 6px; overflow: hidden; margin-bottom: 8px; border: 1px solid #cbd5e1; background: #0f172a;">
                    <img src="${mainImg}" style="width: 100%; height: 100%; object-fit: cover;" alt="${escapeHtml(opp.title)}">
                </div>
                ${loteHeaderHtml}
                <strong style="font-size: 13px; display: block; margin-bottom: 4px; color: #0f172a; line-height: 1.2;">${escapeHtml(opp.title)}</strong>
                <span style="color: #64748b; font-size: 11px; display: block; margin-bottom: 6px;">📍 ${escapeHtml(fullAddress)}</span>
                ${popupDetailHtml}
                <button onclick="openPropertyDetailModal(${idx})" style="width: 100%; padding: 7px 12px; background: #2563eb; color: #ffffff; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; box-shadow: 0 2px 4px rgba(37,99,235,0.3);">
                    🔍 Ver Ficha Completa
                </button>
            </div>
        `;
    }

    function openClusterWithZoom(cluster, targetOppIdToOpen = null) {
        if (!map) return;
        if (currentSpiderClusterKey === cluster.key && !targetOppIdToOpen) {
            window.unspiderify();
            return;
        }

        const currentZoom = map.getZoom();
        const targetZoom = Math.max(currentZoom, 16);

        if (currentZoom < 15) {
            map.flyTo([cluster.lat, cluster.lon], targetZoom, { duration: 0.6 });
            map.once('moveend', () => {
                spiderifyCluster(cluster, cluster.marker, targetOppIdToOpen);
            });
        } else {
            map.panTo([cluster.lat, cluster.lon], { duration: 0.25 });
            spiderifyCluster(cluster, cluster.marker, targetOppIdToOpen);
        }
    }

    function spiderifyCluster(cluster, clusterMarker, targetOppIdToOpen = null) {
        window.unspiderify();
        if (!map) return;

        currentSpiderClusterKey = cluster.key;
        currentSpiderLayer = L.layerGroup();
        const count = cluster.items.length;
        const centerLatLng = L.latLng(cluster.lat, cluster.lon);
        const centerPoint = map.latLngToLayerPoint(centerLatLng);

        const radiusPx = count <= 2 ? 45 : (count <= 4 ? 56 : (count <= 6 ? 68 : 82));

        cluster.items.forEach((item, i) => {
            const opp = item.opp;
            const idx = item.idx;

            let angle;
            if (count === 2) {
                angle = (i === 0 ? -Math.PI * 0.75 : -Math.PI * 0.25);
            } else if (count === 3) {
                angle = -Math.PI / 2 + (i - 1) * (Math.PI / 3);
            } else {
                angle = (2 * Math.PI * i / count) - (Math.PI / 2);
            }

            const childPoint = L.point(
                centerPoint.x + radiusPx * Math.cos(angle),
                centerPoint.y + radiusPx * Math.sin(angle)
            );
            const childLatLng = map.layerPointToLatLng(childPoint);

            // 1. Línea SVG conectora
            const connector = L.polyline([centerLatLng, childLatLng], {
                color: '#818cf8',
                weight: 2,
                opacity: 0.9,
                dashArray: '3, 4',
                className: 'spider-connector-line'
            });
            currentSpiderLayer.addLayer(connector);

            // 2. Marcador desplegado en abanico
            let childColor = '#f59e0b';
            if (opp.source_type === 'pgou') {
                childColor = opp.planning_status && opp.planning_status.includes('Definitiva') ? '#a855f7' : '#10b981';
            } else if (opp.source_type === 'edictos') {
                childColor = opp.category === 'HERENCIA_YACENTE' ? '#eab308' : '#6366f1';
            } else if (opp.source_type === 'market') {
                childColor = opp.has_pgou_synergy ? '#a855f7' : '#10b981';
            } else {
                childColor = opp.strategy === 'HOUSE_FLIPPING' ? '#ef4444' : '#f59e0b';
            }

            const isActualLot = !!opp.is_lotes;
            const badgeText = isActualLot ? `L${opp.lot_number || (i + 1)}` : `${i + 1}`;
            const childIcon = L.divIcon({
                className: 'custom-map-pin spider-pin-wrapper',
                html: `
                    <div class="spider-pin-circle" style="background-color: ${childColor}; box-shadow: 0 0 14px ${childColor}; font-size: ${isActualLot ? '10px' : '11px'}; font-weight: 800;">
                        ${badgeText}
                    </div>
                `,
                iconSize: [28, 28],
                iconAnchor: [14, 14]
            });

            const childMarker = L.marker(childLatLng, { icon: childIcon });
            childMarker.bindPopup(buildPopupHtml(opp, idx));

            childMarker.on('click', () => {
                document.querySelectorAll('.deal-card').forEach(c => c.classList.remove('card-highlight'));
                const cardEl = document.querySelector(`.deal-card[data-opp-id="${opp.id}"]`);
                if (cardEl) {
                    cardEl.classList.add('card-highlight');
                    cardEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            });

            currentSpiderLayer.addLayer(childMarker);

            if (targetOppIdToOpen && opp.id === targetOppIdToOpen) {
                setTimeout(() => childMarker.openPopup(), 180);
            }
        });

        currentSpiderLayer.addTo(map);
    }

    window.highlightOpportunityPin = function(oppId, lat, lon) {
        document.querySelectorAll('.deal-card').forEach(c => c.classList.remove('card-highlight'));
        const cardEl = document.querySelector(`.deal-card[data-opp-id="${oppId}"]`);
        if (cardEl) cardEl.classList.add('card-highlight');

        const cluster = clustersByOppId[oppId];
        if (cluster && cluster.items.length > 1) {
            openClusterWithZoom(cluster, oppId);
            return;
        }

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

    // Render Pins on Map with Interactivity & Spiderify (Opción A: Abanico Radial)
    function renderMapMarkers(opps) {
        if (!map || !mapMarkersLayer) {
            initMap();
        }
        if (!mapMarkersLayer) return;

        if (typeof window.unspiderify === 'function') {
            window.unspiderify();
        }
        mapMarkersLayer.clearLayers();
        markersMap = {};
        clustersByOppId = {};
        const bounds = [];

        // Agrupar oportunidades en clusters geográficos o por id_subasta si es por lotes
        const clusters = {};
        const coordOccurrences = {};
        (opps || []).forEach((opp, idx) => {
            const rawLat = parseFloat(opp.lat);
            const rawLon = parseFloat(opp.lon);
            if (!isNaN(rawLat) && !isNaN(rawLon) && rawLat !== 0 && rawLon !== 0) {
                const isMarket = (opp.source_type === 'market');
                let lat = rawLat;
                let lon = rawLon;

                // Para oportunidades de mercado, NUNCA agrupar en clusters de fincas.
                // Cada inmueble de mercado tiene su propia chincheta individual.
                // Si varios inmuebles comparten coordenadas base, aplicamos micro-dispersión imperceptible (~20m)
                // para que ambas chinchetas sean visibles individualmente.
                if (isMarket) {
                    const coordKey = `${rawLat.toFixed(4)},${rawLon.toFixed(4)}`;
                    const seen = coordOccurrences[coordKey] || 0;
                    coordOccurrences[coordKey] = seen + 1;
                    if (seen > 0) {
                        const angle = seen * 2.39996; // Golden angle spiral
                        const r = 0.00025 * Math.sqrt(seen);
                        lat = rawLat + r * Math.cos(angle);
                        lon = rawLon + (r * Math.sin(angle) / Math.cos(rawLat * Math.PI / 180));
                    }
                }

                const geoKey = isMarket
                    ? `market_${opp.id || idx}`
                    : ((opp.is_lotes && opp.id_subasta)
                        ? `sub_${opp.id_subasta}`
                        : `${lat.toFixed(4)},${lon.toFixed(4)}`);

                if (!clusters[geoKey]) {
                    clusters[geoKey] = {
                        key: geoKey,
                        lat: lat,
                        lon: lon,
                        items: [],
                        marker: null
                    };
                }
                clusters[geoKey].items.push({ opp, idx, lat, lon });
                bounds.push([lat, lon]);
            }
        });

        // Crear marcadores en el mapa
        Object.keys(clusters).forEach(key => {
            const cluster = clusters[key];
            const count = cluster.items.length;

            if (count === 1) {
                // Caso 1: Oportunidad individual
                const item = cluster.items[0];
                const opp = item.opp;
                const idx = item.idx;
                const lat = item.lat;
                const lon = item.lon;

                clustersByOppId[opp.id] = cluster;

                let color = '#f59e0b';
                if (opp.source_type === 'pgou') {
                    color = opp.planning_status && opp.planning_status.includes('Definitiva') ? '#a855f7' : '#10b981';
                } else if (opp.source_type === 'edictos') {
                    color = opp.category === 'HERENCIA_YACENTE' ? '#eab308' : '#6366f1';
                } else if (opp.source_type === 'market') {
                    color = opp.has_pgou_synergy ? '#a855f7' : '#10b981';
                } else {
                    color = opp.strategy === 'HOUSE_FLIPPING' ? '#ef4444' : '#f59e0b';
                }

                let iconHtml = `<div style="background-color: ${color}; width: 20px; height: 20px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 12px ${color}; cursor: pointer;"></div>`;
                let iconSize = [20, 20];
                let iconAnchor = [10, 10];

                if (opp.is_lotes) {
                    iconHtml = `
                        <div class="pin-lote-badge" style="background-color: ${color}; min-width: 26px; height: 26px; padding: 0 6px; border-radius: 13px; border: 2px solid white; box-shadow: 0 0 14px ${color}; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 3px; color: white; font-weight: 800; font-size: 11px;">
                            <span>📦</span><span>L${opp.lot_number || 1}</span>
                        </div>
                    `;
                    iconSize = [46, 26];
                    iconAnchor = [23, 13];
                }

                const customIcon = L.divIcon({
                    className: 'custom-map-pin',
                    html: iconHtml,
                    iconSize: iconSize,
                    iconAnchor: iconAnchor
                });

                const marker = L.marker([lat, lon], { icon: customIcon });
                marker.bindPopup(buildPopupHtml(opp, idx));

                marker.on('click', () => {
                    document.querySelectorAll('.deal-card').forEach(c => c.classList.remove('card-highlight'));
                    const cardEl = document.querySelector(`.deal-card[data-opp-id="${opp.id}"]`);
                    if (cardEl) {
                        cardEl.classList.add('card-highlight');
                        cardEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                });

                cluster.marker = marker;
                markersMap[opp.id] = marker;
                mapMarkersLayer.addLayer(marker);

            } else {
                // Caso 2: Subasta con múltiples lotes o fincas co-ubicadas -> Cluster con apertura en abanico (Spiderify)
                cluster.items.forEach(it => {
                    clustersByOppId[it.opp.id] = cluster;
                });

                const hasLot = cluster.items.some(it => it.opp.is_lotes);
                const clusterColor = hasLot ? '#6366f1' : '#0ea5e9';
                const labelText = hasLot ? `${count} Lotes` : `${count} Fincas`;

                const clusterIcon = L.divIcon({
                    className: 'custom-map-pin pin-cluster',
                    html: `
                        <div class="spider-cluster-badge" style="background: linear-gradient(135deg, ${clusterColor}, #4338ca); min-width: 36px; height: 32px; padding: 0 9px; border-radius: 16px; border: 2px solid white; box-shadow: 0 0 16px rgba(99,102,241,0.85); cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 4px; color: white; font-weight: 800; font-size: 11px; white-space: nowrap;">
                            <span>${hasLot ? '📦' : '📍'}</span>
                            <span>${labelText}</span>
                        </div>
                    `,
                    iconSize: [44, 32],
                    iconAnchor: [22, 16]
                });

                const clusterMarker = L.marker([cluster.lat, cluster.lon], { icon: clusterIcon });

                // Al pulsar el cluster: abrir abanico radial (Spiderify con zoom inteligente)
                clusterMarker.on('click', (e) => {
                    L.DomEvent.stopPropagation(e);
                    openClusterWithZoom(cluster);
                });

                cluster.marker = clusterMarker;
                mapMarkersLayer.addLayer(clusterMarker);
            }
        });

        if (map) {
            if (bounds.length > 0) {
                map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
            } else {
                map.setView([40.4168, -3.7038], 6);
            }
            setTimeout(() => {
                try { map.invalidateSize(); } catch(e) {}
            }, 60);
        }
    }

    // Trigger Ingestion Pipeline (Guaranteed execution without serverless freezing)
    btnRunPipeline.addEventListener('click', async () => {
        try {
            btnRunPipeline.disabled = true;
            document.getElementById('text-run').textContent = 'Escaneando...';

            showToast('🔍 Escáner activado. Sincronizando Subastas BOE, Desarrollos PGOU y Oportunidades de Mercado...', 'info');

            // 1. Lanzar la sincronización garantizada en el servidor
            const res = await fetch('/api/v1/pipeline/run?sync=true', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${state.token}` }
            });

            if (res.status === 401) {
                logout();
                return;
            }

            if (!res.ok) throw new Error('Error durante el escaneado');
            const data = await res.json();
            const subCount = data?.result?.raw_auctions_processed || 'varias';
            const mktCount = data?.result?.market_total || 0;
            const newMkt = data?.result?.new_market_detected || 0;

            showToast(`✅ Escáner completado: ${subCount} subastas y ${mktCount} oportunidades de Mercado (${newMkt} novedades) sincronizadas.`, 'success');

            // 2. Refrescar datos en el mapa y listado
            await fetchOpportunities(true);

        } catch (err) {
            showToast(`Aviso: ${err.message}`, 'info');
            await fetchOpportunities(true);
        } finally {
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

    function isSolarOpportunity(opp) {
        if (!opp) return false;
        if (opp.source_type === 'pgou') return true;
        if (opp.strategy === 'LAND_DEVELOPMENT') return true;
        const pt = (opp.property_type || '').toLowerCase();
        if (pt.includes('solar') || pt.includes('suelo') || pt.includes('terreno') || pt.includes('parcela')) return true;
        return false;
    }

    function getBtlStyle(rentalYield) {
        if (rentalYield === null || rentalYield === undefined || isNaN(rentalYield)) {
            return { bg: 'rgba(239, 68, 68, 0.22)', border: '#ef4444', color: '#f87171', pts: 0 };
        }
        const y = parseFloat(rentalYield);
        if (y >= 7.0) {
            return { bg: 'rgba(34, 197, 94, 0.22)', border: '#22c55e', color: '#4ade80', pts: 100 };
        } else if (y >= 6.0) {
            return { bg: 'rgba(234, 179, 8, 0.22)', border: '#eab308', color: '#fde047', pts: 90 };
        } else if (y >= 5.0) {
            return { bg: 'rgba(249, 115, 22, 0.22)', border: '#f97316', color: '#fb923c', pts: 80 };
        } else if (y >= 4.0) {
            // Naranja degradado hacia rojo (sin azul, color más rojo)
            return { bg: 'rgba(234, 88, 12, 0.25)', border: '#ea580c', color: '#fb923c', pts: 50 };
        } else {
            return { bg: 'rgba(239, 68, 68, 0.22)', border: '#ef4444', color: '#f87171', pts: 0 };
        }
    }

    function renderBtlBadge(opp, context = 'card') {
        if (!opp || isSolarOpportunity(opp)) return '';
        if (opp.rental_yield === undefined || opp.rental_yield === null) return '';
        const yNum = parseFloat(opp.rental_yield);
        if (isNaN(yNum) || yNum <= 0) return '';

        const style = getBtlStyle(yNum);
        const pts = (opp.btl_score !== undefined && opp.btl_score !== null) ? Math.round(opp.btl_score) : style.pts;
        const yieldFormatted = yNum.toFixed(2).replace('.', ',');
        const label = `${yieldFormatted}% BTL (${pts} pts)`;

        if (context === 'modal') {
            return `<span class="score-chip" title="Estrategia Buy to Let (Rentabilidad Bruta Alquiler)" style="background: ${style.bg}; border: 1px solid ${style.border}; color: ${style.color}; padding: 3px 8px; border-radius: 6px; font-size: 0.78rem; font-weight: 700; white-space: nowrap; text-align: right; display: inline-block;">
                <strong>${label}</strong>
            </span>`;
        }

        return `<span class="score-chip" title="Estrategia Buy to Let (Rentabilidad Bruta Alquiler)" style="background: ${style.bg}; border: 1px solid ${style.border}; color: ${style.color};">
            <strong>${label}</strong>
        </span>`;
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
