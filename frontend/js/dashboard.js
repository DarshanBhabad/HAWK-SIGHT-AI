/* ============================================
   DASHBOARD - MARKET DATA, CHART, AI PREDICTIONS
   ============================================ */

// --- MARKET HOURS STATUS ---
function checkMarketStatus() {
    const now = new Date();
    const nyTimeString = now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" });
    const istTime = new Date(nyTimeString);

    const day = istTime.getDay();
    const hours = istTime.getHours();
    const minutes = istTime.getMinutes();

    const isWeekend = day === 0 || day === 6;
    const isBeforeOpen = hours < 9 || (hours === 9 && minutes < 15);
    const isAfterClose = hours > 15 || (hours === 15 && minutes >= 30);
    const isOpen = !isWeekend && !isBeforeOpen && !isAfterClose;

    const badge = document.getElementById('market-status-badge');
    const text = document.getElementById('market-status-text');
    const icon = document.getElementById('market-status-icon');

    if (isOpen) {
        badge.className = "hidden sm:flex items-center gap-2 px-3 py-1 rounded-full bg-green-500/10 border border-green-500/20 text-green-400 text-xs font-bold transition-colors";
        text.innerText = "MARKET OPEN";
        icon.className = "fas fa-circle text-[8px] animate-pulse";
    } else {
        badge.className = "hidden sm:flex items-center gap-2 px-3 py-1 rounded-full bg-red-500/10 border border-red-500/20 text-red-400 text-xs font-bold transition-colors";
        text.innerText = "MARKET CLOSED";
        icon.className = "fas fa-lock text-[10px]";
    }
}

// --- FETCH LIVE STOCK PRICE ---
async function fetchStockPrice(symbol) {
    try {
        const response = await fetch(`${CONFIG.API_URL}/quote?symbol=${symbol}`);
        const data = await response.json();
        if (!data.c) throw new Error("No Data");
        return { price: data.c, change: data.dp };
    } catch (error) {
        console.error("API Error", error);
        return { price: 0, change: 0 };
    }
}

// --- WEB SOCKET FOR LIVE PRICES ---
const socket = io(CONFIG.API_URL || 'http://127.0.0.1:5000');

socket.on('price_update', (prices) => {
    // prices is a dictionary { "AAPL": 150.5, ... }
    let needsRender = false;
    for (const [symbol, price] of Object.entries(prices)) {
        if (!STATE.stockData[symbol]) {
            STATE.stockData[symbol] = { price: price, change: 0 };
            needsRender = true;
        } else {
            const oldPrice = STATE.stockData[symbol].price;
            if (oldPrice !== price) {
                // Calculate pseudo-change if real change is missing
                const diff = price - oldPrice;
                STATE.stockData[symbol].price = price;
                STATE.stockData[symbol].change = (diff / oldPrice) * 100;
                needsRender = true;
            }
        }
    }
    if (needsRender) {
        renderMarketTable();
    }
});

// --- FETCH LIVE STOCK PRICE (Initial Load Only) ---
// --- UPDATE MARKET TABLE (Fetches initial data) ---
async function updateMarketTable() {
    for (const symbol of CONFIG.TICKERS) {
        const data = await fetchStockPrice(symbol);
        STATE.stockData[symbol] = data;
    }
    renderMarketTable();
    updateTradeEstimate();   // keep the manual trade panel's price + cost fresh
}

// --- RENDER MARKET TABLE (Does not fetch) ---
function renderMarketTable() {
    const tbody = document.getElementById('stock-ticker-body');
    tbody.innerHTML = ''; // Clear and re-render

    for (const symbol of CONFIG.TICKERS) {
        const data = STATE.stockData[symbol] || { price: 0, change: 0 };
        
        const isUp = data.change >= 0;
        const colorClass = isUp ? 'text-green-400' : 'text-red-400';
        const trendIcon = isUp
            ? '<i class="fas fa-arrow-trend-up text-green-500"></i>'
            : '<i class="fas fa-arrow-trend-down text-red-500"></i>';

        let row = document.createElement('tr');
        row.id = `row-${symbol}`;
        row.className = `border-b border-gray-800 hover:bg-gray-800/50 transition cursor-pointer`;
        
        if (symbol === STATE.currentSelection) row.classList.add('bg-gray-800');
        
        const isFav = STATE.favorites.has(symbol);
        const starClass = isFav ? 'fas fa-star fav-star active' : 'far fa-star fav-star';

        row.innerHTML = `
            <td class="px-6 py-4 font-bold text-white">
                <div class="flex items-center gap-3">
                    <i class="${starClass}" data-symbol="${symbol}" onclick="event.stopPropagation(); toggleFavorite('${symbol}')"></i>
                    <span class="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center text-xs text-gray-300">${symbol[0]}</span>
                    ${symbol}
                </div>
            </td>
            <td class="px-6 py-4 font-mono text-gray-300">$${data.price.toFixed(2)}</td>
            <td class="px-6 py-4 ${colorClass} font-medium">${isUp ? '+' : ''}${data.change.toFixed(2)}%</td>
            <td class="px-6 py-4 text-right text-xs font-bold">${trendIcon}</td>
        `;

        // Click on the row (excluding star) triggers prediction
        row.onclick = () => runAIPrediction(symbol);
        tbody.appendChild(row);
    }
}

// --- DRAW PRICE CHART ---
async function updateChart(symbol, predictedPrice = null) {
    try {
        const response = await fetch(`${CONFIG.API_URL}/history?symbol=${symbol}`);
        const data = await response.json();

        let labels = [...data.dates];
        let prices = [...data.prices];

        if (predictedPrice) {
            labels.push('~3 Months (AI)');
            prices.push(predictedPrice);
        }

        const ctx = document.getElementById('stockChart').getContext('2d');
        if (STATE.priceChart) STATE.priceChart.destroy();

        const pointColors = prices.map((_, i) =>
            i === prices.length - 1 && predictedPrice ? '#eab308' : '#38BDF8'
        );
        const pointRadii = prices.map((_, i) =>
            i === prices.length - 1 && predictedPrice ? 6 : 0
        );

        STATE.priceChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: symbol,
                    data: prices,
                    borderColor: '#38BDF8',
                    backgroundColor: 'rgba(56, 189, 248, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    pointBackgroundColor: pointColors,
                    pointRadius: pointRadii,
                    pointHoverRadius: 8,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(22, 27, 34, 0.9)',
                        titleColor: '#818CF8',
                        bodyColor: '#ffffff',
                        borderColor: '#30363d',
                        borderWidth: 1,
                        padding: 12,
                        displayColors: false,
                        callbacks: {
                            label: function(context) {
                                let value = context.parsed.y;
                                let isPrediction = context.chart.data.labels[context.dataIndex] === '~3 Months (AI)';
                                return (isPrediction ? '🤖 3-Mo Target: ' : 'Price: ') + '$' + value.toFixed(2);
                            }
                        }
                    }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: '#6b7280', maxTicksLimit: 7 } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#6b7280' } }
                }
            }
        });
    } catch (error) {
        console.error("Chart Error", error);
    }
}

// --- 3-MONTH OUTLOOK (HONEST UI: PROBABILITY + RISK + BASELINE + PROOF) ---
async function runAIPrediction(symbol) {
    STATE.currentSelection = symbol;
    updateMarketTable();
    updateChart(symbol);
    loadNews(symbol);   // short-term news lens, loads in parallel (separate from the 3-month model)
    updateTradeEstimate();   // refresh the manual trade panel for the selected stock

    document.getElementById('pred-symbol').innerText = symbol;
    document.getElementById('pred-direction').innerHTML = '<div class="spinner"></div>';
    document.getElementById('pred-change').innerText = 'analyzing...';
    document.getElementById('pred-change').className = 'text-2xl font-mono text-yellow-500 animate-pulse';
    document.getElementById('pred-confidence-text').innerText = '--';
    document.getElementById('pred-confidence-fill').style.width = '0%';
    document.getElementById('pred-baseline').innerText = '';
    document.getElementById('pred-volatility').innerHTML = '<span class="metric-tag medium">CALCULATING</span>';
    document.getElementById('pred-metrics').innerHTML = '';

    try {
        const response = await apiFetch('/predict', {
            method: 'POST',
            body: JSON.stringify({ symbol: symbol })
        });
        const result = await response.json();
        if (result.error) throw new Error(result.error);

        // Show the ~3-month price target on the chart (a rough estimate)
        updateChart(symbol, result.predicted_price);

        const isBullish = result.is_bullish;
        const directionClass = isBullish ? 'up' : 'down';
        const directionIcon = isBullish ? 'fa-arrow-up' : 'fa-arrow-down';
        const directionText = isBullish ? 'LIKELY UP' : 'LIKELY DOWN';
        const colorClass = isBullish ? 'text-green-400' : 'text-red-400';

        // --- DIRECTION BADGE (3-month) ---
        document.getElementById('pred-direction').innerHTML = `
            <div class="direction-badge ${directionClass}">
                <i class="fas ${directionIcon}"></i> ${directionText}
            </div>
        `;

        // --- EXPECTED 3-MONTH MOVE ---
        const sign = result.expected_return_pct >= 0 ? '+' : '';
        document.getElementById('pred-change').innerText = `${sign}${result.expected_return_pct.toFixed(1)}%`;
        document.getElementById('pred-change').className = `text-4xl font-mono ${colorClass}`;

        // --- PROBABILITY BAR ("chance higher in 3 months") ---
        const probPct = (result.probability_up * 100).toFixed(0);
        document.getElementById('pred-confidence-text').innerText = `${probPct}%`;
        document.getElementById('pred-confidence-fill').style.width = `${probPct}%`;

        // --- HONEST BASELINE (so the user can judge if there's real edge) ---
        const basePct = (result.baseline_up_rate * 100).toFixed(0);
        document.getElementById('pred-baseline').innerText =
            `Baseline: this stock was simply up ${basePct}% of the time historically.`;

        // --- RISK TAG ---
        const volLevel = result.volatility_level || 'medium';
        document.getElementById('pred-volatility').innerHTML =
            `<span class="metric-tag ${volLevel.toLowerCase()}">RISK: ${volLevel.toUpperCase()}</span>`;

        // --- HONEST PROOF (measured on data the model never saw) ---
        const acc = (result.model_accuracy * 100).toFixed(0);
        const baseAcc = (result.baseline_accuracy * 100).toFixed(0);
        const skill = result.skill_above_baseline * 100;
        const skillColor = skill > 1 ? 'text-green-400' : (skill < -1 ? 'text-red-400' : 'text-yellow-400');
        const skillSign = skill >= 0 ? '+' : '';

        // AUC = ranking quality of the probabilities. This is where the model
        // genuinely has an edge (0.5 = none, >0.55 = real, robust signal).
        const auc = (result.walk_forward_auc != null ? result.walk_forward_auc : 0.5);
        const aucColor = auc >= 0.55 ? 'text-green-400' : (auc < 0.5 ? 'text-red-400' : 'text-yellow-400');

        // Robust verdict: built on the walk-forward signal, NOT a single split.
        const robust = result.robust_signal;
        const verdictColor = robust ? 'text-green-400' : 'text-yellow-400';
        const verdictText = robust
            ? `✅ Real ranking signal across many time windows (AUC ${auc.toFixed(2)}). The confidence % carries genuine edge.`
            : `⚠️ No robust edge on direction — over 3 months this name is up ~${basePct}% of the time regardless, so treat the call as low confidence and lean on the risk tag.`;

        document.getElementById('pred-metrics').innerHTML = `
            <div class="grid grid-cols-4 gap-2 mt-4 text-xs">
                <div class="bg-dark-800 p-2 rounded">
                    <div class="text-gray-500">Accuracy</div>
                    <div class="text-white font-mono">${acc}%</div>
                </div>
                <div class="bg-dark-800 p-2 rounded">
                    <div class="text-gray-500">Baseline</div>
                    <div class="text-white font-mono">${baseAcc}%</div>
                </div>
                <div class="bg-dark-800 p-2 rounded">
                    <div class="text-gray-500" title="Accuracy minus the always-up baseline. Near 0 is expected for these stocks.">Skill</div>
                    <div class="${skillColor} font-mono">${skillSign}${skill.toFixed(1)}%</div>
                </div>
                <div class="bg-dark-800 p-2 rounded">
                    <div class="text-gray-500" title="Ranking quality of the probabilities (walk-forward). >0.55 = real edge.">Signal (AUC)</div>
                    <div class="${aucColor} font-mono">${auc.toFixed(2)}</div>
                </div>
            </div>
            <div class="${verdictColor} text-[11px] mt-3">${verdictText}</div>
            <div class="text-gray-500 text-[11px] mt-1"><i class="fas fa-info-circle"></i> Educational tool, not financial advice. Never invest money you can't afford to lose.</div>
        `;

    } catch (error) {
        console.error(error);
        document.getElementById('pred-direction').innerHTML =
            '<div class="direction-badge neutral"><i class="fas fa-exclamation-triangle"></i> ERROR</div>';
        document.getElementById('pred-change').innerText = '---';
        document.getElementById('pred-change').className = 'text-4xl font-mono text-red-500';
        document.getElementById('pred-metrics').innerHTML =
            `<div class="text-red-400 text-xs mt-3">${error.message || 'Prediction failed.'}</div>`;
    }
}

// ============================================================
//  NEWS + MARKET MOOD  (short-term lens, SEPARATE from the 3-month model)
// ============================================================

// Full Tailwind class strings (Play CDN picks these up from the DOM at runtime).
const SENTIMENT_STYLE = {
    positive: { chip: 'bg-green-500/15 text-green-400 border border-green-500/30', icon: 'fa-arrow-trend-up', dot: '🟢' },
    negative: { chip: 'bg-red-500/15 text-red-400 border border-red-500/30',     icon: 'fa-arrow-trend-down', dot: '🔴' },
    neutral:  { chip: 'bg-gray-500/15 text-gray-400 border border-gray-500/30',  icon: 'fa-minus', dot: '⚪' },
};
const MOOD_BADGE = {
    positive: 'px-3 py-1 rounded text-xs font-bold bg-green-500/10 border border-green-500/20 text-green-400',
    negative: 'px-3 py-1 rounded text-xs font-bold bg-red-500/10 border border-red-500/20 text-red-400',
    neutral:  'px-3 py-1 rounded text-xs font-bold bg-gray-500/10 border border-gray-500/20 text-gray-400',
};

function timeAgo(unixSeconds) {
    if (!unixSeconds) return '';
    const diff = Math.floor(Date.now() / 1000) - unixSeconds;
    if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderArticle(a) {
    const st = SENTIMENT_STYLE[a.sentiment] || SENTIMENT_STYLE.neutral;
    const assist = a.sentiment_source === 'lexicon-assist' && a.keywords && a.keywords.length
        ? ` <span class="text-gray-600" title="Flagged by finance keywords: ${escapeHtml(a.keywords.join(', '))}">&middot; kw</span>` : '';
    const headline = escapeHtml(a.headline);
    const source = escapeHtml(a.source);
    const link = a.url ? `href="${escapeHtml(a.url)}" target="_blank" rel="noopener"` : '';
    return `
        <a ${link} class="block bg-dark-800 hover:bg-dark-700 transition rounded-lg p-3 border border-gray-800">
            <div class="flex items-start gap-3">
                <span class="${st.chip} text-[10px] font-bold px-2 py-0.5 rounded whitespace-nowrap mt-0.5">
                    <i class="fas ${st.icon}"></i> ${a.sentiment.toUpperCase()}
                </span>
                <div class="min-w-0">
                    <p class="text-sm text-gray-200 leading-snug">${headline}</p>
                    <p class="text-[11px] text-gray-500 mt-1">${source} &middot; ${timeAgo(a.datetime)}${assist}</p>
                </div>
            </div>
        </a>`;
}

async function loadNews(symbol) {
    const statusEl = document.getElementById('news-status');
    const listEl = document.getElementById('news-list');
    const badgeEl = document.getElementById('news-mood-badge');
    const valueEl = document.getElementById('news-mood-value');
    const markerEl = document.getElementById('news-mood-marker');
    const countsEl = document.getElementById('news-mood-counts');
    if (!statusEl) return;

    statusEl.innerText = 'Loading news…';
    listEl.innerHTML = '';
    valueEl.innerText = '--';
    countsEl.innerText = '';
    badgeEl.className = MOOD_BADGE.neutral;
    badgeEl.innerText = 'MOOD --';
    markerEl.style.left = '50%';

    try {
        const response = await apiFetch(`/news?symbol=${encodeURIComponent(symbol)}`);
        const data = await response.json();
        if (data.error) throw new Error(data.error);

        const s = data.sentiment || { counts: {}, mood: 50, label: 'neutral', total: 0 };
        valueEl.innerText = `${s.mood}/100`;
        markerEl.style.left = `${s.mood}%`;
        badgeEl.className = MOOD_BADGE[s.label] || MOOD_BADGE.neutral;
        badgeEl.innerText = `MOOD ${s.mood} · ${s.label.toUpperCase()}`;
        const c = s.counts || {};
        countsEl.innerHTML =
            `Based on ${s.total} headlines &middot; 🟢 ${c.positive || 0} positive &middot; 🔴 ${c.negative || 0} negative &middot; ⚪ ${c.neutral || 0} neutral`;

        if (!data.articles || data.articles.length === 0) {
            statusEl.innerText = 'No recent news found for this stock.';
            return;
        }
        statusEl.innerText = '';
        listEl.innerHTML = data.articles.map(renderArticle).join('');
    } catch (err) {
        statusEl.innerText = `Couldn't load news: ${err.message}`;
    }
}

// --- TRADE EXECUTION (BUY / SELL) ---
async function executeTrade(action) {
    if (!STATE.currentUser) return alert('Please log in first');

    const shares = parseInt(document.getElementById('trade-shares').value);
    if (!shares || shares <= 0) return alert('Enter valid number of shares');

    const price = STATE.stockData[STATE.currentSelection]?.price;
    if (!price) return alert('Live price unavailable. Try again.');

    try {
        const response = await apiFetch(`/${action}`, {
            method: 'POST',
            body: JSON.stringify({
                symbol: STATE.currentSelection,
                shares: shares,
                // Note: server should fetch its own price for security,
                // but we send this for backwards compat — backend ignores it
                price: price
            })
        });
        const data = await response.json();

        if (data.success) {
            STATE.currentUser.balance = data.new_balance;
            localStorage.setItem(CONFIG.STORAGE.USER, JSON.stringify(STATE.currentUser));
            document.getElementById('display-balance').innerText = `$${data.new_balance.toFixed(2)}`;

            const balEl = document.getElementById('display-balance');
            balEl.classList.add(action === 'buy' ? 'price-down' : 'price-up');
            setTimeout(() => balEl.classList.remove('price-down', 'price-up'), 1000);

            const verb = action === 'buy' ? 'Bought' : 'Sold';
            showTradeStatus(`✓ ${verb} ${shares} ${STATE.currentSelection}`, true);
            // (The portfolio modal reloads holdings each time it is opened.)
        } else {
            showTradeStatus(data.error || 'Trade failed', false);
        }
    } catch (err) {
        console.error('Trade error', err);
        showTradeStatus('Trade failed. Check connection.', false);
    }
}

// --- Manual trade panel helpers ---
function updateTradeEstimate() {
    const symEl = document.getElementById('trade-symbol');
    if (!symEl) return;
    const sym = STATE.currentSelection;
    const price = sym ? STATE.stockData[sym]?.price : null;

    symEl.innerText = sym || '—';
    document.getElementById('trade-price').innerText = price ? `@ $${price.toFixed(2)}` : '';

    const shares = parseInt(document.getElementById('trade-shares')?.value) || 0;
    const cost = (price && shares > 0) ? price * shares : 0;
    document.getElementById('trade-est-cost').innerText = `$${cost.toFixed(2)}`;
}

function adjustShares(delta) {
    const input = document.getElementById('trade-shares');
    if (!input) return;
    let v = (parseInt(input.value) || 0) + delta;
    if (v < 1) v = 1;
    input.value = v;
    updateTradeEstimate();
}

function showTradeStatus(msg, ok = true) {
    const el = document.getElementById('trade-status');
    if (!el) return;
    el.innerText = msg;
    el.className = `text-xs text-center mt-3 h-4 ${ok ? 'text-green-400' : 'text-red-400'}`;
    setTimeout(() => { if (el.innerText === msg) el.innerText = ''; }, 4000);
}

// --- ADD FUNDS MODAL ---
function openAddFunds() {
    if (!STATE.currentUser) return alert('Please log in first');
    document.getElementById('deposit-amount').value = '';
    document.getElementById('add-funds-modal').classList.remove('hidden');
}

function closeAddFunds() {
    document.getElementById('add-funds-modal').classList.add('hidden');
}

async function confirmAddFunds() {
    const amount = parseFloat(document.getElementById('deposit-amount').value);
    if (isNaN(amount) || amount <= 0) return alert('Please enter a valid positive number');

    try {
        const response = await apiFetch('/add_funds', {
            method: 'POST',
            body: JSON.stringify({ amount })
        });
        const data = await response.json();

        if (data.success) {
            STATE.currentUser.balance = data.new_balance;
            localStorage.setItem(CONFIG.STORAGE.USER, JSON.stringify(STATE.currentUser));
            document.getElementById('display-balance').innerText = `$${data.new_balance.toFixed(2)}`;

            const balEl = document.getElementById('display-balance');
            balEl.classList.add('price-up');
            setTimeout(() => balEl.classList.remove('price-up'), 1000);

            closeAddFunds();
        } else {
            alert(data.error);
        }
    } catch (err) {
        console.error('Add funds error', err);
    }
}
