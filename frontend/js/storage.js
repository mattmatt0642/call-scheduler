/* =========================
   LocalStorage + State — with Snapshots + Stale Detection
   ========================= */

const DEFAULT_STATE = {
  doctors: [],
  offices: [],
  settings: {
    minDaysBetweenCalls: 1,
    solverTimeLimitSeconds: 30,
  },
  blackouts: {},
  schedules: {},
  totals: {},
};

let STATE = structuredClone ? structuredClone(DEFAULT_STATE) : JSON.parse(JSON.stringify(DEFAULT_STATE));

function generateId() {
  return Math.random().toString(36).slice(2, 10);
}

let _saveStateTimer = null;
let _snapshotTimer = null;

const SNAPSHOT_KEY = 'callsched_snapshots';
const SNAPSHOT_INTERVAL_MS = 10 * 60 * 1000;
const MAX_SNAPSHOTS = 5;

function takeSnapshot() {
  try {
    const raw = localStorage.getItem('callsched');
    if (!raw) return;
    const parsed = JSON.parse(raw);
    const meta = {
      key: 'callsched_snapshot_' + Date.now(),
      ts: Date.now(),
      doctorCount: parsed.doctors?.length || 0,
      scheduleMonths: Object.keys(parsed.schedules || {}).length,
      sizeKB: (new Blob([raw]).size / 1024).toFixed(1),
    };
    const snapRaw = localStorage.getItem(SNAPSHOT_KEY);
    const snaps = snapRaw ? JSON.parse(snapRaw) : [];
    snaps.unshift(meta);
    if (snaps.length > MAX_SNAPSHOTS) {
      const removed = snaps.splice(MAX_SNAPSHOTS);
      for (const s of removed) {
        localStorage.removeItem(s.key);
      }
    }
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snaps));
    localStorage.setItem(meta.key, raw);
    console.log('[Storage] Snapshot saved:', meta.key, meta.sizeKB + 'KB');
  } catch (e) {
    console.warn('[Storage] Snapshot failed:', e.message);
  }
}

function startPeriodicSnapshots() {
  stopPeriodicSnapshots();
  _snapshotTimer = setInterval(takeSnapshot, SNAPSHOT_INTERVAL_MS);
  console.log('[Storage] Periodic snapshots started, every', SNAPSHOT_INTERVAL_MS / 60000, 'min');
}

function stopPeriodicSnapshots() {
  if (_snapshotTimer) {
    clearInterval(_snapshotTimer);
    _snapshotTimer = null;
  }
}

function getSnapshots() {
  try {
    const raw = localStorage.getItem(SNAPSHOT_KEY);
    if (!raw) return [];
    return JSON.parse(raw);
  } catch (e) {
    return [];
  }
}

function getSnapshotData(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function restoreSnapshot(key) {
  const data = getSnapshotData(key);
  if (!data) throw new Error('Snapshot not found: ' + key);
  _mergeDefaults(data);
  STATE = data;
  saveState();
  return true;
}

function saveState() {
  try {
    localStorage.setItem('callsched', JSON.stringify(STATE));
  } catch (e) {
    console.warn('Failed to save state to localStorage:', e.message);
  }
  clearTimeout(_saveStateTimer);
  _saveStateTimer = setTimeout(async () => {
    try {
      await fetch(`${window.location.origin}/api/state`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(STATE),
      });
    } catch (e) {
      // Queue for later if offline
      if (!navigator.onLine) {
        try {
          const qRaw = localStorage.getItem('callsched_pending_sync');
          const pending = qRaw ? JSON.parse(qRaw) : [];
          pending.push({ ts: Date.now(), state: STATE });
          localStorage.setItem('callsched_pending_sync', JSON.stringify(pending.slice(-10)));
        } catch (qe) {}
      }
    }
  }, 300);
}

function loadState() {
  try {
    const raw = localStorage.getItem('callsched');
    if (raw) {
      const parsed = JSON.parse(raw);
      _mergeDefaults(parsed);
      STATE = parsed;
      migrateBlackoutFormat();
    }
  } catch (e) {
    console.warn('Failed to load state from localStorage:', e.message);
  }
}

async function loadStateFromServer() {
  try {
    const res = await fetch(`${window.location.origin}/api/state`);
    if (!res.ok) return false;
    const data = await res.json();
    if (data && Object.keys(data).length > 0) {
      _mergeDefaults(data);
      _mergeServerIntoLocal(data);
      migrateBlackoutFormat();
      return true;
    }
  } catch {
  }
  return false;
}

function _mergeServerIntoLocal(server) {
  const serverTs = server._lastModified;
  const localRaw = localStorage.getItem('callsched');
  const localTs = localRaw ? JSON.parse(localRaw)._lastModified : 0;
  if (serverTs && serverTs <= localTs) return;
  for (const key of ['doctors', 'offices']) {
    if (server[key] && server[key].length > 0) {
      STATE[key] = server[key];
    }
  }
  if (server.settings) STATE.settings = { ...STATE.settings, ...server.settings };
  if (server.schedules) {
    for (const mk in server.schedules) {
      STATE.schedules[mk] = server.schedules[mk];
    }
  }
  if (server.blackouts) {
    for (const mk in server.blackouts) {
      STATE.blackouts[mk] = server.blackouts[mk];
    }
  }
  if (server.totals) {
    for (const docId in server.totals) {
      STATE.totals[docId] = server.totals[docId];
    }
  }
  saveState();
}

function _mergeDefaults(parsed) {
  for (const key of Object.keys(DEFAULT_STATE)) {
    if (!(key in parsed)) {
      parsed[key] = JSON.parse(JSON.stringify(DEFAULT_STATE[key]));
    }
  }
  for (const doc of parsed.doctors) {
    if (doc.hospitalCallEligible === undefined) doc.hospitalCallEligible = true;
    if (doc.surgicalAssistEligible === undefined) doc.surgicalAssistEligible = true;
    if (doc.weekendCallOff === undefined) doc.weekendCallOff = false;
    if (doc.maxFridayNightCalls === undefined) doc.maxFridayNightCalls = 2;
    if (doc.maxWeekendBlocks === undefined) doc.maxWeekendBlocks = 2;
  }
}

function getMonthKey(year, month) {
  return `${year}-${String(month + 1).padStart(2, '0')}`;
}

function updateTotalsFromSchedule(monthResult) {
  const totals = {};
  for (const monthKey in STATE.schedules) {
    const result = STATE.schedules[monthKey];
    if (!result || !result.counts) continue;
    for (const [docId, counts] of Object.entries(result.counts)) {
      if (!totals[docId]) {
        totals[docId] = {
          weekday_day: 0, weekday_night: 0, friday_night: 0,
          weekend_blocks: 0, total_sessions: 0,
          am_sessions: 0, pm_sessions: 0, late_sessions: 0,
          office_visits: {},
        };
      }
      totals[docId].weekday_day += counts.weekdayDayCalls || 0;
      totals[docId].weekday_night += counts.weekdayNightCalls || 0;
      totals[docId].friday_night += counts.fridayNightCalls || 0;
      totals[docId].weekend_blocks += counts.weekendBlocks || 0;
      totals[docId].total_sessions += counts.totalSessions || 0;
      totals[docId].am_sessions += counts.amSessions || 0;
      totals[docId].pm_sessions += counts.pmSessions || 0;
      totals[docId].late_sessions += counts.lateSessions || 0;
      const visits = counts.officeVisitCounts || {};
      for (const [officeId, count] of Object.entries(visits)) {
        totals[docId].office_visits[officeId] = (totals[docId].office_visits[officeId] || 0) + (count || 0);
      }
    }
  }
  STATE.totals = totals;
  saveState();
}

const defaultStateDoctor = () => ({
  id: generateId(),
  name: 'Dr. ' + (['Smith','Jones','Lee','Kim','Patel','Brown','Wilson','Taylor','Garcia','Chen'][Math.floor(Math.random()*10)]),
  allowedOffices: null,
  officePreferences: [],
  requiredSessionsPerWeek: 5,
  hospitalCallEligible: true,
  surgicalAssistEligible: true,
  weekendCallOff: false,
  maxWeekdayDayCalls: 5,
  maxWeekdayNightCalls: 5,
  maxFridayNightCalls: 2,
  maxWeekendBlocks: 2,
  preferredCallDays: [],
  postCallPreference: 'no_preference',
  callShiftPreference: 'no_preference',
  dayNightPreference: 'balanced',
  amPmPreference: 'balanced',
  standingDaysOff: [],
  fixedRecurring: [],
  oneTimeOverrides: [],
});

function migrateBlackoutFormat() {
  let changed = false;
  for (const mk of Object.keys(STATE.blackouts)) {
    const byDoc = STATE.blackouts[mk];
    for (const docId of Object.keys(byDoc)) {
      const val = byDoc[docId];
      if (Array.isArray(val) && val.length > 0 && typeof val[0] === 'string') {
        byDoc[docId] = val.map(dateStr => ({ date: dateStr, period: 'all_day' }));
        changed = true;
      }
    }
  }
  if (changed) saveState();
}

function getDataAgeMs() {
  try {
    const raw = localStorage.getItem('callsched');
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const savedAt = parsed._savedAt || parsed._lastModified;
    if (!savedAt) return null;
    return Date.now() - savedAt;
  } catch (e) {
    return null;
  }
}

function isDataStale(thresholdMs = 60 * 60 * 1000) {
  const age = getDataAgeMs();
  if (age === null) return false;
  return age > thresholdMs;
}

// ── Init ─────────────────────────────────────────────────────────────────────
(function initStorage() {
  loadState();
  startPeriodicSnapshots();
})();