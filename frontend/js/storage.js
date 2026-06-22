/* =========================
   LocalStorage + State
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

let STATE = structuredClone
  ? structuredClone(DEFAULT_STATE)
  : JSON.parse(JSON.stringify(DEFAULT_STATE));

function generateId() {
  return Math.random().toString(36).slice(2, 10);
}

function saveState() {
  try {
    localStorage.setItem('callsched', JSON.stringify(STATE));
  } catch (e) {
    console.warn('Failed to save state:', e.message);
  }
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
    console.warn('Failed to load state:', e.message);
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
        totals[docId].office_visits[officeId] =
          (totals[docId].office_visits[officeId] || 0) + (count || 0);
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
  weekendPairingPreference: true,
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
    if (doc.weekendPairingPreference === undefined) doc.weekendPairingPreference = true;
    if (doc.maxFridayNightCalls === undefined) doc.maxFridayNightCalls = 2;
    if (doc.maxWeekendBlocks === undefined) doc.maxWeekendBlocks = 2;
  }
}

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

(function initStorage() {
  loadState();
})();
