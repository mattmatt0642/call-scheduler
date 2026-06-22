/* =========================
   Backend Communication — with Retry + Offline Queue
   ========================= */

const API_BASE = window.location.origin;
const SYNC_QUEUE_KEY = 'callsched_sync_queue';

const RETRY_CONFIG = {
  maxRetries: 3,
  baseDelayMs: 800,
  maxDelayMs: 8000,
  retryOn: [0, 408, 429, 500, 502, 503, 504],
};

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function isRetryableStatus(status) {
  return RETRY_CONFIG.retryOn.includes(status);
}

async function fetchWithRetry(url, options = {}, retries = RETRY_CONFIG.maxRetries) {
  const timeout = options._timeout || 30000;
  const doFetch = async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const res = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timer);
      if (!res.ok && isRetryableStatus(res.status)) {
        const text = await res.text().catch(() => '');
        const err = new Error(text || `HTTP ${res.status}`);
        err.status = res.status;
        err.isRetryable = true;
        throw err;
      }
      return res;
    } catch (e) {
      clearTimeout(timer);
      if (e.name === 'AbortError') {
        const err = new Error('Request timed out');
        err.isRetryable = true;
        throw err;
      }
      throw e;
    }
  };

  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await doFetch();
      if (attempt > 0) console.log('[API] Retry success on attempt', attempt + 1, url);
      return res;
    } catch (err) {
      lastError = err;
      const isOffline = !navigator.onLine || err.message.includes('Failed to fetch') || err.message.includes('NetworkError');
      if (isOffline) {
        if (options.method === 'GET' || !options.method) {
          throw err;
        }
        enqueueSyncRequest(url, options);
        const offlineErr = new Error('Offline — request queued for when you reconnect');
        offlineErr.queued = true;
        throw offlineErr;
      }
      if (!err.isRetryable && attempt >= retries) throw err;
      if (attempt < retries && err.isRetryable !== false) {
        const delay = Math.min(RETRY_CONFIG.baseDelayMs * Math.pow(2, attempt), RETRY_CONFIG.maxDelayMs);
        const jitter = delay * 0.15 * Math.random();
        console.log('[API] Retry', attempt + 1, '/', retries, 'in', Math.round(delay + jitter) + 'ms —', err.message);
        await sleep(delay + jitter);
      } else if (attempt >= retries) {
        break;
      }
    }
  }
  throw lastError;
}

function enqueueSyncRequest(url, options) {
  try {
    const raw = localStorage.getItem(SYNC_QUEUE_KEY);
    const queue = raw ? JSON.parse(raw) : [];
    queue.push({
      url, options,
      queuedAt: Date.now(),
      method: options.method || 'GET',
    });
    localStorage.setItem(SYNC_QUEUE_KEY, JSON.stringify(queue));
    console.log('[SyncQueue] Enqueued', options.method, url, '— queue size:', queue.length);
  } catch (e) {}
}

async function replaySyncQueue() {
  try {
    const raw = localStorage.getItem(SYNC_QUEUE_KEY);
    if (!raw) return;
    const queue = JSON.parse(raw);
    if (!queue.length) return;
    console.log('[SyncQueue] Replaying', queue.length, 'queued request(s)');
    const stillPending = [];
    for (const item of queue) {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        const res = await fetch(item.url, { ...item.options, signal: controller.signal });
        clearTimeout(timer);
        if (res.ok) {
          console.log('[SyncQueue] Replayed OK:', item.method, item.url);
        } else {
          stillPending.push(item);
        }
      } catch (e) {
        stillPending.push(item);
      }
    }
    localStorage.setItem(SYNC_QUEUE_KEY, JSON.stringify(stillPending));
    if (stillPending.length > 0) {
      console.log('[SyncQueue] Still pending:', stillPending.length);
    }
  } catch (e) {}
}

function getSyncQueueSize() {
  try {
    const raw = localStorage.getItem(SYNC_QUEUE_KEY);
    if (!raw) return 0;
    return JSON.parse(raw).length;
  } catch (e) {
    return 0;
  }
}

async function apiHealth() {
  const res = await fetchWithRetry(`${API_BASE}/api/health`, { method: 'GET', _timeout: 5000 }, 2);
  if (!res.ok) throw new Error('Health check failed');
  return res.json();
}

async function apiGenerate(year, month) {
  const inp = buildScheduleRequest(year, month);
  console.log('[apiGenerate] Sending request:', JSON.stringify(inp).length, 'bytes, doctors:', inp.doctors?.length, 'offices:', inp.offices?.length);
  const res = await fetchWithRetry(`${API_BASE}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(inp),
    _timeout: 120000,
  });
  if (!res.ok) {
    const err = await res.text();
    console.error('[apiGenerate] Error:', res.status, err);
    throw new Error(err || 'Generate failed');
  }
  const data = await res.json();
  console.log('[apiGenerate] Response: assignments=', data.assignments?.length, 'slots=', data.slots?.length);
  return data;
}

async function apiExportBalance(doctors, offices, totals) {
  const res = await fetchWithRetry(`${API_BASE}/api/export-balance`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doctors, offices, totals }),
  });
  if (!res.ok) throw new Error('Failed to export balance');
  return res.text();
}

async function apiImportBalance(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetchWithRetry(`${API_BASE}/api/import-balance`, { method: 'POST', body: form });
  if (!res.ok) throw new Error('Failed to import balance');
  return res.json();
}

async function apiExportSchedule(year, month, assignments, dayOffDates, customRestrictions) {
  const res = await fetchWithRetry(`${API_BASE}/api/export-schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      year, month, doctors: STATE.doctors, offices: STATE.offices,
      assignments, dayOffDates: dayOffDates || [],
      customRestrictions: customRestrictions || [],
    }),
  });
  if (!res.ok) throw new Error('Failed to export schedule');
  return res.text();
}

async function apiPostState(state) {
  const res = await fetchWithRetry(`${API_BASE}/api/state`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state),
  });
  if (!res.ok) throw new Error('Failed to sync state');
  return res.json();
}

function buildScheduleRequest(year, month) {
  return {
    year, month,
    doctors: STATE.doctors,
    offices: STATE.offices,
    globalOfficeRanking: buildGlobalOfficeRanking(),
    dayOffDates: extractDayOffDates(year, month),
    customRestrictions: [],
    lockedAssignments: [],
    historicalBalance: STATE.totals || {},
    solverTimeLimitSeconds: STATE.settings.solverTimeLimitSeconds,
  };
}

function buildGlobalOfficeRanking() {
  const hospital = STATE.offices.find(o => o.isHospital);
  const nonHosp = STATE.offices.filter(o => !o.isHospital);
  const ids = [];
  if (hospital) ids.push(hospital.id);
  nonHosp.forEach(o => ids.push(o.id));
  return ids;
}

function extractDayOffDates(year, month) {
  const mk = getMonthKey(year, month);
  const bo = STATE.blackouts[mk] || {};
  const perDoctor = {};
  for (const [docId, entries] of Object.entries(bo)) {
    if (Array.isArray(entries) && entries.length > 0) {
      const dateEntries = entries.map(e => {
        const obj = { date: e.date, period: e.period || 'all_day' };
        if (e.startTime) obj.startTime = e.startTime;
        if (e.endTime) obj.endTime = e.endTime;
        return obj;
      });
      perDoctor[docId] = dateEntries;
    }
  }
  return perDoctor;
}