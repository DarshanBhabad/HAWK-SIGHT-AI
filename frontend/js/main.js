/* ============================================
   MAIN APP INITIALIZATION
   ============================================ */

document.addEventListener('DOMContentLoaded', async () => {
    // Load user from localStorage
    STATE.currentUser = JSON.parse(localStorage.getItem(CONFIG.STORAGE.USER)) || null;

    // Setup auth UI handlers
    setupAuthTabs();
    setupLogin();
    setupSignup();

    // Start market status checker
    checkMarketStatus();
    setInterval(checkMarketStatus, 60000);

    // If user is logged in, show the app
    if (STATE.currentUser) {
        document.getElementById('auth-page').classList.add('hidden');
        document.getElementById('app-container').classList.remove('hidden');
        document.getElementById('user-name-display').innerText = STATE.currentUser.name;
        document.getElementById('display-balance').innerText =
            `$${STATE.currentUser.balance.toFixed(2)}`;

        // Load favorites first, then market table (so stars render correctly)
        await loadFavorites();
        await updateMarketTable();

        // Auto-refresh prices periodically
        setInterval(updateMarketTable, CONFIG.PRICE_REFRESH_INTERVAL);
    }
});
