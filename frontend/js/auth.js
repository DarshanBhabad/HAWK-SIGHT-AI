/* ============================================
   AUTHENTICATION - LOGIN & SIGNUP
   ============================================ */

// --- TAB TOGGLE BETWEEN LOGIN AND SIGNUP ---
function setupAuthTabs() {
    const loginBtn = document.getElementById('show-login-btn');
    const signupBtn = document.getElementById('show-signup-btn');
    const loginForm = document.getElementById('login-form-container');
    const signupForm = document.getElementById('signup-form-container');
    const toggleBg = document.getElementById('toggle-bg');

    loginBtn.addEventListener('click', () => {
        loginForm.classList.remove('hidden');
        loginForm.classList.add('block', 'animate-fade-in');
        signupForm.classList.add('hidden');
        signupForm.classList.remove('block', 'animate-fade-in');
        
        loginBtn.classList.add('text-white');
        loginBtn.classList.remove('text-gray-400');
        signupBtn.classList.add('text-gray-400');
        signupBtn.classList.remove('text-white');
        toggleBg.style.transform = 'translateX(0)';
    });

    signupBtn.addEventListener('click', () => {
        signupForm.classList.remove('hidden');
        signupForm.classList.add('block', 'animate-fade-in');
        loginForm.classList.add('hidden');
        loginForm.classList.remove('block', 'animate-fade-in');
        
        signupBtn.classList.add('text-white');
        signupBtn.classList.remove('text-gray-400');
        loginBtn.classList.add('text-gray-400');
        loginBtn.classList.remove('text-white');
        toggleBg.style.transform = 'translateX(100%)';
    });
}

// --- LOGIN HANDLER ---
function setupLogin() {
    document.getElementById('login-form').onsubmit = async (e) => {
        e.preventDefault();
        const email = e.target[0].value;
        const password = e.target[1].value;

        try {
            const res = await fetch(`${CONFIG.API_URL}/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();

            if (data.success) {
                localStorage.setItem(CONFIG.STORAGE.USER, JSON.stringify(data.user));
                localStorage.setItem(CONFIG.STORAGE.TOKEN, data.token);
                location.reload();
            } else {
                showAuthError(data.error || 'Login failed');
            }
        } catch (err) {
            console.error(err);
            showAuthError('Cannot reach server. Is Flask running?');
        }
    };
}

// --- SIGNUP HANDLER ---
function setupSignup() {
    document.getElementById('signup-form').onsubmit = async (e) => {
        e.preventDefault();
        const name = e.target[0].value;
        const email = e.target[1].value;
        const password = e.target[2].value;

        if (password.length < 6) {
            return showAuthError('Password must be at least 6 characters');
        }

        try {
            const res = await fetch(`${CONFIG.API_URL}/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, email, password })
            });
            const data = await res.json();

            if (data.success) {
                localStorage.setItem(CONFIG.STORAGE.USER, JSON.stringify(data.user));
                localStorage.setItem(CONFIG.STORAGE.TOKEN, data.token);
                location.reload();
            } else {
                showAuthError(data.error || 'Signup failed');
            }
        } catch (err) {
            console.error(err);
            showAuthError('Cannot reach server. Is Flask running?');
        }
    };
}

// --- LOGOUT ---
function logoutUser() {
    localStorage.removeItem(CONFIG.STORAGE.USER);
    localStorage.removeItem(CONFIG.STORAGE.TOKEN);
    location.reload();
}

// --- ERROR DISPLAY ---
function showAuthError(message) {
    let errorEl = document.getElementById('auth-error');
    if (!errorEl) {
        errorEl = document.createElement('div');
        errorEl.id = 'auth-error';
        errorEl.className = 'mt-4 p-3 bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg text-center';
        document.querySelector('.glass-effect').appendChild(errorEl);
    }
    errorEl.innerText = message;
    setTimeout(() => errorEl.remove(), 4000);
}
