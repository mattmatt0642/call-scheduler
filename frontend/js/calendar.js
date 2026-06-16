/* =========================
Calendar → Spreadsheet View
========================= */

function buildCalendarHTML(year, month, scheduleData) {
  const DAYS_IN_MONTH = new Date(year, month + 1, 0).getDate();
  const FIRST_DOW = (new Date(year, month, 1).getDay() + 6) % 7;
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

  const shiftRows = [
    { key: 'call_day', label: 'Call Day' },
    { key: 'call_night', label: 'Call Night' },
    { key: 'call_weekend', label: 'Wknd Sat' },
    { key: 'call_weekend_sun', label: 'Wknd Sun' },
    { key: 'surgical_am', label: 'Surg AM' },
    { key: 'surgical_hosp_pm', label: 'Surg PM' },
  ];
  if (hospId) {
    shiftRows.push({ key: `${hospId}_am`, label: `${hospName} AM` });
    shiftRows.push({ key: `${hospId}_pm`, label: `${hospName} PM` });
  }
  for (const o of nonHosp) {
    shiftRows.push({ key: `${o.id}_am`, label: `${o.name} AM` });
    shiftRows.push({ key: `${o.id}_pm`, label: `${o.name} PM` });
    shiftRows.push({ key: `${o.id}_late`, label: `${o.name} Late` });
  }

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

  const weeks = [];
  let currentWeek = [];
  for (let i = 0; i < FIRST_DOW; i++) currentWeek.push(null);
  for (let d = 1; d <= DAYS_IN_MONTH; d++) {
    currentWeek.push(d);
    if (currentWeek.length === 7) {
      weeks.push(currentWeek);
      currentWeek = [];
    }
  }
  if (currentWeek.length > 0) {
    while (currentWeek.length < 7) currentWeek.push(null);
    weeks.push(currentWeek);
  }

  const MONTH_NAMES = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const MONTH_ABBREV = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  const isCurrentMonth = (today.getFullYear() === year && today.getMonth() === month);

  function weekLabel(week) {
    const weekStart = week.find(d => d !== null);
    const weekEnd = [...week].reverse().find(d => d !== null);
    return weekStart ? `${MONTH_ABBREV[month]} ${weekStart}${weekEnd !== weekStart ? '–' + weekEnd : ''}` : '';
  }

  function colClasses(col, dayNum) {
    const cls = [];
    if (col >= 5) cls.push('weekend-col');
    if (isCurrentMonth && dayNum) {
      const cellDateStr = `${year}-${MONTH_STR}-${String(dayNum).padStart(2, '0')}`;
      if (cellDateStr === todayStr) cls.push('today-col');
    }
    return cls;
  }

  function renderWeekDayHeaders(week, isSecond) {
    let h = '';
    for (let col = 0; col < 7; col++) {
      const dayNum = week[col];
      const cls = colClasses(col, dayNum);
      if (isSecond && col === 0) cls.push('week-divider-col');
      const dateLabel = dayNum ? `<span class="th-date">${dayNum}</span>` : '';
      h += `<th class="${cls.join(' ')}"><span class="th-day">${DAY_NAMES[col]}</span>${dateLabel}</th>`;
    }
    return h;
  }

  function renderWeekBodyRow(row, week, isSecond) {
    let h = '';
    for (let col = 0; col < 7; col++) {
      const dayNum = week[col];
      const cls = colClasses(col, dayNum);
      if (isSecond && col === 0) cls.push('week-divider-col');
      const clsAttr = cls.length ? ` class="${cls.join(' ')}"` : '';
      if (!dayNum) {
        h += `<td${clsAttr}></td>`;
        continue;
      }
      const cell = dayData[dayNum].slots[row.key];
      if (cell) {
        h += `<td${clsAttr}><div class="chip ${cell.chip}">${cell.doc}</div></td>`;
      } else {
        h += `<td${clsAttr}><span class="chip chip-empty">·</span></td>`;
      }
    }
    return h;
  }

  function renderSingleWeekBlock(week) {
    const label = weekLabel(week);
    let h = `<div class="schedule-week-block">`;
    h += `<div class="week-block-header"><span>${label}</span></div>`;
    h += `<div class="week-block-scroll"><table class="sheet-table">`;
    h += '<thead><tr><th>Shift</th>';
    h += renderWeekDayHeaders(week, false);
    h += '</tr></thead>';
    h += '<tbody>';
    for (const row of shiftRows) {
      h += '<tr>';
      h += `<td>${row.label}</td>`;
      h += renderWeekBodyRow(row, week, false);
      h += '</tr>';
    }
    h += '</tbody></table></div></div>';
    return h;
  }

  let html = '';
  for (let wi = 0; wi < weeks.length; wi += 2) {
    const week1 = weeks[wi];
    const week2 = weeks[wi + 1];

    if (!week2) {
      html += renderSingleWeekBlock(week1);
      continue;
    }

    const label1 = weekLabel(week1);
    const label2 = weekLabel(week2);

    html += `<div class="schedule-week-block schedule-week-pair">`;
    html += `<div class="week-block-header week-pair-header"><span>${label1}</span><span class="week-pair-sep"></span><span>${label2}</span></div>`;
    html += `<div class="week-block-scroll"><table class="sheet-table sheet-table-pair">`;

    html += '<thead>';
    html += `<tr><th rowspan="2">Shift</th>`;
    html += `<th colspan="7" class="week-header-left">${label1}</th>`;
    html += `<th colspan="7" class="week-header-right week-divider-col">${label2}</th>`;
    html += '</tr><tr>';
    html += renderWeekDayHeaders(week1, false);
    html += renderWeekDayHeaders(week2, true);
    html += '</tr></thead>';

    html += '<tbody>';
    for (const row of shiftRows) {
      html += '<tr>';
      html += `<td>${row.label}</td>`;
      html += renderWeekBodyRow(row, week1, false);
      html += renderWeekBodyRow(row, week2, true);
      html += '</tr>';
    }
    html += '</tbody></table></div></div>';
  }

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

 let html = '<div class="blackout-grid" data-doctor-id="' + escapeHtml(doctorId) + '">';
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
  const clickable = !isWeekend ? ' role="button" tabindex="0"' : '';
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
  html += `<div class="${cls}" data-date="${dateStr}"${clickable}>${d}${dotsHTML}</div>`;
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
  const portal = document.getElementById('blackout-portal') || document.body;
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
}

document.addEventListener('click', function(e) {
  if (_activePopup && !_activePopup.contains(e.target)) {
    closePeriodPopup();
  }
});

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape' && _activePopup) {
    closePeriodPopup();
  }
});
