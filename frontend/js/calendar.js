/* =========================
Calendar → Spreadsheet View
========================= */

function buildCalendarHTML(year, month, scheduleData) {
	const DAYS_IN_MONTH = new Date(year, month + 1, 0).getDate();
	const FIRST_DOW = (new Date(year, month, 1).getDay() + 6) % 7;
	const MONTH_NAME = new Date(year, month, 1).toLocaleString('default', { month: 'long' });
	const MONTH_STR = String(month + 1).padStart(2, '0');
	const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

	console.log('[buildCalendarHTML]', year, month, 'slots:', scheduleData?.slots?.length, 'assignments:', scheduleData?.assignments?.length);

	const slotMap = {};
	const assignMap = {};
	if (scheduleData) {
		for (const s of (scheduleData.slots || [])) slotMap[s.slotId] = s;
		for (const a of (scheduleData.assignments || [])) {
			if (!assignMap[a.slotId]) assignMap[a.slotId] = [];
			assignMap[a.slotId].push(a);
		}
	}

	const nonHosp = [...new Set((scheduleData?.slots || [])
		.filter(s => !s.isHospital && s.officeId)
		.map(s => s.officeId))]
		.map(id => ({ id, name: STATE.offices.find(o => o.id === id)?.name || id }));

	const hospId = [...new Set((scheduleData?.slots || [])
		.filter(s => s.isHospital)
		.map(s => s.officeId))][0] || null;

	const hospName = hospId ? (STATE.offices.find(o => o.id === hospId)?.name || 'Hosp') : null;

	const callCols = [
	{ key: 'call_day', label: 'Call Day', width: '85px' },
	{ key: 'call_night', label: 'Call Night', width: '85px' },
	{ key: 'call_weekend', label: 'Wknd Sat', width: '85px' },
	{ key: 'call_weekend_sun', label: 'Wknd Sun', width: '85px' },
	{ key: 'surgical_am', label: 'Surg AM', width: '78px' },
	{ key: 'surgical_hosp_pm', label: 'Surg PM', width: '78px' },
	];

	const officeCols = nonHosp.flatMap(o => [
		{ key: `${o.id}_am`, label: `${o.name} AM`, width: '70px' },
		{ key: `${o.id}_pm`, label: `${o.name} PM`, width: '70px' },
		{ key: `${o.id}_late`, label: `${o.name} Late`, width: '70px' },
	]);

	const hospCols = hospId ? [
		{ key: `${hospId}_am`, label: `${hospName} AM`, width: '70px' },
		{ key: `${hospId}_pm`, label: `${hospName} PM`, width: '70px' },
	] : [];

	const allCols = [...callCols, ...officeCols, ...hospCols];

	const dayData = {};
	for (let d = 1; d <= DAYS_IN_MONTH; d++) {
		dayData[d] = { dateStr: `${year}-${MONTH_STR}-${String(d).padStart(2, '0')}`, slots: {} };
	}

	if (scheduleData?.slots) {
		for (const slot of scheduleData.slots) {
			const dayNum = parseInt(slot.date.split('-')[2], 10);
			if (!dayData[dayNum]) continue;
			const assigned = assignMap[slot.slotId];
			if (!assigned || !assigned.length) continue;
			const docName = assigned.map(a => getDoctorLastName(a.doctorId)).filter(Boolean).join(', ');
			if (!docName) continue;

			const chip = getChipClass(slot);

			if (['call_day', 'call_night', 'call_weekend', 'call_weekend_sun'].includes(slot.shiftType)) {
				dayData[dayNum].slots[slot.shiftType] = { doc: docName, chip };
			}
			else if (slot.shiftType === 'surgical_am') {
				dayData[dayNum].slots['surgical_am'] = { doc: docName, chip };
			}
			else if (slot.shiftType === 'surgical_hosp_pm') {
				dayData[dayNum].slots['surgical_hosp_pm'] = { doc: docName, chip };
			}
			else if (['office_am', 'office_pm', 'office_late'].includes(slot.shiftType)) {
				const suffix = slot.shiftType.replace('office_', '');
				dayData[dayNum].slots[`${slot.officeId}_${suffix}`] = { doc: docName, chip };
			}
		}
	}

let html = `<div class="schedule-sheet">
<table class="sheet-table">
		<thead><tr><th>Date</th>`;
	for (const col of allCols) {
		html += `<th style="min-width:${col.width}">${col.label}</th>`;
	}
html += '</tr></thead><tbody>';

for (let d = 1; d <= DAYS_IN_MONTH; d++) {
		const dow = (FIRST_DOW + d - 1) % 7;
		const isWeekend = dow >= 5;
		const { slots, dateStr } = dayData[d];
		html += `<tr${isWeekend ? ' style="opacity:0.55"' : ''}>`;
		html += `<td>${DAY_NAMES[dow]} ${d}<br><span style="font-size:0.65rem;color:var(--text-muted)">${dateStr}</span></td>`;
		for (const col of allCols) {
			const cell = slots[col.key];
			if (cell) {
				html += `<td><div class="chip ${cell.chip}">${cell.doc}</div></td>`;
			} else {
				html += `<td><span class="chip chip-empty">—</span></td>`;
			}
		}
		html += '</tr>';
	}
	html += '</tbody></table></div>';

setTimeout(() => {
}, 0);

return html;
}

function getChipClass(slot) {
	const t = slot.shiftType;
	if (t === 'call_day') return 'chip-call-day';
	if (t === 'call_night') {
		const dow = new Date(slot.date + 'T00:00:00').getDay();
		return dow === 5 ? 'chip-fri-night' : 'chip-call-night';
	}
	if (t === 'call_weekend' || t === 'call_weekend_sun') return 'chip-weekend';
	if (t === 'surgical_am' || t === 'surgical_hosp_pm') return 'chip-surgical';
	if (t === 'office_late') {
		return slot.isHospital ? 'chip-hosp-office-late' : 'chip-office-late';
	}
	if (t === 'office_am') {
		return slot.isHospital ? 'chip-hosp-office-am' : 'chip-office-am';
	}
	if (t === 'office_pm') {
		return slot.isHospital ? 'chip-hosp-office-pm' : 'chip-office-pm';
	}
	return 'chip-empty';
}

function getDoctorLastName(id) {
	const d = STATE.doctors.find(doc => doc.id === id);
	if (!d) return id;
	const parts = d.name.trim().split(/\s+/);
	return parts.length > 1 ? parts[parts.length - 1] : parts[0];
}

function buildMonthlySummaryHTML(year, month, scheduleData) {
	if (!scheduleData || !scheduleData.counts) {
		return '<p class="empty-msg">No summary data for this month.</p>';
	}

	const counts = scheduleData.counts;
	const nonHosp = STATE.offices.filter(o => !o.isHospital);

	const callCols = ['Wk Day', 'Wk Night', 'Fri Night', 'Wknd'];
	const sessCols = ['Sessions', 'AM', 'PM', 'Late'];
	const officeCols = nonHosp.map(o => o.name);
	const prefCol = ['Pref Rate'];
	const allCols = [...callCols, ...sessCols, ...officeCols, ...prefCol];

	let html = '<div class="card mt-half"><div class="card-header">Monthly Summary</div>';
	html += '<div style="overflow-x:auto;padding:0.3rem">';
	html += '<table class="sheet-table summary-table"><thead><tr><th>Doctor</th>';
	for (const c of allCols) html += `<th>${escapeHtml(c)}</th>`;
	html += '</tr></thead><tbody>';

	const doctorIds = Object.keys(counts);
	for (const docId of doctorIds) {
		const c = counts[docId];
		const doc = STATE.doctors.find(d => d.id === docId);
		const name = doc ? doc.name : c.doctor_name || docId;
		const visits = c.officeVisitCounts || {};
		const prefRate = c.preferredDayCallRate;
		const prefDisplay = prefRate != null ? (prefRate * 100).toFixed(0) + '%' : '—';

		html += `<tr><td>${escapeHtml(name)}</td>`;
		html += `<td>${c.weekdayDayCalls || 0}</td>`;
		html += `<td>${c.weekdayNightCalls || 0}</td>`;
		html += `<td>${c.fridayNightCalls || 0}</td>`;
		html += `<td>${c.weekendBlocks || 0}</td>`;
		html += `<td>${c.totalSessions || 0}</td>`;
		html += `<td>${c.amSessions || 0}</td>`;
		html += `<td>${c.pmSessions || 0}</td>`;
		html += `<td>${c.lateSessions || 0}</td>`;
		for (const o of nonHosp) {
			html += `<td>${visits[o.id] || 0}</td>`;
		}
		html += `<td>${prefDisplay}</td>`;
		html += '</tr>';
	}
	html += '</tbody></table></div></div>';
	return html;
}

// escapeHtml defined in app.js

// ---- Blackout / Time Off Calendar ----

const PERIOD_LABELS = {
 all_day: 'All Day',
 morning: 'Morning',
 afternoon: 'Afternoon',
 custom: 'Custom Window'
};

function buildBlackoutGridHTML(year, month, doctorId) {
 const DAYS_IN_MONTH = new Date(year, month + 1, 0).getDate();
 const FIRST_DOW = (new Date(year, month, 1).getDay() + 6) % 7;
 const DAY_NAMES = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
 const MONTH_STR = String(month + 1).padStart(2, '0');

 const mk = getMonthKey(year, month);
 const entries = (STATE.blackouts[mk] || {})[doctorId] || [];
 const entriesByDate = {};
 for (const e of entries) {
  if (!entriesByDate[e.date]) entriesByDate[e.date] = [];
  entriesByDate[e.date].push(e);
 }

 let html = '<div class="blackout-grid">';
 for (const dn of DAY_NAMES) html += `<div class="blackout-cell header">${dn}</div>`;
 for (let i = 0; i < FIRST_DOW; i++) html += '<div class="blackout-cell"></div>';
 for (let d = 1; d <= DAYS_IN_MONTH; d++) {
  const dateStr = `${year}-${MONTH_STR}-${String(d).padStart(2, '0')}`;
  const dow = (FIRST_DOW + d - 1) % 7;
  const isWeekend = dow >= 5;
  const dateEntries = entriesByDate[dateStr] || [];
  let cls = 'blackout-cell';
  if (isWeekend) {
   cls += ' weekend';
  } else if (dateEntries.length > 0) {
   const periods = dateEntries.map(e => e.period);
   if (periods.includes('all_day')) cls += ' blocked-all';
   else if (periods.length === 2 && periods.includes('morning') && periods.includes('afternoon')) cls += ' blocked-all';
   else if (periods.includes('custom')) cls += ' blocked-custom';
   else if (periods.includes('morning')) cls += ' blocked-am';
   else if (periods.includes('afternoon')) cls += ' blocked-pm';
   else cls += ' blocked-all';
  } else {
   cls += ' free';
  }
  const handler = !isWeekend ? `onclick="handleBlackoutCellClick('${doctorId}', '${dateStr}', this, event)"` : '';
  let dotsHTML = '';
  if (!isWeekend && dateEntries.length > 0) {
   const periods = dateEntries.map(e => e.period);
   const uniquePeriods = [...new Set(periods)];
   dotsHTML = '<div class="period-dots">';
   for (const p of uniquePeriods) {
    dotsHTML += `<span class="pdot pdot-${p === 'all_day' ? 'all' : p === 'morning' ? 'am' : p === 'afternoon' ? 'pm' : 'custom'}"></span>`;
   }
   dotsHTML += '</div>';
  }
  html += `<div class="${cls}" data-date="${dateStr}" ${handler}>${d}${dotsHTML}</div>`;
 }
 html += '</div>';
 return html;
}

function buildTimeOffEntriesHTML(year, month, doctorId) {
 const mk = getMonthKey(year, month);
 const entries = (STATE.blackouts[mk] || {})[doctorId] || [];
 if (!entries.length) return '<div class="text-muted" style="font-size:0.78rem;margin-top:0.3rem;">No time off selected.</div>';
 const sorted = [...entries].sort((a, b) => a.date.localeCompare(b.date) || a.period.localeCompare(b.period));
 let html = '<div class="timeoff-entries">';
 for (const e of sorted) {
  const dotCls = e.period === 'all_day' ? 'entry-dot-all' : e.period === 'morning' ? 'entry-dot-am' : e.period === 'afternoon' ? 'entry-dot-pm' : 'entry-dot-custom';
  const dotStyle = e.period === 'all_day' ? 'background:var(--accent-red)' : e.period === 'morning' ? 'background:var(--accent-orange)' : e.period === 'afternoon' ? 'background:var(--accent-purple)' : 'background:var(--accent-teal)';
  const periodLabel = PERIOD_LABELS[e.period] || e.period;
  const customInputs = e.period === 'custom'
   ? `<input type="time" class="entry-time-input" value="${e.startTime || '09:00'}" onchange="updateCustomTimeOff('${doctorId}', '${e.date}', 'startTime', this.value)"> - <input type="time" class="entry-time-input" value="${e.endTime || '11:00'}" onchange="updateCustomTimeOff('${doctorId}', '${e.date}', 'endTime', this.value)">`
   : '';
  html += `<div class="timeoff-entry">
   <span class="entry-dot" style="${dotStyle}"></span>
   <span class="entry-date">${e.date.slice(5)}</span>
   <span class="entry-period">${periodLabel}</span>
   ${customInputs ? `<span class="entry-window">${customInputs}</span>` : ''}
   <button class="entry-remove" onclick="handleRemoveTimeOff('${doctorId}', '${e.date}', '${e.period}')">Remove</button>
  </div>`;
 }
 html += '</div>';
 return html;
}

let _activePopup = null;

function closePeriodPopup() {
 if (_activePopup) { _activePopup.remove(); _activePopup = null; }
}

function handleBlackoutCellClick(doctorId, dateStr, cellEl, event) {
 event.stopPropagation();
 closePeriodPopup();
 const mk = getMonthKeyFromStr(dateStr);
 const entries = ((STATE.blackouts[mk] || {})[doctorId] || []).filter(e => e.date === dateStr);
 const existingPeriods = entries.map(e => e.period);

 const popup = document.createElement('div');
 popup.className = 'period-popup';

 const dayNum = dateStr.slice(8);
 const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
 const mIdx = parseInt(dateStr.slice(5, 7), 10) - 1;
 popup.innerHTML = `<div class="period-popup-title">Time off ${monthNames[mIdx]} ${dayNum}</div>`;

 const periods = [
  { key: 'all_day', label: 'All Day', dotColor: 'var(--accent-red)' },
  { key: 'morning', label: 'Morning (AM)', dotColor: 'var(--accent-orange)' },
  { key: 'afternoon', label: 'Afternoon (PM)', dotColor: 'var(--accent-purple)' },
  { key: 'custom', label: 'Custom Window', dotColor: 'var(--accent-teal)' },
 ];

 for (const p of periods) {
  const isOn = existingPeriods.includes(p.key);
  const check = isOn ? '&#10003; ' : '';
  popup.innerHTML += `<button onclick="toggleTimeOffPeriod('${doctorId}', '${dateStr}', '${p.key}', this)" ${isOn ? 'style="background:var(--bg-hover)"' : ''}>
   <span class="popup-dot" style="background:${p.dotColor}"></span>
   ${check}${p.label}
  </button>`;
 }

 if (existingPeriods.length > 0) {
  popup.innerHTML += `<button class="popup-remove" onclick="handleRemoveAllTimeOffDate('${doctorId}', '${dateStr}')">Clear all for this day</button>`;
 }

 const rect = cellEl.getBoundingClientRect();
 const portal = document.getElementById('blackout-portal') || document.getElementById('blackout-portal-gen') || document.body;
 const portalRect = portal === document.body ? { top: 0, left: 0 } : portal.getBoundingClientRect();
 portal.style.position = 'relative';
 popup.style.position = 'absolute';
 popup.style.top = (rect.bottom - portalRect.top + (portal.scrollTop || 0) + 4) + 'px';
 popup.style.left = Math.max(0, rect.left - portalRect.left - 40) + 'px';
 portal.appendChild(popup);
 _activePopup = popup;
}

function toggleTimeOffPeriod(doctorId, dateStr, period) {
 const mk = getMonthKeyFromStr(dateStr);
 if (!STATE.blackouts[mk]) STATE.blackouts[mk] = {};
 if (!STATE.blackouts[mk][doctorId]) STATE.blackouts[mk][doctorId] = [];
 const entries = STATE.blackouts[mk][doctorId];
 const idx = entries.findIndex(e => e.date === dateStr && e.period === period);
 if (idx !== -1) {
  entries.splice(idx, 1);
 } else {
  const entry = { date: dateStr, period };
  if (period === 'custom') {
   entry.startTime = '09:00';
   entry.endTime = '11:00';
  }
  entries.push(entry);
 }
 if (entries.length === 0) delete STATE.blackouts[mk][doctorId];
 saveState();
 closePeriodPopup();
 refreshBlackoutCalendar();
}

function handleRemoveTimeOff(doctorId, dateStr, period) {
 const mk = getMonthKeyFromStr(dateStr);
 if (!STATE.blackouts[mk]?.[doctorId]) return;
 const entries = STATE.blackouts[mk][doctorId];
 const idx = entries.findIndex(e => e.date === dateStr && e.period === period);
 if (idx !== -1) entries.splice(idx, 1);
 if (entries.length === 0) delete STATE.blackouts[mk][doctorId];
 saveState();
 refreshBlackoutCalendar();
}

function handleRemoveAllTimeOffDate(doctorId, dateStr) {
 const mk = getMonthKeyFromStr(dateStr);
 if (!STATE.blackouts[mk]?.[doctorId]) return;
 STATE.blackouts[mk][doctorId] = STATE.blackouts[mk][doctorId].filter(e => e.date !== dateStr);
 if (STATE.blackouts[mk][doctorId].length === 0) delete STATE.blackouts[mk][doctorId];
 saveState();
 closePeriodPopup();
 refreshBlackoutCalendar();
}

function updateCustomTimeOff(doctorId, dateStr, field, value) {
 const mk = getMonthKeyFromStr(dateStr);
 const entries = STATE.blackouts[mk]?.[doctorId];
 if (!entries) return;
 const entry = entries.find(e => e.date === dateStr && e.period === 'custom');
 if (entry) {
  entry[field] = value;
  saveState();
 }
}

function getMonthKeyFromStr(dateStr) {
 const [y, m] = dateStr.split('-').map(Number);
 return getMonthKey(y, m - 1);
}

function refreshBlackoutCalendar() {
 closePeriodPopup();
 const { year, month } = getBlackoutYearMonth();

 const cal = document.getElementById('blackout-calendar');
 const sel = document.getElementById('blackout-doctor-select');
 const doctorId = sel?.value;
 if (cal && doctorId) {
  cal.innerHTML = buildBlackoutGridHTML(year, month, doctorId);
  const entriesEl = document.getElementById('blackout-entries');
  if (entriesEl) entriesEl.innerHTML = buildTimeOffEntriesHTML(year, month, doctorId);
 }

 const cal2 = document.getElementById('blackout-calendar-gen');
 const sel2 = document.getElementById('blackout-doctor-select-gen');
 const doctorId2 = sel2?.value;
 if (cal2 && doctorId2) {
  cal2.innerHTML = buildBlackoutGridHTML(year, month, doctorId2);
  const entriesEl2 = document.getElementById('blackout-entries-gen');
  if (entriesEl2) entriesEl2.innerHTML = buildTimeOffEntriesHTML(year, month, doctorId2);
 }
}

document.addEventListener('click', function(e) {
 if (_activePopup && !_activePopup.contains(e.target)) {
  closePeriodPopup();
 }
});
