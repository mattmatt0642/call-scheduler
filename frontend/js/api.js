/* =========================
   Backend Communication
   ========================= */

const API_BASE = window.location.origin;

async function apiFetch(url, options = {}) {
  const timeout = options._timeout || 30000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(timer);
    return res;
  } catch (e) {
    clearTimeout(timer);
    throw e;
  }
}

async function apiHealth() {
  const res = await apiFetch(`${API_BASE}/api/health`, { method: 'GET', _timeout: 5000 });
  if (!res.ok) throw new Error('Health check failed');
  return res.json();
}

async function apiGenerate(year, month) {
  const inp = buildScheduleRequest(year, month);
  const res = await apiFetch(`${API_BASE}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(inp),
    _timeout: 120000,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || 'Generate failed');
  }
  return res.json();
}

async function apiExportBalance(doctors, offices, totals) {
  const res = await apiFetch(`${API_BASE}/api/export-balance`, {
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
  const res = await apiFetch(`${API_BASE}/api/import-balance`, { method: 'POST', body: form });
  if (!res.ok) throw new Error('Failed to import balance');
  return res.json();
}

async function apiExportSchedule(year, month, assignments) {
  const res = await apiFetch(`${API_BASE}/api/export-schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      year, month, doctors: STATE.doctors, offices: STATE.offices,
      assignments, dayOffDates: [], customRestrictions: [],
    }),
  });
  if (!res.ok) throw new Error('Failed to export schedule');
  return res.text();
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
      perDoctor[docId] = entries.map(e => {
        const obj = { date: e.date, period: e.period || 'all_day' };
        if (e.startTime) obj.startTime = e.startTime;
        if (e.endTime) obj.endTime = e.endTime;
        return obj;
      });
    }
  }
  return perDoctor;
}
