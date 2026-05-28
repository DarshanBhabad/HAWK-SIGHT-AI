/* ============================================
   GLOBAL CONFIGURATION
   ============================================ */

const CONFIG = {
    // Flask backend URL - change to your deployed URL in production
    API_URL: 'http://127.0.0.1:5000',

    // Stocks tracked by Hawk Sight
    TICKERS: ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA'],

    // How often to refresh live prices (ms)
    PRICE_REFRESH_INTERVAL: 30000,  // 30 seconds

    // Prediction confidence thresholds
    CONFIDENCE: {
        HIGH: 0.65,
        MEDIUM: 0.55,
        // anything below MEDIUM is "low"
    },

    // Local storage keys
    STORAGE: {
        USER: 'hawk_user',
        TOKEN: 'hawk_token',
    }
};

// Global runtime state (shared across modules)
const STATE = {
    stockData: {},          // { AAPL: {price, change}, ... }
    currentSelection: 'AAPL',
    priceChart: null,
    currentUser: null,
    favorites: new Set(),   // Set of favorited ticker symbols
};

// Helper: authenticated fetch (adds JWT token automatically)
async function apiFetch(endpoint, options = {}) {
    const token = localStorage.getItem(CONFIG.STORAGE.TOKEN);
    const headers = {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
    };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(`${CONFIG.API_URL}${endpoint}`, {
        ...options,
        headers,
    });

    // If token expired, kick user back to login
    if (response.status === 401) {
        localStorage.removeItem(CONFIG.STORAGE.USER);
        localStorage.removeItem(CONFIG.STORAGE.TOKEN);
        location.reload();
        return null;
    }

    return response;
}
