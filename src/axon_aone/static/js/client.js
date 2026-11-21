/**
 * Axon Trading Web Client
 * Real-time trading interface with WebSocket support
 */

// ============ Socket.IO Connection ============
const socket = io();

// ============ Global State ============
let appState = {
    orders: [],
    schedulerOrders: [],
    positions: [],
    portfolio: {
        total_capital: 100000,
        current_value: 100000,
        daily_pnl: 0,
        cash_available: 100000
    },
    marketStatus: 'CLOSED',
    stats: {
        total_trades: 0,
        filled_trades: 0,
        cancelled_trades: 0,
        buy_orders: 0,
        sell_orders: 0,
        open_positions: 0
    },
    ticks: {},  // symbol -> { symbol, token, ltp, raw }
    globalState: {
        manualKill: false,
        tradeMode: 'mock'
    }
};

// ============ Initialize ============
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing Axon Trading Interface...');
    
    initializeEventListeners();
    loadMarketStatus();
    loadGlobalState();
    loadStats();
    loadOrders();
    loadSchedulerOrders();
    loadPositions();
    loadPortfolio();
    startPolling();
});

// ============ Event Listeners ============
function initializeEventListeners() {
    // Tab navigation
    const navTabs = document.querySelectorAll('.nav-tab');
    navTabs.forEach(tab => {
        tab.addEventListener('click', function() {
            switchTab(this.dataset.tab);
        });
    });
    
    // Trade form submission
    const tradeForm = document.getElementById('trade-form');
    if (tradeForm) {
        tradeForm.addEventListener('submit', handleTradeSubmit);
    }
    
    // Order type change
    const orderType = document.getElementById('order-type');
    if (orderType) {
        orderType.addEventListener('change', function() {
            const priceGroup = document.getElementById('price-group');
            if (this.value === 'LIMIT') {
                priceGroup.style.display = 'flex';
            } else {
                priceGroup.style.display = 'none';
            }
        });
    }
    
    // Filter inputs
    const filterSymbol = document.getElementById('filter-symbol');
    const filterStatus = document.getElementById('filter-status');
    if (filterSymbol) {
        filterSymbol.addEventListener('input', filterOrders);
    }
    if (filterStatus) {
        filterStatus.addEventListener('change', filterOrders);
    }

    // Scheduler filter inputs
    const schedFilterSymbol = document.getElementById('scheduler-filter-symbol');
    const schedFilterStatus = document.getElementById('scheduler-filter-status');
    if (schedFilterSymbol) {
        schedFilterSymbol.addEventListener('input', filterSchedulerOrders);
    }
    if (schedFilterStatus) {
        schedFilterStatus.addEventListener('change', filterSchedulerOrders);
    }
    
    // Modal close
    const modal = document.getElementById('order-modal');
    const modalClose = document.querySelector('.modal-close');
    const btnClose = document.querySelector('.btn-close');
    
    if (modalClose) {
        modalClose.addEventListener('click', () => modal.classList.remove('show'));
    }
    if (btnClose) {
        btnClose.addEventListener('click', () => modal.classList.remove('show'));
    }
    
    // Close modal when clicking outside
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('show');
            }
        });
    }
}

// ============ Tab Navigation ============
function switchTab(tabName) {
    // Hide all tabs
    const tabs = document.querySelectorAll('.tab-content');
    tabs.forEach(tab => tab.classList.remove('active'));
    
    // Remove active from all nav tabs
    const navTabs = document.querySelectorAll('.nav-tab');
    navTabs.forEach(tab => tab.classList.remove('active'));
    
    // Show selected tab
    const selectedTab = document.getElementById(`tab-${tabName}`);
    if (selectedTab) {
        selectedTab.classList.add('active');
    }
    
    // Mark nav tab as active
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
}

// ============ API Calls ============
async function apiCall(endpoint, method = 'GET', data = null) {
    try {
        const options = {
            method,
            headers: {
                'Content-Type': 'application/json',
            }
        };
        
        if (data && method !== 'GET') {
            options.body = JSON.stringify(data);
        }
        
        const response = await fetch(endpoint, options);
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || `HTTP ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error(`API Error (${endpoint}):`, error);
        throw error;
    }
}

// ============ Market Status ============
async function loadMarketStatus() {
    try {
        const data = await apiCall('/api/market-status');
        appState.marketStatus = data.status;
        
        const statusIndicator = document.getElementById('status-indicator');
        const statusText = document.getElementById('status-text');
        
        if (statusIndicator) {
            statusIndicator.classList.toggle('open', data.status === 'OPEN');
        }
        if (statusText) {
            statusText.textContent = `${data.status} - ${data.details}`;
        }
    } catch (error) {
        console.error('Error loading market status:', error);
    }
}

// ============ Stats ============
async function loadStats() {
    try {
        const data = await apiCall('/api/stats');
        appState.stats = data;
        
        document.getElementById('stat-total').textContent = data.total_trades;
        document.getElementById('stat-filled').textContent = data.filled_trades;
        document.getElementById('stat-positions').textContent = data.open_positions;
        document.getElementById('stat-pnl').textContent = `$${data.portfolio.daily_pnl.toFixed(2)}`;
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// ============ Global State (Kill Switch & Mode) ============
async function loadGlobalState() {
    try {
        const data = await apiCall('/api/global-state');
        appState.globalState.manualKill = !!data.manual_kill;
        appState.globalState.tradeMode = (data.trade_mode || 'mock');
        renderGlobalStateBanner();
    } catch (error) {
        console.error('Error loading global state:', error);
    }
}

function renderGlobalStateBanner() {
    const banner = document.getElementById('global-state-banner');
    const modeSpan = document.getElementById('global-mode-text');
    const killSpan = document.getElementById('global-kill-text');

    if (!banner || !modeSpan || !killSpan) return;

    const mode = appState.globalState.tradeMode === 'live' ? 'LIVE' : 'MOCK';
    const killActive = appState.globalState.manualKill;

    modeSpan.textContent = mode;
    killSpan.textContent = killActive ? 'ON' : 'OFF';

    banner.classList.toggle('kill-active', killActive);
}

// ============ Orders ============
async function loadOrders() {
    try {
        const data = await apiCall('/api/orders');
        appState.orders = data.orders || [];
        renderOrders(appState.orders);
    } catch (error) {
        console.error('Error loading orders:', error);
    }
}

// ============ Scheduler Orders ============
async function loadSchedulerOrders() {
    try {
        const data = await apiCall('/api/scheduler/orders');
        appState.schedulerOrders = data.orders || [];
        renderSchedulerOrders(appState.schedulerOrders);
    } catch (error) {
        console.error('Error loading scheduler orders:', error);
    }
}

function renderSchedulerOrders(orders) {
    const tableBody = document.getElementById('scheduler-orders-table-body');

    if (!tableBody) return;

    if (orders.length === 0) {
        tableBody.innerHTML = '<tr class="empty-state"><td colspan="7">No scheduler orders yet. Scheduler will populate this list when trades are triggered.</td></tr>';
        return;
    }

    tableBody.innerHTML = orders.map(order => `
        <tr>
            <td><strong>${order.id}</strong></td>
            <td>${order.symbol}</td>
            <td>
                <span class="${order.side === 'BUY' ? 'buy-badge' : 'sell-badge'}">
                    ${order.side}
                </span>
            </td>
            <td>${order.quantity}</td>
            <td>
                <span class="status-badge status-${(order.status || '').toLowerCase()}">
                    ${order.status || 'UNKNOWN'}
                </span>
            </td>
            <td>
                <span class="status-badge status-${(order.trade_mode || 'mock')}">
                    ${(order.trade_mode || 'mock').toUpperCase()}
                </span>
            </td>
            <td>${formatTime(order.timestamp)}</td>
        </tr>
    `).join('');
}

function filterSchedulerOrders() {
    const symbol = document.getElementById('scheduler-filter-symbol').value.toUpperCase();
    const status = document.getElementById('scheduler-filter-status').value;

    let filtered = appState.schedulerOrders;

    if (symbol) {
        filtered = filtered.filter(o => (o.symbol || '').toUpperCase().includes(symbol));
    }
    if (status) {
        filtered = filtered.filter(o => o.status === status);
    }

    renderSchedulerOrders(filtered);
}

function renderOrders(orders) {
    const tableBody = document.getElementById('orders-table-body');
    
    if (!tableBody) return;
    
    if (orders.length === 0) {
        tableBody.innerHTML = '<tr class="empty-state"><td colspan="9">No orders yet. Place a trade to get started.</td></tr>';
        return;
    }
    
    tableBody.innerHTML = orders.map(order => `
        <tr onclick="showOrderDetails('${order.id}')">
            <td><strong>${order.id}</strong></td>
            <td>${order.symbol}</td>
            <td>
                <span class="${order.side === 'BUY' ? 'buy-badge' : 'sell-badge'}">
                    ${order.side}
                </span>
            </td>
            <td>${order.quantity}</td>
            <td>${order.order_type}</td>
            <td>
                <span class="status-badge status-${order.status.toLowerCase()}">
                    ${order.status}
                </span>
            </td>
            <td>
                <span class="status-badge status-${order.trade_mode}">
                    ${order.trade_mode.toUpperCase()}
                </span>
            </td>
            <td>${formatTime(order.timestamp)}</td>
            <td>
                ${order.status === 'PENDING' ? `
                    <button class="btn-secondary" onclick="cancelOrder('${order.id}', event)">Cancel</button>
                ` : '-'}
            </td>
        </tr>
    `).join('');
}

function filterOrders() {
    const symbol = document.getElementById('filter-symbol').value.toUpperCase();
    const status = document.getElementById('filter-status').value;
    
    let filtered = appState.orders;
    
    if (symbol) {
        filtered = filtered.filter(o => o.symbol.includes(symbol));
    }
    if (status) {
        filtered = filtered.filter(o => o.status === status);
    }
    
    renderOrders(filtered);
}

function showOrderDetails(orderId) {
    const order = appState.orders.find(o => o.id === orderId);
    if (!order) return;
    
    const modal = document.getElementById('order-modal');
    const modalBody = document.getElementById('modal-body');
    
    const brokerResponse = order.broker_response ? JSON.stringify(order.broker_response, null, 2) : 'N/A';
    
    modalBody.innerHTML = `
        <div><span class="label">Order ID:</span><span class="value">${order.id}</span></div>
        <div><span class="label">Symbol:</span><span class="value">${order.symbol}</span></div>
        <div><span class="label">Side:</span><span class="value">${order.side}</span></div>
        <div><span class="label">Quantity:</span><span class="value">${order.quantity}</span></div>
        <div><span class="label">Filled:</span><span class="value">${order.filled_quantity}</span></div>
        <div><span class="label">Status:</span><span class="value">${order.status}</span></div>
        <div><span class="label">Order Type:</span><span class="value">${order.order_type}</span></div>
        <div><span class="label">Price:</span><span class="value">${order.price || 'Market'}</span></div>
        <div><span class="label">Mode:</span><span class="value">${order.trade_mode.toUpperCase()}</span></div>
        <div><span class="label">Time:</span><span class="value">${formatTime(order.timestamp)}</span></div>
        <div style="margin-top: 1rem; white-space: pre-wrap; background: #1a3a52; padding: 1rem; border-radius: 4px; font-size: 0.85rem;">
            <span class="label">Response:</span>
            <br><code>${brokerResponse}</code>
        </div>
    `;
    
    modal.classList.add('show');
}

async function cancelOrder(orderId, event) {
    event.stopPropagation();
    
    if (!confirm('Are you sure you want to cancel this order?')) {
        return;
    }
    
    try {
        const result = await apiCall(`/api/orders/${orderId}/cancel`, 'POST');
        showNotification('Order cancelled successfully', 'success');
        loadOrders();
    } catch (error) {
        showNotification(`Error cancelling order: ${error.message}`, 'error');
    }
}

// ============ Positions ============
async function loadPositions() {
    try {
        const data = await apiCall('/api/positions');
        appState.positions = data.positions || [];
        renderPositions(appState.positions);
    } catch (error) {
        console.error('Error loading positions:', error);
    }
}

function renderPositions(positions) {
    const tableBody = document.getElementById('positions-table-body');
    
    if (!tableBody) return;
    
    if (positions.length === 0) {
        tableBody.innerHTML = '<tr class="empty-state"><td colspan="6">No open positions.</td></tr>';
        return;
    }
    
    tableBody.innerHTML = positions.map(pos => {
        const pnlClass = pos.pnl >= 0 ? 'buy-badge' : 'sell-badge';
        const pnlPercent = pos.pnl_percent >= 0 ? '+' : '';
        
        return `
            <tr>
                <td><strong>${pos.symbol}</strong></td>
                <td>${pos.quantity}</td>
                <td>$${(pos.average_price || 0).toFixed(2)}</td>
                <td>$${(pos.current_price || 0).toFixed(2)}</td>
                <td><span class="${pnlClass}">$${pos.pnl.toFixed(2)}</span></td>
                <td><span class="${pnlClass}">${pnlPercent}${pos.pnl_percent.toFixed(2)}%</span></td>
            </tr>
        `;
    }).join('');
}

// ============ Portfolio ============
async function loadPortfolio() {
    try {
        const data = await apiCall('/api/portfolio');
        appState.portfolio = data;
        renderPortfolio(data);
    } catch (error) {
        console.error('Error loading portfolio:', error);
    }
}

function renderPortfolio(portfolio) {
    const total = portfolio.total_capital || 100000;
    const current = portfolio.current_value || 100000;
    const cash = portfolio.cash_available || 100000;
    const dailyPnL = portfolio.daily_pnl || 0;
    
    document.getElementById('portfolio-total').textContent = `$${total.toFixed(2)}`;
    document.getElementById('portfolio-current').textContent = `$${current.toFixed(2)}`;
    document.getElementById('portfolio-cash').textContent = `$${cash.toFixed(2)}`;
    
    const pnlEl = document.getElementById('portfolio-daily-pnl');
    if (pnlEl) {
        pnlEl.textContent = `$${dailyPnL.toFixed(2)}`;
        pnlEl.style.color = dailyPnL >= 0 ? '#10b981' : '#ef4444';
    }
}

// ============ Trade Submission ============
async function handleTradeSubmit(e) {
    e.preventDefault();
    
    const form = e.target;
    const formData = new FormData(form);
    
    const data = {
        symbol: formData.get('symbol'),
        quantity: parseInt(formData.get('quantity')),
        side: formData.get('side'),
        order_type: formData.get('order_type'),
        price: formData.get('price') ? parseFloat(formData.get('price')) : null,
        trade_mode: formData.get('trade_mode')
    };
    
    // Block locally if manual kill switch is active
    if (appState.globalState.manualKill) {
        showNotification('Manual kill switch is ACTIVE. New trades are blocked.', 'error');
        return;
    }

    // Validate
    if (!data.symbol || !data.quantity) {
        showNotification('Please fill in all required fields', 'error');
        return;
    }
    
    // Show loading state
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = 'Placing Trade...';
    
    try {
        const result = await apiCall('/api/trade', 'POST', data);
        
        showNotification(`Trade order placed: ${result.order_id}`, 'success');
        form.reset();
        
        // Reload data
        setTimeout(() => {
            loadOrders();
            loadStats();
            loadGlobalState();
        }, 500);
        
    } catch (error) {
        showNotification(`Error placing trade: ${error.message}`, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
    }
}

// ============ WebSocket Events ============
socket.on('connect', function() {
    console.log('Connected to server');
    socket.emit('subscribe_updates');
});

socket.on('disconnect', function() {
    console.log('Disconnected from server');
});

socket.on('order_update', function(order) {
    console.log('Order update received:', order);
    
    const existingIndex = appState.orders.findIndex(o => o.id === order.id);
    if (existingIndex >= 0) {
        appState.orders[existingIndex] = order;
    } else {
        appState.orders.push(order);
    }
    
    // Re-render if on orders tab
    const ordersTab = document.getElementById('tab-orders');
    if (ordersTab.classList.contains('active')) {
        renderOrders(appState.orders);
    }
    
    loadStats();
});

socket.on('position_update', function(positions) {
    console.log('Position update received:', positions);
    appState.positions = positions;
    
    const positionsTab = document.getElementById('tab-positions');
    if (positionsTab.classList.contains('active')) {
        renderPositions(positions);
    }
});

socket.on('portfolio_update', function(portfolio) {
    console.log('Portfolio update received:', portfolio);
    appState.portfolio = portfolio;
    
    const portfolioTab = document.getElementById('tab-portfolio');
    if (portfolioTab.classList.contains('active')) {
        renderPortfolio(portfolio);
    }
});

socket.on('market_status', function(data) {
    console.log('Market status update:', data);
    appState.marketStatus = data.status;
    
    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    
    if (statusIndicator) {
        statusIndicator.classList.toggle('open', data.status === 'OPEN');
    }
    if (statusText) {
        statusText.textContent = `${data.status} - ${data.details}`;
    }
});
// Live market data ticks from Angel One MarketFeed (raw payload)
socket.on('tick_update', function(tick) {
    console.log('Tick update received:', tick);
    updateTickFromPayload(tick);
    renderMarketFeed();
});

socket.on('sync_orders', function(orders) {
    console.log('Syncing orders from server');
    appState.orders = orders;
    renderOrders(orders);
});

socket.on('sync_positions', function(positions) {
    console.log('Syncing positions from server');
    appState.positions = positions;
    renderPositions(positions);
});

socket.on('sync_portfolio', function(portfolio) {
    console.log('Syncing portfolio from server');
    appState.portfolio = portfolio;
    renderPortfolio(portfolio);
});

socket.on('sync_ticks', function(ticks) {
    console.log('Syncing ticks from server', ticks);
    if (Array.isArray(ticks)) {
        ticks.forEach(updateTickFromPayload);
        renderMarketFeed();
    }
});

// ============ Polling ============
function startPolling() {
    // Poll every 10 seconds
    setInterval(() => {
        loadMarketStatus();
        loadStats();
        loadSchedulerOrders();
        loadGlobalState();
    }, 10000);
}

// ============ Utilities ============
function formatTime(isoString) {
    try {
        const date = new Date(isoString);
        return date.toLocaleString('en-US', {
            month: 'short',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch {
        return isoString;
    }
}

function showNotification(message, type = 'info') {
    const statusEl = document.getElementById('trade-status');
    if (!statusEl) return;
    
    statusEl.textContent = message;
    statusEl.className = `trade-status ${type}`;
    
    // Auto-hide after 5 seconds
    setTimeout(() => {
        statusEl.className = 'trade-status';
        statusEl.textContent = '';
    }, 5000);
}

// ============ Live Market Feed Rendering ============

function updateTickFromPayload(payload) {
    if (!payload) return;

    // Normalise server payload: may be raw list/dict or already symbol-mapped
    if (Array.isArray(payload)) {
        payload.forEach(updateTickFromPayload);
        return;
    }

    // If payload has top-level data list, expand it
    if (payload.data && Array.isArray(payload.data)) {
        payload.data.forEach(updateTickFromPayload);
        return;
    }

    // Try to extract our normalised form
    let symbol = payload.symbol || payload.tradingsymbol;
    const token = payload.token || payload.symboltoken || payload.tk || payload.token;
    const ltp = payload.ltp || payload.ap || payload.close;

    if (!symbol && payload.raw) {
        const raw = payload.raw;
        symbol = raw.symbol || raw.tradingsymbol || symbol;
    }

    if (!symbol) return;

    appState.ticks[symbol] = {
        symbol,
        token,
        ltp,
        raw: payload.raw || payload
    };
}

function renderMarketFeed() {
    const body = document.getElementById('market-feed-body');
    if (!body) return;

    const symbols = Object.keys(appState.ticks).sort();
    if (symbols.length === 0) {
        body.innerHTML = '<tr class="empty-state"><td colspan="2">Waiting for live ticks...</td></tr>';
        return;
    }

    body.innerHTML = symbols.map(sym => {
        const tick = appState.ticks[sym];
        const price = typeof tick.ltp === 'number' ? tick.ltp.toFixed(2) : (tick.ltp || '—');
        return `
            <tr>
                <td><strong>${sym}</strong></td>
                <td>${price}</td>
            </tr>
        `;
    }).join('');
}
