/* ============================================
   FAVORITES - Mark stocks for auto-buy pool
   ============================================ */

// --- LOAD USER'S FAVORITES FROM SERVER ---
async function loadFavorites() {
    if (!STATE.currentUser) return;
    try {
        const res = await apiFetch('/favorites');
        const data = await res.json();
        STATE.favorites = new Set(data.favorites || []);
    } catch (err) {
        console.error('Failed to load favorites', err);
    }
}

// --- TOGGLE STAR ON / OFF ---
async function toggleFavorite(symbol) {
    if (!STATE.currentUser) return alert('Please log in first');

    const isFav = STATE.favorites.has(symbol);
    const action = isFav ? 'remove' : 'add';

    // Optimistic UI update
    if (isFav) STATE.favorites.delete(symbol);
    else STATE.favorites.add(symbol);
    updateStarUI(symbol);

    try {
        const res = await apiFetch('/favorites', {
            method: 'POST',
            body: JSON.stringify({ symbol, action })
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error);
    } catch (err) {
        // Revert on failure
        if (action === 'add') STATE.favorites.delete(symbol);
        else STATE.favorites.add(symbol);
        updateStarUI(symbol);
        console.error('Favorite toggle failed', err);
    }
}

function updateStarUI(symbol) {
    const star = document.querySelector(`.fav-star[data-symbol="${symbol}"]`);
    if (!star) return;
    const isFav = STATE.favorites.has(symbol);
    star.className = isFav ? 'fas fa-star fav-star active' : 'far fa-star fav-star';
    star.setAttribute('data-symbol', symbol);
}
