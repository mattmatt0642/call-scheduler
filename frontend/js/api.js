/* =========================
   Backend Communication
   ========================= */

const API_BASE = window.location.origin;

async function apiHealth() {
const res = await fetch(`${API_BASE}/api/health`);
if (!res.ok) throw new Error('Health check failed');
return res.json();
}

async function apiGenerate(year, month) {
const inp = buildScheduleRequest(year, month);
console.log('[apiGenerate] Sending request:', JSON.stringify(inp).length, 'bytes, doctors:', inp.doctors?.length, 'offices:', inp.offices?.length);
const res = await fetch(`${API_BASE}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(inp)
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
const res = await fetch(`${API_BASE}/api/export-balance`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doctors, offices, totals })
  });
  if (!res.ok) throw new Error('Failed to export balance');
  return res.text();
}

async function apiImportBalance(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/api/import-balance`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) throw new Error('Failed to import balance');
  return res.json();
}

async function apiExportSchedule(year, month, assignments, dayOffDates, customRestrictions) {
  const res = await fetch(`${API_BASE}/api/export-schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      year, month, doctors: STATE.doctors, offices: STATE.offices,
      assignments, dayOffDates: dayOffDates || [],
      customRestrictions: customRestrictions || []
    })
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
