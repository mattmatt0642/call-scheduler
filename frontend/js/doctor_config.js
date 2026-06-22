/* =========================
Doctor Config — Clean Card Layout
Everything important visible at a glance; advanced fields collapsed
========================= */

function renderDoctorAccordion() {
  const container = document.getElementById('doctor-accordion');
  if (!container) return;

  const mainEl = document.querySelector('main');
  const prevScrollTop = mainEl ? mainEl.scrollTop : 0;
  const prevScrollLeft = mainEl ? mainEl.scrollLeft : 0;

  const openAdvIds = Array.from(container.querySelectorAll('.advanced-body.open'))
    .map(el => el.id)
    .filter(id => id);

  const openTimeOffIds = Array.from(container.querySelectorAll('.timeoff-body.open'))
    .map(el => el.id)
    .filter(id => id);

  if (!STATE.doctors.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">+</div><div class="empty-state-title">No doctors to configure</div><div class="empty-state-desc">Add doctors in the Setup tab first.</div></div>';
    if (mainEl) { mainEl.scrollTop = prevScrollTop; mainEl.scrollLeft = prevScrollLeft; }
    return;
  }

  container.innerHTML = STATE.doctors.map(doc => buildDocCard(doc)).join('');

  openAdvIds.forEach(id => {
    const body = document.getElementById(id);
    if (body) {
      body.classList.add('open');
      const btn = body.previousElementSibling;
      if (btn) {
        const arrow = btn.querySelector('.advanced-arrow');
        if (arrow) arrow.innerHTML = '&#9660;';
      }
    }
  });

  openTimeOffIds.forEach(id => {
    const body = document.getElementById(id);
    if (body) {
      body.classList.add('open');
      const btn = body.previousElementSibling;
      if (btn) {
        const arrow = btn.querySelector('.toggle-arrow');
        if (arrow) arrow.innerHTML = '&#9660;';
      }
      renderDocTimeOffCalendar(body);
    }
  });

  if (mainEl) { mainEl.scrollTop = prevScrollTop; mainEl.scrollLeft = prevScrollLeft; }
}

function buildDocCard(doc) {
  const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];

  const offChecks = dayNames.map((d, i) => {
    const checked = doc.standingDaysOff?.includes(i) ? 'checked' : '';
    return `<label class="day-chip ${checked ? 'active' : ''}"><input type="checkbox" ${checked} onchange="toggleDayOff('${doc.id}', ${i}, this.checked, 'standingDaysOff'); this.parentElement.classList.toggle('active', this.checked)"/>${d}</label>`;
  }).join('');

  const prefChecks = weekdayNames.map((d, i) => {
    const checked = doc.preferredCallDays?.includes(i) ? 'checked' : '';
    return `<label class="day-chip pref ${checked ? 'active' : ''}"><input type="checkbox" ${checked} onchange="toggleDayOff('${doc.id}', ${i}, this.checked, 'preferredCallDays'); this.parentElement.classList.toggle('active', this.checked)"/>${d}</label>`;
  }).join('');

  const nonHosp = STATE.offices.filter(o => !o.isHospital);
  const isAllowedAll = !doc.allowedOffices;
  const allowedChecks = nonHosp.length
    ? nonHosp.map(o => {
        const checked = isAllowedAll || doc.allowedOffices?.includes(o.id) ? 'checked' : '';
        return `<label class="day-chip off ${checked ? 'active' : ''}"><input type="checkbox" ${checked} onchange="toggleOfficeAccess('${doc.id}', '${o.id}', this.checked); this.parentElement.classList.toggle('active', this.checked)"/>${escapeHtml(o.name)}</label>`;
      }).join('')
    : '<span class="text-sm text-muted">No non-hospital offices defined</span>';

  const advancedId = 'adv-' + doc.id;
  const officePrefs = buildOfficePreferenceList(doc);
  const prefDropdowns = buildPreferenceDropdowns(doc);
  const fixedRows = buildFixedRecurringRows(doc);
  const overrideRows = buildOneTimeOverrideRows(doc);

  return `<div class="doc-item fade-in-item" data-doc-id="${doc.id}">
  <div class="doc-card">
    <div class="doc-card-top">
      <div class="doc-card-name-row">
        <input type="text" class="doc-name-input" value="${escapeHtml(doc.name)}" onchange="updateDocField('${doc.id}', 'name', this.value)"/>
        <button class="btn btn-sm btn-danger" onclick="removeDoctor('${doc.id}')">Remove</button>
      </div>
      <div class="doc-card-toggles">
        <label class="toggle-label"><span class="toggle-text">Hospital Call</span>
          <div class="toggle-switch"><input type="checkbox" ${doc.hospitalCallEligible ? 'checked' : ''} onchange="updateDocField('${doc.id}', 'hospitalCallEligible', this.checked)"/><span class="toggle-slider"></span></div>
        </label>
      <label class="toggle-label"><span class="toggle-text">Surgical Assist</span>
      <div class="toggle-switch"><input type="checkbox" ${doc.surgicalAssistEligible ? 'checked' : ''} onchange="updateDocField('${doc.id}', 'surgicalAssistEligible', this.checked)"/><span class="toggle-slider"></span></div>
      </label>
      <label class="toggle-label"><span class="toggle-text">No Wknd Call</span>
      <div class="toggle-switch"><input type="checkbox" ${doc.weekendCallOff ? 'checked' : ''} onchange="updateDocField('${doc.id}', 'weekendCallOff', this.checked)"/><span class="toggle-slider"></span></div>
      </label>
      <label class="toggle-label"><span class="toggle-text">Pair Weekends</span>
      <div class="toggle-switch"><input type="checkbox" ${doc.weekendPairingPreference ? 'checked' : ''} onchange="updateDocField('${doc.id}', 'weekendPairingPreference', this.checked)"/><span class="toggle-slider"></span></div>
      </label>
      </div>
    </div>

    <div class="doc-card-section">
      <h4 class="doc-card-label">Standing Days Off</h4>
      <div class="day-chips-row">${offChecks}</div>
    </div>

    <div class="doc-card-section">
      <h4 class="doc-card-label">Preferred Call Days</h4>
      <div class="day-chips-row">${prefChecks}</div>
      <div class="form-note">Friday affects day calls only — Fri night is always balance-only.</div>
    </div>

    <div class="doc-card-section">
      <h4 class="doc-card-label">Call Limits</h4>
      <div class="limits-row">
  <div class="limit-item"><label>Max Weekday Day</label><input type="number" min="0" value="${doc.maxWeekdayDayCalls}" onchange="updateDocField('${doc.id}', 'maxWeekdayDayCalls', Math.max(0, parseInt(this.value)||0))"/></div>
  <div class="limit-item"><label>Max Weekday Night</label><input type="number" min="0" value="${doc.maxWeekdayNightCalls}" onchange="updateDocField('${doc.id}', 'maxWeekdayNightCalls', Math.max(0, parseInt(this.value)||0))"/></div>
  <div class="limit-item"><label>Max Friday Night</label><input type="number" min="0" value="${doc.maxFridayNightCalls}" onchange="updateDocField('${doc.id}', 'maxFridayNightCalls', Math.max(0, parseInt(this.value)||0))"/></div>
  <div class="limit-item"><label>Max Weekend Blocks</label><input type="number" min="0" value="${doc.maxWeekendBlocks}" onchange="updateDocField('${doc.id}', 'maxWeekendBlocks', Math.max(0, parseInt(this.value)||0))"/></div>
  <div class="limit-item"><label>Sessions Per Week</label><input type="number" min="0" max="10" value="${doc.requiredSessionsPerWeek}" onchange="updateDocField('${doc.id}', 'requiredSessionsPerWeek', Math.min(10, Math.max(0, parseInt(this.value)||0)))"/></div>
      </div>
    </div>

    <div class="doc-card-section">
      <h4 class="doc-card-label">Allowed Offices</h4>
      <div class="day-chips-row">${allowedChecks}</div>
    </div>

    <div class="doc-card-section timeoff-section">
      <button class="timeoff-toggle" onclick="toggleTimeOff('toff-${doc.id}', this)">
        <h4 class="doc-card-label" style="margin:0">Time Off <span class="toggle-arrow">&#9654;</span></h4>
      </button>
      <div id="toff-${doc.id}" class="timeoff-body" data-doctor-id="${doc.id}">
      </div>
    </div>

    <div class="doc-card-advanced">
      <button class="advanced-toggle" onclick="toggleAdvanced('${advancedId}', this)">
        <span class="advanced-arrow">&#9654;</span> Advanced Settings
      </button>
      <div id="${advancedId}" class="advanced-body">
        <div class="doc-card-section">
          <h4 class="doc-card-label">Office Preferences <span class="form-note-inline">(drag to reorder — top = highest priority)</span></h4>
          ${officePrefs}
        </div>
        <div class="doc-card-section">
          <h4 class="doc-card-label">Preferences</h4>
          ${prefDropdowns}
        </div>
        <div class="doc-card-section">
          <h4 class="doc-card-label">Fixed Recurring Assignments</h4>
          ${fixedRows}
          <button class="btn btn-sm mt-half" onclick="addFixedRecurring('${doc.id}')">+ Add Recurring</button>
        </div>
        <div class="doc-card-section">
          <h4 class="doc-card-label">One-Time Overrides</h4>
          ${overrideRows}
          <button class="btn btn-sm mt-half" onclick="addOneTimeOverride('${doc.id}')">+ Add Override</button>
        </div>
      </div>
    </div>
  </div>
</div>`;
}

function toggleAdvanced(id, btn) {
  const body = document.getElementById(id);
  if (!body) return;
  const open = body.classList.toggle('open');
  const arrow = btn.querySelector('.advanced-arrow');
  if (arrow) arrow.innerHTML = open ? '&#9660;' : '&#9654;';
}

function buildOfficePreferenceList(doc) {
  if (!STATE.offices.length) return '<span class="text-muted">Add offices in Setup first.</span>';
  const prefs = doc.officePreferences || [];
  const ranked = prefs.filter(id => STATE.offices.some(o => o.id === id));
  const unranked = STATE.offices.filter(o => !ranked.includes(o.id));
  const items = [...ranked.map(id => STATE.offices.find(o => o.id === id)), ...unranked];

  let html = '<div class="office-pref-list" data-doc-id="' + doc.id + '">';
  items.forEach((o, i) => {
    const isRanked = ranked.includes(o.id);
    html += `<div class="office-pref-item" data-office-id="${o.id}" draggable="true"
      ondragstart="officePrefDragStart(event, '${doc.id}', '${o.id}')"
      ondragover="officePrefDragOver(event)"
      ondrop="officePrefDrop(event, '${doc.id}', '${o.id}')">
      <span class="office-pref-handle">⠿</span>
      <span class="office-pref-rank">${isRanked ? ranked.indexOf(o.id) + 1 : '—'}</span>
      <span class="office-pref-name">${escapeHtml(o.name)}</span>
      ${o.isHospital ? '<span class="office-pref-badge">Hosp</span>' : ''}
    </div>`;
  });
  html += '</div>';
  return html;
}

function buildPreferenceDropdowns(doc) {
  const postCallOpts = [
    { value: 'no_preference', label: 'No Preference' },
    { value: 'hospital_next_day', label: 'Hospital Next Day' },
    { value: 'off_next_day', label: 'Off Next Day' },
  ];
  const callShiftOpts = [
    { value: 'no_preference', label: 'No Preference' },
    { value: 'prefer_single', label: 'Prefer Single' },
    { value: 'prefer_double', label: 'Prefer Double' },
  ];
  const dayNightOpts = [
    { value: 'balanced', label: 'Balanced' },
    { value: 'prefer_day', label: 'Prefer Day' },
    { value: 'prefer_night', label: 'Prefer Night' },
  ];
  const amPmOpts = [
    { value: 'balanced', label: 'Balanced' },
    { value: 'prefer_am', label: 'Prefer AM' },
    { value: 'prefer_pm', label: 'Prefer PM' },
  ];

  function sel(opts, val) {
    return opts.map(o => `<option value="${o.value}" ${doc[val] === o.value ? 'selected' : ''}>${o.label}</option>`).join('');
  }

  return `<div class="pref-grid">
  <div class="form-row">
    <label>Post-Call Preference</label>
    <select onchange="updateDocField('${doc.id}', 'postCallPreference', this.value)">${sel(postCallOpts, 'postCallPreference')}</select>
  </div>
  <div class="form-row">
    <label>Call Shift Preference</label>
    <select onchange="updateDocField('${doc.id}', 'callShiftPreference', this.value)">${sel(callShiftOpts, 'callShiftPreference')}</select>
  </div>
  <div class="form-row">
    <label>Day/Night Preference</label>
    <select onchange="updateDocField('${doc.id}', 'dayNightPreference', this.value)">${sel(dayNightOpts, 'dayNightPreference')}</select>
  </div>
  <div class="form-row">
    <label>AM/PM Preference</label>
    <select onchange="updateDocField('${doc.id}', 'amPmPreference', this.value)">${sel(amPmOpts, 'amPmPreference')}</select>
  </div>
</div>`;
}

function buildFixedRecurringRows(doc) {
  const items = doc.fixedRecurring || [];
  if (!items.length) return '<p class="mini-empty-note">No recurring assignments yet. Click the button below to add one.</p>';

  const dayOpts = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((d, i) =>
    `<option value="${i}">${d}</option>`
  ).join('');
  const shiftOpts = ['office_am','office_pm','office_late'].map(s =>
    `<option value="${s}">${s.replace('office_', '').toUpperCase()}</option>`
  ).join('');
  const officeOpts = STATE.offices.map(o =>
    `<option value="${o.id}">${escapeHtml(o.name)}</option>`
  ).join('');

  let html = '<table class="mini-table"><thead><tr><th>Day</th><th>Office</th><th>Shift</th><th></th></tr></thead><tbody>';
  items.forEach((item, idx) => {
    html += `<tr>
  <td><select onchange="updateFixedRecurring('${doc.id}', ${idx}, 'dayOfWeek', parseInt(this.value))">
    ${dayOpts.replace(`value="${item.dayOfWeek}"`, `value="${item.dayOfWeek}" selected`)}
  </select></td>
  <td><select onchange="updateFixedRecurring('${doc.id}', ${idx}, 'officeId', this.value)">
    ${officeOpts.replace(`value="${item.officeId}"`, `value="${item.officeId}" selected`)}
  </select></td>
  <td><select onchange="updateFixedRecurring('${doc.id}', ${idx}, 'shiftType', this.value)">
    ${shiftOpts.replace(`value="${item.shiftType}"`, `value="${item.shiftType}" selected`)}
  </select></td>
  <td><button class="btn btn-sm btn-danger" onclick="removeFixedRecurring('${doc.id}', ${idx})">Remove</button></td>
</tr>`;
  });
  html += '</tbody></table>';
  return html;
}

function buildOneTimeOverrideRows(doc) {
  const items = doc.oneTimeOverrides || [];
  if (!items.length) return '<p class="mini-empty-note">No one-time overrides yet. Click the button below to add one.</p>';

  const shiftOpts = ['office_am','office_pm','office_late','call_day','call_night'].map(s =>
    `<option value="${s}">${s.replace(/^(office_|call_)/, '').toUpperCase()}</option>`
  ).join('');
  const officeOpts = STATE.offices.map(o =>
    `<option value="${o.id}">${escapeHtml(o.name)}</option>`
  ).join('');

  let html = '<table class="mini-table"><thead><tr><th>Date</th><th>Office</th><th>Shift</th><th></th></tr></thead><tbody>';
  items.forEach((item, idx) => {
    html += `<tr>
  <td><input type="date" value="${item.date || ''}" onchange="updateOneTimeOverride('${doc.id}', ${idx}, 'date', this.value)"/></td>
  <td><select onchange="updateOneTimeOverride('${doc.id}', ${idx}, 'officeId', this.value)">
    ${officeOpts.replace(`value="${item.officeId}"`, `value="${item.officeId}" selected`)}
  </select></td>
  <td><select onchange="updateOneTimeOverride('${doc.id}', ${idx}, 'shiftType', this.value)">
    ${shiftOpts.replace(`value="${item.shiftType}"`, `value="${item.shiftType}" selected`)}
  </select></td>
  <td><button class="btn btn-sm btn-danger" onclick="removeOneTimeOverride('${doc.id}', ${idx})">Remove</button></td>
</tr>`;
  });
  html += '</tbody></table>';
  return html;
}

function toggleDocItem(header) {
  header.parentElement.classList.toggle('open');
  const icon = header.querySelector('.toggle-icon');
  if (icon) icon.textContent = header.parentElement.classList.contains('open') ? '▼' : '▶';
}

function updateDocField(docId, field, value) {
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc) return;
  doc[field] = value;
  saveState();
  if (field === 'name') {
    const input = document.querySelector(`.doc-item[data-doc-id="${docId}"] .doc-name-input`);
    if (input) input.value = value;
  }
}

function toggleDayOff(docId, dayIndex, checked, field) {
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc) return;
  if (!doc[field]) doc[field] = [];
  const arr = doc[field];
  if (checked) {
    if (!arr.includes(dayIndex)) arr.push(dayIndex);
  } else {
    doc[field] = arr.filter(v => v !== dayIndex);
  }
  saveState();
}

function toggleOfficeAccess(docId, officeId, checked) {
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc) return;
  const nonHospIds = STATE.offices.filter(o => !o.isHospital).map(o => o.id);
  if (!doc.allowedOffices) doc.allowedOffices = [...nonHospIds];
  if (checked) {
    if (!doc.allowedOffices.includes(officeId)) doc.allowedOffices.push(officeId);
  } else {
    doc.allowedOffices = doc.allowedOffices.filter(id => id !== officeId);
  }
  if (doc.allowedOffices.length === nonHospIds.length) doc.allowedOffices = null;
  saveState();
}

function addFixedRecurring(docId) {
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc) return;
  if (!doc.fixedRecurring) doc.fixedRecurring = [];
  doc.fixedRecurring.push({ dayOfWeek: 0, officeId: STATE.offices[0]?.id || '', shiftType: 'office_am' });
  saveState();
  renderDoctorAccordion();
  reopenDocItem(docId);
}

function removeFixedRecurring(docId, idx) {
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc || !doc.fixedRecurring) return;
  doc.fixedRecurring.splice(idx, 1);
  saveState();
  renderDoctorAccordion();
  reopenDocItem(docId);
}

function updateFixedRecurring(docId, idx, field, value) {
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc || !doc.fixedRecurring || !doc.fixedRecurring[idx]) return;
  doc.fixedRecurring[idx][field] = value;
  saveState();
}

function addOneTimeOverride(docId) {
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc) return;
  if (!doc.oneTimeOverrides) doc.oneTimeOverrides = [];
  doc.oneTimeOverrides.push({ date: '', officeId: STATE.offices[0]?.id || '', shiftType: 'office_am' });
  saveState();
  renderDoctorAccordion();
  reopenDocItem(docId);
}

function removeOneTimeOverride(docId, idx) {
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc || !doc.oneTimeOverrides) return;
  doc.oneTimeOverrides.splice(idx, 1);
  saveState();
  renderDoctorAccordion();
  reopenDocItem(docId);
}

function updateOneTimeOverride(docId, idx, field, value) {
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc || !doc.oneTimeOverrides || !doc.oneTimeOverrides[idx]) return;
  doc.oneTimeOverrides[idx][field] = value;
  saveState();
}

function reopenDocItem(docId) {
  const advBody = document.getElementById('adv-' + docId);
  if (advBody) {
    advBody.classList.add('open');
    const btn = advBody.previousElementSibling;
    if (btn) {
      const arrow = btn.querySelector('.advanced-arrow');
      if (arrow) arrow.innerHTML = '&#9660;';
    }
  }
}

let _dragDocId = null;
let _dragOfficeId = null;

function officePrefDragStart(e, docId, officeId) {
  _dragDocId = docId;
  _dragOfficeId = officeId;
  e.dataTransfer.effectAllowed = 'move';
  e.target.style.opacity = '0.4';
}

function officePrefDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
}

function officePrefDrop(e, docId, targetOfficeId) {
  e.preventDefault();
  if (_dragDocId !== docId || !_dragOfficeId || _dragOfficeId === targetOfficeId) return;
  const doc = STATE.doctors.find(d => d.id === docId);
  if (!doc) return;
  if (!doc.officePreferences) doc.officePreferences = [];

  const prefs = [...doc.officePreferences];
  const srcIdx = prefs.indexOf(_dragOfficeId);
  const tgtIdx = prefs.indexOf(targetOfficeId);

  if (srcIdx !== -1) {
    prefs.splice(srcIdx, 1);
  } else {
    prefs.push(_dragOfficeId);
  }

  const newTgtIdx = prefs.indexOf(targetOfficeId);
  if (newTgtIdx !== -1) {
    prefs.splice(newTgtIdx, 0, _dragOfficeId);
  } else {
    prefs.push(_dragOfficeId);
  }

  doc.officePreferences = prefs;
  saveState();
  renderDoctorAccordion();
  reopenDocItem(docId);
  _dragDocId = null;
  _dragOfficeId = null;
}

function toggleTimeOff(id, btn) {
  const body = document.getElementById(id);
  if (!body) return;
  const open = body.classList.toggle('open');
  const arrow = btn.querySelector('.toggle-arrow');
  if (arrow) arrow.innerHTML = open ? '&#9660;' : '&#9654;';
  if (open) renderDocTimeOffCalendar(body);
}

function renderDocTimeOffCalendar(bodyEl) {
  if (!bodyEl) return;
  const doctorId = bodyEl.dataset.doctorId;
  if (!doctorId) return;
  const { year, month } = getBlackoutYearMonth();
  bodyEl.innerHTML = `
    <div id="doc-bo-cal-${doctorId}" class="blackout-calendar-container"></div>
    <div id="doc-bo-portal-${doctorId}" class="doc-bo-portal" style="position:relative"></div>
    <div class="blackout-legend">
      <span><span class="legend-dot legend-dot-all"></span> All Day</span>
      <span><span class="legend-dot legend-dot-am"></span> Morning</span>
      <span><span class="legend-dot legend-dot-pm"></span> Afternoon</span>
      <span><span class="legend-dot legend-dot-custom"></span> Custom</span>
    </div>
    <div id="doc-bo-entries-${doctorId}"></div>`;
  const calEl = document.getElementById('doc-bo-cal-' + doctorId);
  const entriesEl = document.getElementById('doc-bo-entries-' + doctorId);
  if (calEl) calEl.innerHTML = buildBlackoutGridHTML(year, month, doctorId);
  if (entriesEl) entriesEl.innerHTML = buildTimeOffEntriesHTML(year, month, doctorId);
}

function refreshAllDocTimeOffCalendars() {
  document.querySelectorAll('.timeoff-body.open').forEach(body => {
    renderDocTimeOffCalendar(body);
  });
}
