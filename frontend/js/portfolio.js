/* ============================================
   PORTFOLIO MODAL
   ============================================ */

async function openPortfolio() {
    if (!STATE.currentUser) return;
    document.getElementById('portfolio-modal').classList.remove('hidden');

    try {
        const res = await apiFetch(`/portfolio`);
        const data = await res.json();

        let totalInvested = 0;
        let currentValue = 0;
        const tbody = document.getElementById('portfolio-body');
        tbody.innerHTML = '';

        if (!data.portfolio || data.portfolio.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center py-8 text-gray-500 font-medium">Your portfolio is empty. Start trading!</td></tr>`;
        } else {
            for (const item of data.portfolio) {
                const livePrice = STATE.stockData[item.symbol]?.price || 0;

                const invested = item.shares * item.avg_price;
                const current = item.shares * livePrice;
                const profit = current - invested;
                const profitPercent = invested > 0 ? (profit / invested) * 100 : 0;

                totalInvested += invested;
                currentValue += current;

                const color = profit >= 0 ? 'text-green-400' : 'text-red-400';
                const sign = profit >= 0 ? '+' : '';

                tbody.innerHTML += `
                    <tr class="hover:bg-gray-800/50 transition">
                        <td class="px-5 py-4 font-bold text-white">
                            <div class="flex items-center gap-2">
                                <span class="w-6 h-6 rounded-full bg-gray-700 flex items-center justify-center text-[10px] text-gray-300">${item.symbol[0]}</span>
                                ${item.symbol}
                            </div>
                        </td>
                        <td class="px-5 py-4 text-center text-gray-300">${item.shares}</td>
                        <td class="px-5 py-4 font-mono text-gray-400">$${item.avg_price.toFixed(2)}</td>
                        <td class="px-5 py-4 font-mono text-white">$${livePrice.toFixed(2)}</td>
                        <td class="px-5 py-4 text-right font-mono ${color} font-bold">
                            ${sign}$${profit.toFixed(2)}
                            <span class="text-xs block">${sign}${profitPercent.toFixed(2)}%</span>
                        </td>
                    </tr>
                `;
            }
        }

        const totalProfit = currentValue - totalInvested;
        const profitColor = totalProfit >= 0 ? 'text-green-400' : 'text-red-400';
        const profitSign = totalProfit >= 0 ? '+' : '-';

        document.getElementById('port-invested').innerText = `$${totalInvested.toFixed(2)}`;
        document.getElementById('port-current-value').innerText = `$${currentValue.toFixed(2)}`;

        const returnCard = document.getElementById('port-return');
        returnCard.innerText = `${profitSign}$${Math.abs(totalProfit).toFixed(2)}`;
        returnCard.className = `text-2xl font-mono ${profitColor}`;

    } catch (err) {
        console.error('Error loading portfolio', err);
    }
}

function closePortfolio() {
    document.getElementById('portfolio-modal').classList.add('hidden');
}
