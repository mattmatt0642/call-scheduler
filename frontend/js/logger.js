/* =========================
   Client-side Error Logger
   Captures errors to localStorage, flushes on next API success
   ========================= */

const ERROR_LOG_KEY = 'callsched_errlog';
const MAX_LOG_ENTRIES = 50;

function logError(type, message, context) {
  try {
    const raw = localStorage.getItem(ERROR_LOG_KEY);
    const log = raw ? JSON.parse(raw) : [];
    log.unshift({
      ts: Date.now(),
      type,
      message,
      context: context || null,
      url: window.location.href,
      userAgent: navigator.userAgent.slice(0, 100),
    });
    if (log.length > MAX_LOG_ENTRIES) log.length = MAX_LOG_ENTRIES;
    localStorage.setItem(ERROR_LOG_KEY, JSON.stringify(log));
  } catch (e) {}
}

function flushErrorLog() {
  try {
    const raw = localStorage.getItem(ERROR_LOG_KEY);
    if (!raw) return;
    const log = JSON.parse(raw);
    if (!log.length) return;
    const payload = JSON.stringify({ clientErrors: log, flushedAt: Date.now() });
    const sizeKB = new Blob([payload]).size / 1024;
    if (sizeKB > 10) {
      localStorage.setItem(ERROR_LOG_KEY, JSON.stringify([]));
      return;
    }
    fetch(`${window.location.origin}/api/client-log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
    }).then(() => {
      localStorage.setItem(ERROR_LOG_KEY, JSON.stringify([]));
    }).catch(() => {});
  } catch (e) {}
}

function getErrorLog() {
  try {
    const raw = localStorage.getItem(ERROR_LOG_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function clearErrorLog() {
  try {
    localStorage.removeItem(ERROR_LOG_KEY);
  } catch (e) {}
}

// ── Global error handlers ───────────────────────────────────────────────────

window.addEventListener('error', e => {
  logError('uncaught', e.message, {
    filename: e.filename,
    lineno: e.lineno,
    colno: e.colno,
  });
});

window.addEventListener('unhandledrejection', e => {
  logError('unhandled_rejection', String(e.reason), { stack: e.reason?.stack });
});

// ── Wrappers for fetch ──────────────────────────────────────────────────────

function wrapFetch(originalFetch) {
  return function wrappedFetch(url, options) {
    return originalFetch(url, options).then(res => {
      if (res.ok && (url.toString().includes('/api/') || url.includes('/api/'))) {
        setTimeout(() => flushErrorLog(), 1000);
      }
      return res;
    }).catch(async err => {
      logError('fetch_failed', err.message, { url: String(url) });
      throw err;
    });
  };
}