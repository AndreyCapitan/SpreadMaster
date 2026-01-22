let isPaused = true;
let displayLimit = 15;
let updateInterval = 15000;
let currentExchange = null;
let currentPair = null;
let currentTimeframe = '15m';
let enabledExchanges = new Set();
let enabledPairs = new Set();
let connectedExchanges = new Set();
let previousRanking = new Map();
let previousSpreads = new Map();
let trendLevels = new Map();
let activeContracts = [];
let closedContracts = [];
let autoEntryEnabled = false;
let autoEntryThreshold = 0;
let autoCloseThreshold = 0;
let timerInterval = null;
let currentMode = 'demo';
let aiLoading = false;

function escapeHtml(str) {
    if (typeof str !== 'string') return str;
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatDuration(ms) {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    
    if (days > 0) return `${days}d ${hours % 24}h`;
    if (hours > 0) return `${hours}h ${minutes % 60}m`;
    if (minutes > 0) return `${minutes}m ${seconds % 60}s`;
    return `${seconds}s`;
}

async function loadContracts() {
    try {
        const res = await fetch('/api/contracts');
        if (res.ok) {
            const data = await res.json();
            activeContracts = data.active.map(c => ({
                id: c.id,
                key: c.key,
                pair: c.pair,
                buyEx: c.buyEx,
                sellEx: c.sellEx,
                entrySpread: c.entrySpread,
                currentSpread: c.currentSpread,
                autoClose: c.autoClose,
                closeThreshold: c.closeThreshold,
                openTime: new Date(c.openTime)
            }));
            closedContracts = data.closed.map(c => ({
                id: c.id,
                key: c.key,
                pair: c.pair,
                buyEx: c.buyEx,
                sellEx: c.sellEx,
                entrySpread: c.entrySpread,
                currentSpread: c.currentSpread,
                profit: c.profit,
                openTime: new Date(c.openTime),
                closeTime: c.closeTime ? new Date(c.closeTime) : null,
                duration: c.closeTime && c.openTime ? new Date(c.closeTime) - new Date(c.openTime) : 0
            }));
            renderContracts();
        }
    } catch (e) {
        console.error('Failed to load contracts:', e);
    }
}

async function saveContractToDB(contract) {
    try {
        await fetch('/api/contracts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                key: contract.key,
                pair: contract.pair,
                buyEx: contract.buyEx,
                sellEx: contract.sellEx,
                entrySpread: contract.entrySpread,
                currentSpread: contract.currentSpread,
                autoClose: contract.autoClose,
                closeThreshold: contract.closeThreshold,
                openTime: contract.openTime.toISOString()
            })
        });
    } catch (e) {
        console.error('Failed to save contract:', e);
    }
}

async function closeContractInDB(key, currentSpread) {
    try {
        await fetch('/api/contracts/close-by-key', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key, currentSpread })
        });
    } catch (e) {
        console.error('Failed to close contract in DB:', e);
    }
}

async function loadConnectedExchanges() {
    try {
        const res = await fetch('/api/connected_exchanges');
        if (res.ok) {
            const data = await res.json();
            connectedExchanges = new Set(data.connected || []);
            updateExchangeChipStatus();
        }
    } catch (e) {
        console.error('Failed to load connected exchanges:', e);
    }
}

function updateExchangeChipStatus() {
    document.querySelectorAll('.exchange-chip').forEach(chip => {
        const ex = chip.dataset.exchange;
        if (connectedExchanges.has(ex)) {
            chip.classList.add('connected');
        } else {
            chip.classList.remove('connected');
        }
    });
}

document.addEventListener('DOMContentLoaded', async function() {
    loadTheme();
    setupEventListeners();
    initMode();
    await initState();
    await loadAccounts();
    await loadConnectedExchanges();
    await loadContracts();
    await loadAutoTradeSettings();
    updatePauseUI();
    startContractTimer();
});

function startContractTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
        updateContractTimers();
    }, 1000);
}

function updateContractTimers() {
    const now = Date.now();
    document.querySelectorAll('.contract-timer').forEach(el => {
        const openTime = parseInt(el.dataset.opentime);
        if (openTime) {
            el.textContent = formatDuration(now - openTime);
        }
    });
}

function loadTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const newTheme = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    const icon = document.getElementById('theme-icon');
    if (theme === 'light') {
        icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
    } else {
        icon.innerHTML = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
    }
}

async function initState() {
    try {
        const res = await fetch('/api/state');
        const data = await res.json();
        syncState(data);
        if (data.spreads) {
            updateSpreadList(data.spreads);
        }
    } catch (err) {
        document.querySelectorAll('.exchange-toggle').forEach(toggle => {
            if (toggle.checked) enabledExchanges.add(toggle.dataset.exchange);
        });
        document.querySelectorAll('.pair-toggle').forEach(toggle => {
            if (toggle.checked) enabledPairs.add(toggle.dataset.pair);
        });
        updateCounts();
    }
}

function updateCounts() {
    const exCount = document.getElementById('ex-count');
    const pairsCount = document.getElementById('pairs-count');
    if (exCount) exCount.textContent = enabledExchanges.size;
    if (pairsCount) pairsCount.textContent = enabledPairs.size;
}

function toggleAllExchanges(enable) {
    document.querySelectorAll('.exchange-toggle').forEach(toggle => {
        toggle.checked = enable;
        if (enable) {
            enabledExchanges.add(toggle.dataset.exchange);
        } else {
            enabledExchanges.delete(toggle.dataset.exchange);
        }
    });
    updateCounts();
    saveState();
}

function toggleAllPairs(enable) {
    document.querySelectorAll('.pair-toggle').forEach(toggle => {
        toggle.checked = enable;
        if (enable) {
            enabledPairs.add(toggle.dataset.pair);
        } else {
            enabledPairs.delete(toggle.dataset.pair);
        }
    });
    updateCounts();
    saveState();
}

function showConnectedExchanges() {
    document.querySelectorAll('.exchange-toggle').forEach(toggle => {
        const ex = toggle.dataset.exchange;
        const isConnected = connectedExchanges.has(ex);
        toggle.checked = isConnected;
        if (isConnected) {
            enabledExchanges.add(ex);
        } else {
            enabledExchanges.delete(ex);
        }
    });
    updateCounts();
    saveState();
}

async function showAvailablePairs() {
    try {
        const res = await fetch('/api/available_pairs?' + new URLSearchParams({
            exchanges: Array.from(enabledExchanges).join(',')
        }));
        if (res.ok) {
            const data = await res.json();
            const availablePairs = new Set(data.pairs || []);
            
            document.querySelectorAll('.pair-toggle').forEach(toggle => {
                const pair = toggle.dataset.pair;
                const isAvailable = availablePairs.has(pair);
                toggle.checked = isAvailable;
                if (isAvailable) {
                    enabledPairs.add(pair);
                } else {
                    enabledPairs.delete(pair);
                }
            });
            updateCounts();
            saveState();
        }
    } catch (e) {
        console.error('Failed to get available pairs:', e);
    }
}

function setupEventListeners() {
    document.getElementById('pause-btn').addEventListener('click', togglePause);
    document.getElementById('theme-btn').addEventListener('click', toggleTheme);
    document.getElementById('close-modal').addEventListener('click', closeModal);
    document.getElementById('settings-btn').addEventListener('click', openSettingsModal);
    
    document.querySelectorAll('.interval-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.interval-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            updateInterval = parseInt(this.dataset.interval);
            if (!isPaused) restartPolling();
        });
    });
    
    document.querySelectorAll('.limit-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.limit-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            displayLimit = parseInt(this.dataset.limit);
        });
    });
    
    document.querySelectorAll('.exchange-toggle').forEach(toggle => {
        toggle.addEventListener('change', function() {
            if (this.checked) {
                enabledExchanges.add(this.dataset.exchange);
            } else {
                enabledExchanges.delete(this.dataset.exchange);
            }
            toggleExchange(this.dataset.exchange, this.checked);
            updateCounts();
        });
    });
    
    document.querySelectorAll('.pair-toggle').forEach(toggle => {
        toggle.addEventListener('change', function() {
            if (this.checked) {
                enabledPairs.add(this.dataset.pair);
            } else {
                enabledPairs.delete(this.dataset.pair);
            }
            togglePair(this.dataset.pair);
            updateCounts();
        });
    });
    
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            currentTimeframe = this.dataset.tf;
            if (currentExchange && currentPair) {
                loadStochastic(currentExchange, currentPair);
            }
        });
    });
    
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', function(e) {
            if (e.target === this) this.classList.remove('active');
        });
    });
    
    document.getElementById('add-account-btn').addEventListener('click', showAccountForm);
    document.getElementById('save-account-btn').addEventListener('click', saveAccount);
    document.getElementById('cancel-account-btn').addEventListener('click', hideAccountForm);
    
    const saveEmailBtn = document.getElementById('save-email-btn');
    if (saveEmailBtn) {
        saveEmailBtn.addEventListener('click', saveEmail);
    }
}

async function saveEmail() {
    const emailInput = document.getElementById('profile-email');
    const email = emailInput.value.trim();
    
    try {
        const res = await fetch('/api/user/email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });
        const data = await res.json();
        
        if (data.error) {
            alert(data.error);
        } else {
            emailInput.value = data.email;
            alert('Email saved!');
        }
    } catch (err) {
        console.error('Error saving email:', err);
    }
}

let pollingInterval = null;

function startPolling() {
    if (isPaused) return;
    fetchStateNow();
    pollingInterval = window.setInterval(fetchStateNow, updateInterval);
}

function fetchStateNow() {
    fetch('/api/state')
        .then(res => res.json())
        .then(data => {
            syncState(data);
            updateSpreadList(data.spreads);
        })
        .catch(err => console.error('Fetch error:', err));
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function restartPolling() {
    stopPolling();
    if (!isPaused) {
        pollingInterval = window.setInterval(fetchStateNow, updateInterval);
    }
}


function syncState(data) {
    if (data.enabled_exchanges) {
        enabledExchanges = new Set(data.enabled_exchanges);
        document.querySelectorAll('.exchange-toggle').forEach(toggle => {
            toggle.checked = enabledExchanges.has(toggle.dataset.exchange);
        });
    }
    if (data.selected_pairs) {
        enabledPairs = new Set(data.selected_pairs);
        document.querySelectorAll('.pair-toggle').forEach(toggle => {
            toggle.checked = enabledPairs.has(toggle.dataset.pair);
        });
    }
    updateCounts();
}

function updateSpreadList(spreads) {
    const container = document.getElementById('spread-list');
    
    if (!spreads || spreads.length === 0) {
        container.innerHTML = '<div class="empty-state">Loading data...</div>';
        return;
    }
    
    const filtered = spreads.filter(s => 
        enabledExchanges.has(s.bid_exchange) && 
        enabledExchanges.has(s.ask_exchange) && 
        enabledPairs.has(s.pair)
    );
    
    if (filtered.length === 0) {
        container.innerHTML = '<div class="empty-state">No spreads for selection</div>';
        return;
    }
    
    const sorted = [...filtered].sort((a, b) => b.spread_percent - a.spread_percent).slice(0, displayLimit);
    
    const newRanking = new Map();
    sorted.forEach((s, idx) => {
        const key = `${s.pair}-${s.bid_exchange}-${s.ask_exchange}`;
        newRanking.set(key, idx);
    });
    
    container.scrollTop = 0;
    
    container.innerHTML = '';
    sorted.forEach((s, idx) => {
        const key = `${s.pair}-${s.bid_exchange}-${s.ask_exchange}`;
        const prevIdx = previousRanking.get(key);
        let animClass = '';
        if (prevIdx !== undefined && prevIdx !== idx) {
            animClass = prevIdx > idx ? 'moving-up' : 'moving-down';
        }
        
        const trendLevel = updateTrendLevel(key, s.spread_percent);
        const indicator = getTrendIndicator(trendLevel);
        
        const hasContract = activeContracts.some(c => c.key === key);
        
        const item = document.createElement('div');
        item.className = 'spread-item' + (animClass ? ' ' + animClass : '');
        item.style.background = getRowBg(s.color);
        item.dataset.key = key;
        
        const trendDiv = document.createElement('div');
        trendDiv.className = 'trend-indicator';
        for (let i = 0; i < 6; i++) {
            const bar = document.createElement('span');
            bar.className = `bar bar-${i + 1} ${indicator[i] || ''}`;
            trendDiv.appendChild(bar);
        }
        item.appendChild(trendDiv);
        
        const infoDiv = document.createElement('div');
        infoDiv.className = 'spread-info';
        infoDiv.addEventListener('click', () => openChart(s.bid_exchange, s.pair));
        
        const pairDiv = document.createElement('div');
        pairDiv.className = 'spread-pair';
        pairDiv.textContent = s.pair.split('/')[0];
        infoDiv.appendChild(pairDiv);
        
        const routeDiv = document.createElement('div');
        routeDiv.className = 'spread-route';
        const askSpan = document.createElement('span');
        askSpan.className = connectedExchanges.has(s.ask_exchange) ? 'ex-connected' : 'ex-disconnected';
        askSpan.textContent = s.ask_exchange.toUpperCase();
        routeDiv.appendChild(askSpan);
        routeDiv.appendChild(document.createTextNode(' → '));
        const bidSpan = document.createElement('span');
        bidSpan.className = connectedExchanges.has(s.bid_exchange) ? 'ex-connected' : 'ex-disconnected';
        bidSpan.textContent = s.bid_exchange.toUpperCase();
        routeDiv.appendChild(bidSpan);
        infoDiv.appendChild(routeDiv);
        item.appendChild(infoDiv);
        
        const pricesDiv = document.createElement('div');
        pricesDiv.className = 'spread-prices';
        pricesDiv.addEventListener('click', () => openChart(s.bid_exchange, s.pair));
        const buyPrice = document.createElement('div');
        buyPrice.className = 'spread-price';
        buyPrice.textContent = 'B: ' + formatPrice(s.ask_price);
        pricesDiv.appendChild(buyPrice);
        const sellPrice = document.createElement('div');
        sellPrice.className = 'spread-price';
        sellPrice.textContent = 'S: ' + formatPrice(s.bid_price);
        pricesDiv.appendChild(sellPrice);
        item.appendChild(pricesDiv);
        
        const valueSpan = document.createElement('span');
        valueSpan.className = 'spread-value';
        valueSpan.style.color = s.color;
        valueSpan.textContent = s.spread_percent.toFixed(3) + '%';
        item.appendChild(valueSpan);
        
        const btn = document.createElement('button');
        btn.className = 'contract-btn' + (hasContract ? ' active' : '');
        btn.textContent = 'C';
        btn.addEventListener('click', (event) => {
            event.stopPropagation();
            openContract(key, s.spread_percent, s.pair, s.ask_exchange, s.bid_exchange);
        });
        item.appendChild(btn);
        
        container.appendChild(item);
    });
    
    previousRanking = newRanking;
    
    sorted.forEach(s => {
        const key = `${s.pair}-${s.bid_exchange}-${s.ask_exchange}`;
        previousSpreads.set(key, s.spread_percent);
    });
    
    setTimeout(() => {
        container.querySelectorAll('.spread-item').forEach(el => {
            el.classList.remove('moving-up', 'moving-down');
        });
    }, 600);
    
    updateActiveContracts(spreads);
}

function openContract(key, spread, pair, buyEx, sellEx) {
    const existing = activeContracts.findIndex(c => c.key === key);
    if (existing >= 0) {
        return;
    }
    
    const contract = {
        key: key,
        pair: pair,
        buyEx: buyEx,
        sellEx: sellEx,
        entrySpread: spread,
        currentSpread: spread,
        openTime: new Date(),
        autoClose: false,
        closeThreshold: 0
    };
    
    activeContracts.push(contract);
    saveContractToDB(contract);
    
    renderContracts();
    fetchSpreads();
}

function closeContract(key, isAuto = false) {
    const idx = activeContracts.findIndex(c => c.key === key);
    if (idx >= 0) {
        const contract = activeContracts[idx];
        const profit = contract.entrySpread - contract.currentSpread;
        const duration = Date.now() - contract.openTime.getTime();
        
        closedContracts.unshift({
            ...contract,
            closeTime: new Date(),
            profit: profit,
            autoClose: isAuto,
            duration: duration
        });
        
        if (closedContracts.length > 100) closedContracts.pop();
        
        closeContractInDB(key, contract.currentSpread);
        activeContracts.splice(idx, 1);
        renderContracts();
    }
}

function monitorSpreadGrowth(spreads) {
    if (currentMode !== 'ml') return;
    
    const now = Date.now();
    let significantChanges = [];
    
    spreads.forEach(s => {
        const key = `${s.pair}-${s.bid_exchange}-${s.ask_exchange}`;
        const current = s.spread_percent;
        const prev = spreadHistory.get(key);
        
        if (prev !== undefined) {
            const change = current - prev;
            const changePercent = prev !== 0 ? (change / prev) * 100 : 0;
            
            if (Math.abs(changePercent) > 20 && Math.abs(change) > 0.1) {
                significantChanges.push({
                    pair: s.pair,
                    from: prev,
                    to: current,
                    change: change,
                    exchanges: `${s.bid_exchange}-${s.ask_exchange}`
                });
            }
        }
        
        spreadHistory.set(key, current);
    });
    
    if (significantChanges.length > 0 && (now - lastAiWarningTime) > 30000) {
        lastAiWarningTime = now;
        const warning = significantChanges.slice(0, 3).map(c => 
            `${c.pair}: ${c.change > 0 ? '+' : ''}${c.change.toFixed(2)}%`
        ).join(', ');
        addAiMessage(`Spread alert: ${warning}`, 'warning');
    }
}

function updateActiveContracts(spreads) {
    if (!spreads) return;
    
    monitorSpreadGrowth(spreads);
    
    if (autoEntryThreshold > 0) {
        spreads.forEach(s => {
            const key = `${s.pair}-${s.bid_exchange}-${s.ask_exchange}`;
            if (s.spread_percent >= autoEntryThreshold && 
                !activeContracts.some(c => c.key === key) &&
                enabledExchanges.has(s.bid_exchange) && 
                enabledExchanges.has(s.ask_exchange) && 
                enabledPairs.has(s.pair)) {
                const contract = {
                    key: key,
                    pair: s.pair,
                    buyEx: s.ask_exchange,
                    sellEx: s.bid_exchange,
                    entrySpread: s.spread_percent,
                    currentSpread: s.spread_percent,
                    openTime: new Date(),
                    autoClose: autoCloseThreshold > 0,
                    closeThreshold: autoCloseThreshold
                };
                activeContracts.push(contract);
                saveContractToDB(contract);
            }
        });
    }
    
    if (activeContracts.length === 0) {
        renderContracts();
        return;
    }
    
    const toClose = [];
    
    activeContracts.forEach(contract => {
        const spread = spreads.find(s => {
            const key = `${s.pair}-${s.bid_exchange}-${s.ask_exchange}`;
            return key === contract.key;
        });
        if (spread) {
            contract.currentSpread = spread.spread_percent;
            
            if (contract.autoClose && contract.closeThreshold > 0 && contract.currentSpread <= contract.closeThreshold) {
                console.log('Auto-closing:', contract.key, 'current:', contract.currentSpread, 'threshold:', contract.closeThreshold);
                toClose.push(contract.key);
            }
        }
    });
    
    toClose.forEach(key => closeContract(key, true));
    
    renderContracts();
}

function updateAutoEntryThreshold(value) {
    const val = parseFloat(value);
    autoEntryThreshold = val;
    autoEntryEnabled = val > 0 || autoCloseThreshold > 0;
    
    const label = document.getElementById('auto-entry-label');
    const btn = document.getElementById('auto-entry-btn');
    const slider = document.getElementById('auto-entry-slider');
    
    if (label) label.textContent = val > 0 ? val.toFixed(2) + '%' : 'OFF';
    if (slider) slider.value = val;
    if (btn) btn.classList.toggle('active', autoEntryEnabled);
    
    saveAutoTradeSettings();
}

function updateAutoCloseThreshold(value) {
    const val = parseFloat(value);
    autoCloseThreshold = val;
    autoEntryEnabled = autoEntryThreshold > 0 || val > 0;
    
    const label = document.getElementById('auto-close-label');
    const btn = document.getElementById('auto-entry-btn');
    const slider = document.getElementById('auto-close-slider');
    
    if (label) label.textContent = val > 0 ? val.toFixed(2) + '%' : 'OFF';
    if (slider) slider.value = val;
    if (btn) btn.classList.toggle('active', autoEntryEnabled);
    
    saveAutoTradeSettings();
}

function adjustAutoEntry(delta) {
    const newVal = Math.max(0, Math.min(2.0, autoEntryThreshold + delta));
    updateAutoEntryThreshold(newVal);
}

function adjustAutoClose(delta) {
    const newVal = Math.max(0, Math.min(2.0, autoCloseThreshold + delta));
    updateAutoCloseThreshold(newVal);
}

function toggleAutoClose(key) {
    const contract = activeContracts.find(c => c.key === key);
    if (contract) {
        contract.autoClose = !contract.autoClose;
        renderContracts();
    }
}

let autonomousEnabled = false;
let maxContracts = 5;
let bankPercent = 10;
let spreadHistory = new Map();
let lastAiWarningTime = 0;

async function loadAutoTradeSettings() {
    try {
        const res = await fetch('/api/auto_trade');
        if (res.ok) {
            const data = await res.json();
            autonomousEnabled = data.auto_enabled;
            
            const toggle = document.getElementById('autonomous-toggle');
            if (toggle) toggle.checked = autonomousEnabled;
            
            if (data.open_threshold > 0) {
                updateAutoEntryThreshold(data.open_threshold);
            }
            if (data.close_threshold > 0) {
                updateAutoCloseThreshold(data.close_threshold);
            }
            if (data.max_contracts) {
                maxContracts = data.max_contracts;
                const input = document.getElementById('max-contracts-input');
                if (input) input.value = maxContracts;
            }
            if (data.bank_percent) {
                bankPercent = data.bank_percent;
                const input = document.getElementById('bank-percent-input');
                if (input) input.value = bankPercent;
            }
        }
    } catch (e) {
        console.error('Failed to load auto trade settings:', e);
    }
}

async function toggleAutonomousMode(enabled) {
    autonomousEnabled = enabled;
    
    try {
        await fetch('/api/auto_trade', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                auto_enabled: enabled,
                open_threshold: autoEntryThreshold,
                close_threshold: autoCloseThreshold,
                max_contracts: 5
            })
        });
        
        const label = document.querySelector('.auto-label');
        if (label) label.style.color = enabled ? '#22c55e' : '';
        
    } catch (e) {
        console.error('Failed to toggle autonomous mode:', e);
    }
}

async function saveAutoTradeSettings() {
    if (!autonomousEnabled) return;
    
    try {
        await fetch('/api/auto_trade', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                auto_enabled: autonomousEnabled,
                open_threshold: autoEntryThreshold,
                close_threshold: autoCloseThreshold,
                max_contracts: maxContracts,
                bank_percent: bankPercent
            })
        });
    } catch (e) {
        console.error('Failed to save auto trade settings:', e);
    }
}

function updateMaxContracts(value) {
    const val = parseInt(value);
    maxContracts = Math.max(1, Math.min(20, val));
    const input = document.getElementById('max-contracts-input');
    if (input) input.value = maxContracts;
    saveAutoTradeSettings();
}

function adjustMaxContracts(delta) {
    updateMaxContracts(maxContracts + delta);
}

function updateBankPercent(value) {
    const val = parseInt(value);
    bankPercent = Math.max(1, Math.min(100, val));
    const input = document.getElementById('bank-percent-input');
    if (input) input.value = bankPercent;
    saveAutoTradeSettings();
}

function adjustBankPercent(delta) {
    updateBankPercent(bankPercent + delta);
}

function promptAutoEntry() {
    const val = prompt('Enter open threshold (0-2%):', autoEntryThreshold.toFixed(2));
    if (val !== null) {
        const num = parseFloat(val);
        if (!isNaN(num) && num >= 0 && num <= 2) {
            updateAutoEntryThreshold(num);
        }
    }
}

function promptAutoClose() {
    const val = prompt('Enter close threshold (0-2%):', autoCloseThreshold.toFixed(2));
    if (val !== null) {
        const num = parseFloat(val);
        if (!isNaN(num) && num >= 0 && num <= 2) {
            updateAutoCloseThreshold(num);
        }
    }
}

async function resetTotalStats() {
    if (!confirm('Reset total profit statistics?')) return;
    
    closedContracts = [];
    try {
        await fetch('/api/contracts/history', { method: 'DELETE' });
    } catch (e) {
        console.error('Failed to reset history:', e);
    }
    updateTotalProfit();
    document.getElementById('history-count').textContent = '0';
}

async function resetHistory() {
    if (!confirm('Clear all closed contracts history?')) return;
    
    closedContracts = [];
    try {
        await fetch('/api/contracts/history', { method: 'DELETE' });
    } catch (e) {
        console.error('Failed to clear history:', e);
    }
    renderHistoryList();
    updateTotalProfit();
    document.getElementById('history-count').textContent = '0';
}

function updateCloseThreshold(key, value) {
    const contract = activeContracts.find(c => c.key === key);
    if (contract) {
        contract.closeThreshold = parseFloat(value);
        const label = document.querySelector(`.threshold-label[data-key="${key}"]`);
        if (label) label.textContent = parseFloat(value).toFixed(2) + '%';
    }
}

function getTotalProfit() {
    return closedContracts.reduce((sum, c) => sum + c.profit, 0);
}

function showClosedContracts() {
    const modal = document.getElementById('history-modal');
    if (modal) {
        renderHistoryList();
        modal.classList.add('active');
    }
}

function closeHistoryModal() {
    const modal = document.getElementById('history-modal');
    if (modal) modal.classList.remove('active');
}

function renderHistoryList() {
    const container = document.getElementById('history-list');
    if (!container) return;
    
    if (closedContracts.length === 0) {
        container.innerHTML = '<div class="empty-contracts">No closed contracts</div>';
        return;
    }
    
    container.innerHTML = closedContracts.map(c => {
        const pnlClass = c.profit >= 0 ? 'profit' : 'loss';
        const autoLabel = c.autoClose ? '(A)' : '';
        const durationStr = c.duration ? formatDuration(c.duration) : '';
        const safePair = escapeHtml(c.pair.split('/')[0]);
        const safeBuyEx = escapeHtml(c.buyEx.toUpperCase());
        const safeSellEx = escapeHtml(c.sellEx.toUpperCase());
        return `
        <div class="contract-item closed">
            <div class="contract-info">
                <span class="contract-pair">${safePair}</span>
                <span class="contract-route">${safeBuyEx}↔${safeSellEx}</span>
                ${durationStr ? `<span class="contract-duration">${durationStr}</span>` : ''}
            </div>
            <div class="contract-spreads">
                <span class="entry">${c.entrySpread.toFixed(3)}%</span>
                <span class="arrow">→</span>
                <span class="current">${c.currentSpread.toFixed(3)}%</span>
            </div>
            <span class="contract-pnl ${pnlClass}">${c.profit >= 0 ? '+' : ''}${c.profit.toFixed(3)}% ${autoLabel}</span>
        </div>`;
    }).join('');
}

function renderContracts() {
    const container = document.getElementById('contracts-list');
    if (!container) return;
    
    let html = '';
    
    const total = getTotalProfit();
    const totalClass = total >= 0 ? 'profit' : 'loss';
    
    if (activeContracts.length === 0) {
        html = '<div class="empty-contracts">Press C to open contract</div>';
    } else {
        const sortedContracts = [...activeContracts].sort((a, b) => {
            const profitA = a.entrySpread - a.currentSpread;
            const profitB = b.entrySpread - b.currentSpread;
            return profitB - profitA;
        });
        
        sortedContracts.forEach(c => {
            const profit = c.entrySpread - c.currentSpread;
            const pnlClass = profit >= 0 ? 'profit' : 'loss';
            const autoClass = c.autoClose ? 'active' : '';
            const threshold = c.closeThreshold || 0;
            
            const openTimeMs = c.openTime instanceof Date ? c.openTime.getTime() : new Date(c.openTime).getTime();
            const elapsed = formatDuration(Date.now() - openTimeMs);
            
            const safePair = escapeHtml(c.pair.split('/')[0]);
            const safeBuyEx = escapeHtml(c.buyEx.toUpperCase());
            const safeSellEx = escapeHtml(c.sellEx.toUpperCase());
            const safeKey = escapeHtml(c.key);
            
            html += `
            <div class="contract-item active">
                <div class="contract-info">
                    <span class="contract-pair">${safePair}</span>
                    <span class="contract-route">${safeBuyEx}↔${safeSellEx}</span>
                    <span class="contract-timer" data-opentime="${openTimeMs}">${elapsed}</span>
                </div>
                <div class="contract-spreads">
                    <span class="entry">${c.entrySpread.toFixed(3)}%</span>
                    <span class="arrow">→</span>
                    <span class="current">${c.currentSpread.toFixed(3)}%</span>
                </div>
                <span class="contract-pnl ${pnlClass}">${profit >= 0 ? '+' : ''}${profit.toFixed(3)}%</span>
                <div class="auto-controls">
                    <button class="auto-btn ${autoClass}" onclick="toggleAutoClose('${safeKey}')">A</button>
                    ${c.autoClose ? `<input type="range" class="threshold-slider" min="0" max="${c.entrySpread.toFixed(2)}" step="0.01" value="${threshold}" oninput="updateCloseThreshold('${safeKey}', this.value)"><span class="threshold-label" data-key="${safeKey}">${threshold.toFixed(2)}%</span>` : ''}
                </div>
                <button class="close-contract-btn" onclick="closeContract('${safeKey}')">✕</button>
            </div>`;
        });
    }
    
    container.innerHTML = html;
    
    const totalEl = document.getElementById('total-profit');
    if (totalEl) {
        totalEl.textContent = `${total >= 0 ? '+' : ''}${total.toFixed(3)}%`;
        totalEl.className = `total-value ${totalClass}`;
    }
    
    const historyCount = document.getElementById('history-count');
    if (historyCount) historyCount.textContent = closedContracts.length;
}

function updateTrendLevel(key, currentSpread) {
    const prevSpread = previousSpreads.get(key);
    let level = trendLevels.get(key) || 0;
    
    if (prevSpread !== undefined) {
        const diff = currentSpread - prevSpread;
        const threshold = 0.003;
        
        if (diff > threshold) {
            if (level < 0) {
                level += 1;
                if (level === 0) level = 1;
            } else {
                level = Math.min(level + 1, 3);
            }
        } else if (diff < -threshold) {
            if (level > 0) {
                level -= 1;
                if (level === 0) level = -1;
            } else {
                level = Math.max(level - 1, -3);
            }
        }
    }
    
    trendLevels.set(key, level);
    return level;
}

function getTrendIndicator(level) {
    const bars = ['', '', '', '', '', ''];
    
    if (level >= 1) bars[3] = 'green';
    if (level >= 2) bars[4] = 'green';
    if (level >= 3) bars[5] = 'green';
    
    if (level <= -1) bars[2] = 'red';
    if (level <= -2) bars[1] = 'red';
    if (level <= -3) bars[0] = 'red';
    
    return bars;
}

function getRowBg(color) {
    if (color === '#22c55e') return 'rgba(34, 197, 94, 0.1)';
    if (color === '#eab308') return 'rgba(234, 179, 8, 0.08)';
    return 'var(--bg-secondary)';
}

function formatPrice(price) {
    if (!price) return '--';
    if (price >= 1000) return price.toFixed(2);
    if (price >= 1) return price.toFixed(4);
    return price.toFixed(6);
}

async function togglePause() {
    isPaused = !isPaused;
    
    if (isPaused) {
        stopPolling();
    } else {
        startPolling();
    }
    
    updatePauseUI();
    
    await fetch('/api/toggle_pause', { method: 'POST' });
}

function updatePauseUI() {
    const icon = document.getElementById('pause-icon');
    if (isPaused) {
        icon.innerHTML = '<polygon points="5 3 19 12 5 21 5 3"/>';
    } else {
        icon.innerHTML = '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>';
    }
    const dot = document.getElementById('status-dot');
    dot.classList.toggle('active', !isPaused);
    dot.classList.toggle('paused', isPaused);
}


async function toggleExchange(exchangeId, enabled) {
    const res = await fetch('/api/toggle_exchange', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ exchange_id: exchangeId, enabled })
    });
    const data = await res.json();
    if (data.enabled_exchanges) {
        enabledExchanges = new Set(data.enabled_exchanges);
    }
}

async function togglePair(pair) {
    const res = await fetch('/api/toggle_pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pair })
    });
    const data = await res.json();
    if (data.selected_pairs) {
        enabledPairs = new Set(data.selected_pairs);
    }
}

function openChart(exchange, pair) {
    currentExchange = exchange;
    currentPair = pair;
    document.getElementById('modal-title').textContent = `${pair} - ${exchange.toUpperCase()}`;
    document.getElementById('chart-modal').classList.add('active');
    loadStochastic(exchange, pair);
}

function closeModal() {
    document.getElementById('chart-modal').classList.remove('active');
}

function openSettingsModal() {
    document.getElementById('settings-modal').classList.add('active');
    loadAccounts();
}

function closeSettingsModal() {
    document.getElementById('settings-modal').classList.remove('active');
    hideAccountForm();
}

function showAccountForm() {
    document.getElementById('add-account-form').classList.remove('hidden');
    document.getElementById('add-account-btn').classList.add('hidden');
}

function hideAccountForm() {
    document.getElementById('add-account-form').classList.add('hidden');
    document.getElementById('add-account-btn').classList.remove('hidden');
    document.getElementById('account-exchange').value = '';
    document.getElementById('account-name').value = '';
    document.getElementById('account-api-key').value = '';
    document.getElementById('account-api-secret').value = '';
    document.getElementById('account-passphrase').value = '';
}

async function loadAccounts() {
    try {
        const res = await fetch('/api/accounts');
        const accounts = await res.json();
        renderAccounts(accounts);
        await loadConnectedExchanges();
    } catch (err) {
        console.error('Load accounts error:', err);
    }
}

function renderAccounts(accounts) {
    const container = document.getElementById('accounts-list');
    if (accounts.length === 0) {
        container.innerHTML = '<div class="empty-state small">No accounts connected</div>';
        return;
    }
    
    container.innerHTML = accounts.map(a => `
        <div class="account-item ${a.is_active ? '' : 'inactive'}">
            <div class="account-info">
                <span class="account-exchange">${a.exchange_id.toUpperCase()}</span>
                <span class="account-name">${a.name}</span>
                <span class="account-key">${a.api_key_masked}</span>
            </div>
            <div class="account-actions">
                <button class="btn btn-mini" onclick="toggleAccountStatus(${a.id})">${a.is_active ? '✓' : '○'}</button>
                <button class="btn btn-mini btn-danger" onclick="deleteAccount(${a.id})">×</button>
            </div>
        </div>
    `).join('');
    
    updateExchangeChipStatus();
}

function quickConnect(exchangeId) {
    const form = document.getElementById('add-account-form');
    const select = document.getElementById('account-exchange');
    
    if (form && select) {
        select.value = exchangeId;
        form.classList.remove('hidden');
        document.getElementById('account-name').value = exchangeId.toUpperCase() + ' Main';
        document.getElementById('account-api-key').focus();
    }
}

async function saveAccount() {
    const exchange = document.getElementById('account-exchange').value;
    const name = document.getElementById('account-name').value;
    const apiKey = document.getElementById('account-api-key').value;
    const apiSecret = document.getElementById('account-api-secret').value;
    const passphrase = document.getElementById('account-passphrase').value;
    
    if (!exchange || !name || !apiKey || !apiSecret) {
        alert('Fill all required fields');
        return;
    }
    
    try {
        await fetch('/api/accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                exchange_id: exchange,
                name: name,
                api_key: apiKey,
                api_secret: apiSecret,
                passphrase: passphrase || null
            })
        });
        hideAccountForm();
        loadAccounts();
    } catch (err) {
        console.error('Save account error:', err);
    }
}

async function deleteAccount(id) {
    if (!confirm('Delete this account?')) return;
    try {
        await fetch(`/api/accounts/${id}`, { method: 'DELETE' });
        loadAccounts();
    } catch (err) {
        console.error('Delete account error:', err);
    }
}

async function toggleAccountStatus(id) {
    try {
        await fetch(`/api/accounts/${id}/toggle`, { method: 'POST' });
        loadAccounts();
    } catch (err) {
        console.error('Toggle account error:', err);
    }
}

async function loadStochastic(exchange, pair) {
    try {
        const res = await fetch(`/api/stochastic/${exchange}/${pair}?interval=${currentTimeframe}`);
        const data = await res.json();
        if (!data.error) renderCharts(data);
    } catch (err) {
        console.error('Load chart error:', err);
    }
}

function renderCharts(data) {
    const stoch = data.stochastic;
    const timestamps = stoch.timestamps.map(t => new Date(t));
    
    const priceTrace = {
        x: timestamps,
        close: stoch.ohlc.map(k => k.close),
        high: stoch.ohlc.map(k => k.high),
        low: stoch.ohlc.map(k => k.low),
        open: stoch.ohlc.map(k => k.open),
        type: 'candlestick',
        increasing: { line: { color: '#22c55e' } },
        decreasing: { line: { color: '#ef4444' } }
    };
    
    const layout = {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#e4e4e7', size: 10 },
        xaxis: { gridcolor: 'rgba(255,255,255,0.05)', showgrid: true },
        yaxis: { gridcolor: 'rgba(255,255,255,0.05)', showgrid: true, side: 'right' },
        margin: { l: 5, r: 50, t: 5, b: 25 },
        showlegend: false
    };
    
    Plotly.newPlot('price-chart', [priceTrace], layout, { responsive: true, displayModeBar: false });
    
    const kTrace = {
        x: timestamps, y: stoch.k,
        type: 'scatter', mode: 'lines', name: '%K',
        line: { color: '#3b82f6', width: 1.5 }
    };
    
    const dTrace = {
        x: timestamps, y: stoch.d,
        type: 'scatter', mode: 'lines', name: '%D',
        line: { color: '#f97316', width: 1.5 }
    };
    
    const stochLayout = {
        ...layout,
        yaxis: { ...layout.yaxis, range: [0, 100] },
        shapes: [
            { type: 'line', x0: timestamps[0], x1: timestamps[timestamps.length-1], y0: 80, y1: 80, line: { color: 'rgba(239,68,68,0.3)', dash: 'dot' } },
            { type: 'line', x0: timestamps[0], x1: timestamps[timestamps.length-1], y0: 20, y1: 20, line: { color: 'rgba(34,197,94,0.3)', dash: 'dot' } }
        ],
        legend: { x: 0, y: 1.1, orientation: 'h', font: { size: 10 } }
    };
    
    Plotly.newPlot('stochastic-chart', [kTrace, dTrace], stochLayout, { responsive: true, displayModeBar: false });
}

function switchMode(mode) {
    currentMode = mode;
    document.querySelectorAll('.mode-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.mode === mode);
    });
    
    const warning = document.getElementById('mode-warning');
    const warningText = warning.querySelector('.warning-text');
    const aiPanel = document.getElementById('ai-panel');
    
    warning.className = 'mode-warning';
    
    if (mode === 'demo') {
        warning.classList.add('demo');
        warningText.textContent = 'Demo mode - virtual trading, no real money';
        aiPanel.classList.add('hidden');
    } else if (mode === 'real') {
        warning.classList.add('real');
        warningText.textContent = 'Real mode - requires connected exchange accounts with API keys';
        aiPanel.classList.add('hidden');
    } else if (mode === 'ml') {
        warning.classList.add('ml');
        warningText.textContent = 'ML mode - AI-assisted trading. USE AT YOUR OWN RISK!';
        aiPanel.classList.remove('hidden');
    }
    
    warning.classList.remove('hidden');
    
    localStorage.setItem('tradingMode', mode);
}

function addAiMessage(text, type = 'ai') {
    const container = document.getElementById('ai-messages');
    const msg = document.createElement('div');
    msg.className = 'ai-message ' + type;
    msg.textContent = text;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

async function sendAiMessage() {
    const input = document.getElementById('ai-input');
    const message = input.value.trim();
    if (!message || aiLoading) return;
    
    input.value = '';
    addAiMessage(message, 'user');
    
    aiLoading = true;
    try {
        const res = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ 
                message,
                context: {
                    spreads: Array.from(previousSpreads.entries()).slice(0, 10),
                    activeContracts: activeContracts.length,
                    mode: currentMode
                }
            })
        });
        
        if (res.ok) {
            const data = await res.json();
            addAiMessage(data.response, 'ai');
        } else {
            addAiMessage('Ошибка AI', 'warning');
        }
    } catch (e) {
        addAiMessage('Ошибка соединения', 'warning');
    }
    aiLoading = false;
}

async function getAiStrategy() {
    if (aiLoading) return;
    
    const btn = document.querySelector('.ai-strategy-btn');
    btn.disabled = true;
    btn.textContent = '...';
    aiLoading = true;
    
    addAiMessage('Анализирую рынок...', 'system');
    
    try {
        const res = await fetch('/api/ai/strategy', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                spreads: Array.from(previousSpreads.entries()),
                activeContracts: activeContracts.map(c => ({
                    pair: c.pair,
                    entrySpread: c.entrySpread,
                    currentSpread: c.currentSpread,
                    profit: c.entrySpread - c.currentSpread
                })),
                settings: {
                    autoEntryThreshold,
                    autoCloseThreshold,
                    maxContracts: parseInt(document.getElementById('max-contracts-input')?.value || 5),
                    bankPercent: parseInt(document.getElementById('bank-percent-input')?.value || 10)
                }
            })
        });
        
        if (res.ok) {
            const data = await res.json();
            addAiMessage(data.strategy, 'ai');
            
            if (data.suggestions) {
                if (data.suggestions.openThreshold !== undefined) {
                    document.getElementById('auto-entry-slider').value = data.suggestions.openThreshold;
                    updateAutoEntryThreshold(data.suggestions.openThreshold);
                }
                if (data.suggestions.closeThreshold !== undefined) {
                    document.getElementById('auto-close-slider').value = data.suggestions.closeThreshold;
                    updateAutoCloseThreshold(data.suggestions.closeThreshold);
                }
                if (data.suggestions.maxContracts !== undefined) {
                    document.getElementById('max-contracts-input').value = data.suggestions.maxContracts;
                    updateMaxContracts(data.suggestions.maxContracts);
                }
                addAiMessage('Настройки применены автоматически', 'system');
            }
        } else {
            addAiMessage('Не удалось получить стратегию', 'warning');
        }
    } catch (e) {
        addAiMessage('Ошибка соединения', 'warning');
    }
    
    btn.disabled = false;
    btn.textContent = 'Стратегия';
    aiLoading = false;
}

function initMode() {
    const savedMode = localStorage.getItem('tradingMode') || 'demo';
    switchMode(savedMode);
}
