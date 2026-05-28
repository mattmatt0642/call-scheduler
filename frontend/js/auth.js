/* =========================
   Authentication
   ========================= */

let _isAuthenticated = false;

async function checkAuth() {
try {
const res = await fetch(`${window.location.origin}/api/auth/check`);
const data = await res.json();
_isAuthenticated = data.authenticated === true;
} catch {
_isAuthenticated = false;
}
_updateAuthOverlay();
if (_isAuthenticated) {
const serverOk = await loadStateFromServer();
if (serverOk && typeof refreshUI === 'function') refreshUI();
}
return _isAuthenticated;
}

async function login(password) {
const res = await fetch(`${window.location.origin}/api/login`, {
method: 'POST',
headers: { 'Content-Type': 'application/json' },
body: JSON.stringify({ password })
});
if (!res.ok) {
const data = await res.json().catch(() => ({}));
throw new Error(data.error || 'Login failed');
}
_isAuthenticated = true;
_updateAuthOverlay();
const serverOk = await loadStateFromServer();
if (serverOk && typeof refreshUI === 'function') refreshUI();
}

function _updateAuthOverlay() {
    const overlay = document.getElementById('auth-overlay');
    if (!overlay) return;
    overlay.style.display = _isAuthenticated ? 'none' : 'flex';
}

function _initAuthOverlay() {
    const overlay = document.createElement('div');
    overlay.id = 'auth-overlay';
    overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:9999;background:var(--bg-primary);color:var(--text-primary);align-items:center;justify-content:center;font-family:var(--font-ui);';
    overlay.innerHTML = `
        <div style="text-align:center;max-width:360px;padding:2rem;">
            <h2 style="margin:0 0 0.5rem;font-size:1.25rem;">Enter Password</h2>
            <p style="color:var(--text-muted);font-size:0.85rem;margin:0 0 1.2rem;">This schedule is password-protected.</p>
            <input type="password" id="auth-password-input" placeholder="Password"
                style="width:100%;padding:0.55rem 0.75rem;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.9rem;box-sizing:border-box;" />
            <div id="auth-error" style="color:var(--accent-red);font-size:0.8rem;margin-top:0.4rem;min-height:1.2em;"></div>
            <button id="auth-submit-btn" style="margin-top:0.8rem;width:100%;padding:0.55rem;border:1px solid var(--accent-blue);border-radius:6px;background:var(--accent-blue);color:#fff;font-size:0.9rem;font-weight:600;cursor:pointer;">Sign In</button>
        </div>`;
    document.body.appendChild(overlay);

    const btn = document.getElementById('auth-submit-btn');
    const input = document.getElementById('auth-password-input');
    const errEl = document.getElementById('auth-error');

    const attempt = async () => {
        errEl.textContent = '';
        try {
            await login(input.value);
        } catch (e) {
            errEl.textContent = e.message;
        }
    };
    btn.addEventListener('click', attempt);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') attempt(); });
}

document.addEventListener('DOMContentLoaded', () => {
    _initAuthOverlay();
    checkAuth();
});
