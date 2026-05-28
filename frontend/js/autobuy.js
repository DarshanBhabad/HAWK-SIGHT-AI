/* ============================================
   AUTO-BUY RECOMMENDATION ENGINE UI
   Shows portfolio-theory-based buy suggestions
   ============================================ */

// --- OPEN AUTO-BUY MODAL ---
async function openAutoBuy() {
    if (!STATE.currentUser) return alert('Please log in first');
    if (STATE.favorites.size === 0) {
        return alert('Mark some stocks as favorites first (click the ⭐ icon)');
    }

    document.getElementById('autobuy-modal').classList.remove('hidden');
    document.getElementById('autobuy-loading').classList.remove('hidden');
    document.getElementById('autobuy-results').classList.add('hidden');

    try {
        const res = await apiFetch('/recommend', { method: 'POST' });
        const data = await res.json();

        document.getElementById('autobuy-loading').classList.add('hidden');
        document.getElementById('autobuy-results').classList.remove('hidden');

        renderRecommendations(data);
    } catch (err) {
        console.error('Recommendation failed', err);
        document.getElementById('autobuy-loading').innerHTML =
            '<div class="text-red-400">Failed to fetch recommendations. Try again.</div>';
    }
}

function closeAutoBuy() {
    document.getElementById('autobuy-modal').classList.add('hidden');
}

// --- RENDER THE OPTIMIZED COMBINATION (Markowitz / max-Sharpe) ---
function renderRecommendations(data) {
    const container = document.getElementById('autobuy-recommendations');
    const summary = document.getElementById('autobuy-summary');
    container.innerHTML = '';

    // Prefer the rich MPT output; fall back to legacy recs if absent.
    const picks = data.picks || (data.recommendations || []).filter(r => r.action === 'BUY');
    const excluded = data.excluded
        || (data.recommendations || []).filter(r => r.action !== 'BUY')
              .map(r => ({ symbol: r.symbol, reason: r.reason || 'Not selected' }));

    if (!picks || picks.length === 0) {
        summary.innerHTML = '';
        container.innerHTML = `
            <div class="text-center py-8 text-gray-400">
                No favorable <b>combination</b> found in your favorites right now.
                <br><span class="text-xs text-gray-500 mt-2 block">${data.note || 'Holding cash may be the better call today.'}</span>
            </div>` + renderExcluded(excluded);
        return;
    }

    // --- Portfolio summary ---
    const erPct = (data.expected_return_pct != null) ? data.expected_return_pct : 0;
    const erVal = (data.expected_profit_value != null) ? data.expected_profit_value : (data.estimated_return || 0);
    const erColor = erPct >= 0 ? 'text-green-400' : 'text-red-400';
    const erSign = erPct >= 0 ? '+' : '';
    summary.innerHTML = `
        <div class="bg-sky-500/5 border border-sky-500/20 rounded-xl p-4 mb-4">
            <div class="text-xs text-sky-300 font-bold uppercase tracking-wide mb-3">
                <i class="fas fa-diagram-project"></i> Optimal Combination &middot; Markowitz (max-Sharpe)
            </div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div><div class="text-[11px] text-gray-500 uppercase font-bold">To Invest</div>
                     <div class="text-lg font-mono text-white">$${(data.total_investment || 0).toFixed(2)}</div></div>
                <div><div class="text-[11px] text-gray-500 uppercase font-bold">Est. 3-Mo Return</div>
                     <div class="text-lg font-mono ${erColor}">${erSign}${erPct.toFixed(1)}% <span class="text-xs text-gray-400">(${erSign}$${Math.abs(erVal).toFixed(0)})</span></div></div>
                <div><div class="text-[11px] text-gray-500 uppercase font-bold">Risk (vol)</div>
                     <div class="text-lg font-mono text-yellow-300">${(data.expected_risk_pct || 0).toFixed(1)}%</div></div>
                <div><div class="text-[11px] text-gray-500 uppercase font-bold">Sharpe</div>
                     <div class="text-lg font-mono text-sky-300">${(data.sharpe || 0).toFixed(2)}</div></div>
            </div>
            <div class="text-[11px] text-gray-500 mt-3">${data.note || ''}</div>
        </div>
    `;

    // --- One card per stock in the combination ---
    picks.forEach(p => {
        const cost = (p.cost != null) ? p.cost : (p.total_cost || 0);
        const weight = (p.weight_pct != null) ? p.weight_pct : 0;
        const er = (p.expected_return_pct != null) ? p.expected_return_pct : (p.predicted_return || 0);
        const erC = er >= 0 ? 'text-green-400' : 'text-red-400';
        const erS = er >= 0 ? '+' : '';
        const risk = (p.risk_level || 'MEDIUM').toLowerCase();
        const trusted = p.trustworthy
            ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded bg-green-500/15 text-green-400 border border-green-500/30 ml-2" title="Our model has real, walk-forward-tested signal on this stock"><i class="fas fa-shield-halved"></i> TRUSTED</span>`
            : '';
        container.innerHTML += `
            <div class="rec-card mb-3">
                <div class="flex justify-between items-start">
                    <div class="flex items-center gap-3">
                        <span class="w-10 h-10 rounded-full bg-gray-700 flex items-center justify-center font-bold text-white">${p.symbol[0]}</span>
                        <div>
                            <div class="font-bold text-white text-lg">${p.symbol}${trusted}</div>
                            <div class="text-xs text-green-400 font-bold uppercase tracking-wide">✅ BUY &middot; ${weight.toFixed(1)}% of basket</div>
                        </div>
                    </div>
                    <div class="text-right">
                        <div class="text-2xl font-mono text-white">${p.shares}</div>
                        <div class="text-xs text-gray-400">shares ($${cost.toFixed(2)})</div>
                    </div>
                </div>
                <div class="grid grid-cols-3 gap-2 mt-3 text-xs">
                    <div><div class="text-gray-500">Est. 3-mo</div>
                         <div class="font-mono ${erC}">${erS}${er.toFixed(1)}%</div></div>
                    <div><div class="text-gray-500">Confidence</div>
                         <div class="font-mono text-white">${((p.confidence || 0) * 100).toFixed(0)}%</div></div>
                    <div><div class="text-gray-500">Risk</div>
                         <div><span class="metric-tag ${risk}">${(p.risk_level || 'MEDIUM')}</span></div></div>
                </div>
                <div class="mt-2 w-full h-1.5 rounded-full bg-dark-700">
                    <div class="h-1.5 rounded-full bg-sky-500" style="width:${Math.min(weight, 100)}%"></div>
                </div>
            </div>
        `;
    });

    container.innerHTML += renderExcluded(excluded);
}

// --- The favorites that were left out, with the honest reason ---
function renderExcluded(excluded) {
    if (!excluded || excluded.length === 0) return '';
    const items = excluded.map(e => `
        <li class="flex justify-between gap-3 py-1">
            <span class="text-gray-300 font-semibold">${e.symbol}</span>
            <span class="text-gray-500 text-right">${e.reason}</span>
        </li>`).join('');
    return `
        <div class="mt-4 bg-dark-800/50 border border-gray-800 rounded-xl p-4">
            <div class="text-xs text-gray-400 font-bold uppercase mb-2"><i class="fas fa-filter"></i> Left out (and why)</div>
            <ul class="text-xs divide-y divide-gray-800">${items}</ul>
        </div>`;
}

// --- EXECUTE ALL RECOMMENDED BUYS ---
async function executeAllBuys() {
    if (!confirm('Approve and buy this combination? This will use your virtual balance.')) return;

    try {
        const res = await apiFetch('/execute_recommendations', { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            alert(`Successfully executed ${data.trades_executed} trades. New balance: $${data.new_balance.toFixed(2)}`);
            STATE.currentUser.balance = data.new_balance;
            localStorage.setItem(CONFIG.STORAGE.USER, JSON.stringify(STATE.currentUser));
            document.getElementById('display-balance').innerText = `$${data.new_balance.toFixed(2)}`;
            closeAutoBuy();
        } else {
            alert(data.error || 'Some trades failed. Check console.');
        }
    } catch (err) {
        console.error('Execute failed', err);
        alert('Failed to execute trades');
    }
}

// --- AUTO-BUY TOGGLE (enable daily automatic execution) ---
async function toggleAutoBuyMode() {
    const toggle = document.getElementById('autobuy-toggle');
    const isOn = toggle.classList.contains('on');
    const newState = !isOn;

    try {
        const res = await apiFetch('/autobuy_settings', {
            method: 'POST',
            body: JSON.stringify({ enabled: newState })
        });
        const data = await res.json();
        if (data.success) {
            toggle.classList.toggle('on', newState);
            document.getElementById('autobuy-mode-label').innerText =
                newState ? 'AUTO-BUY: ON' : 'AUTO-BUY: OFF';
        }
    } catch (err) {
        console.error('Toggle failed', err);
    }
}
