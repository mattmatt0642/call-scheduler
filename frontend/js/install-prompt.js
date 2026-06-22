/* =========================
   Connection State + Install Prompt
   Online/offline detection, banners, PWA install handling
   ========================= */

/* ── Connection State ─────────────────────────────────────────────────────── */

let _connBannerShown = false;
let _connDismissed = false;

function initConnectionIndicator() {
  updateConnectionBanner();

  window.addEventListener('online', () => {
    _connDismissed = false;
    updateConnectionBanner();
    if (typeof flushErrorLog === 'function') flushErrorLog();
    if (typeof replaySyncQueue === 'function') replaySyncQueue();
  });

  window.addEventListener('offline', () => {
    _connDismissed = false;
    updateConnectionBanner();
  });

  document.addEventListener('click', e => {
    if (e.target.closest('.conn-banner-dismiss')) {
      _connDismissed = true;
      const banner = document.getElementById('conn-banner');
      if (banner) banner.remove();
    }
  });
}

function updateConnectionBanner() {
  const existing = document.getElementById('conn-banner');
  if (existing) existing.remove();

  if (!navigator.onLine && !_connDismissed) {
    showConnectionBanner('offline', 'You are offline. Changes will sync when connected.');
  } else if (navigator.onLine && _connBannerShown) {
    showConnectionBanner('online', 'Back online', 3000);
  }
}

function showConnectionBanner(type, message, autoHideMs) {
  const banner = document.createElement('div');
  banner.id = 'conn-banner';
  banner.className = 'conn-banner conn-banner-' + type;
  banner.setAttribute('role', 'alert');
  banner.innerHTML = `
    <span class="conn-banner-icon">${type === 'offline' ? '📡' : '✅'}</span>
    <span class="conn-banner-msg">${message}</span>
    <button class="conn-banner-dismiss btn btn-sm btn-ghost" aria-label="Dismiss">&times;</button>
  `;
  const header = document.querySelector('.app-header');
  if (header) {
    header.insertAdjacentElement('afterend', banner);
    requestAnimationFrame(() => banner.classList.add('visible'));
  }
  if (type === 'offline') _connBannerShown = true;
  if (autoHideMs) {
    setTimeout(() => {
      banner.classList.remove('visible');
      setTimeout(() => banner.remove(), 300);
    }, autoHideMs);
  }
}

function isOnline() {
  return navigator.onLine;
}

/* ── PWA Install Prompt ───────────────────────────────────────────────────── */

let _installPromptEvent = null;
let _installShown = false;

function initInstallPrompt() {
  window.addEventListener('beforeinstallprompt', e => {
    e.preventDefault();
    _installPromptEvent = e;
    if (!_installShown) {
      _installShown = true;
      showInstallBanner();
    }
  });

  window.addEventListener('appinstalled', () => {
    const banner = document.getElementById('install-banner');
    if (banner) {
      banner.innerHTML = '<span>App installed! 🎉</span>';
      setTimeout(() => banner.remove(), 3000);
    }
    _installPromptEvent = null;
  });
}

function showInstallBanner() {
  const existing = document.getElementById('install-banner');
  if (existing) existing.remove();

  const banner = document.createElement('div');
  banner.id = 'install-banner';
  banner.className = 'conn-banner conn-banner-info';
  banner.setAttribute('role', 'status');
  banner.innerHTML = `
    <span class="conn-banner-icon">📱</span>
    <span class="conn-banner-msg">Add to home screen for the best experience</span>
    <button class="btn btn-sm btn-primary" id="install-btn">Install</button>
    <button class="conn-banner-dismiss btn btn-sm btn-ghost" aria-label="Dismiss">&times;</button>
  `;
  const header = document.querySelector('.app-header');
  if (header) {
    header.insertAdjacentElement('afterend', banner);
    requestAnimationFrame(() => banner.classList.add('visible'));
  }

  document.getElementById('install-btn')?.addEventListener('click', async () => {
    if (!_installPromptEvent) return;
    _installPromptEvent.prompt();
    const { outcome } = await _installPromptEvent.userChoice;
    banner.remove();
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initConnectionIndicator();
  initInstallPrompt();
});