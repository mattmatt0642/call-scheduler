/* =========================
   App Controller — Wizard-first design
   ========================= */

const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
let currentScheduleYear = new Date().getFullYear();
let currentScheduleMonth = new Date().getMonth();
let wizardStep = 1;

// ── Wizard ──────────────────────────────────────────────────────────────────

function showWizardStep(step) {
  wizardStep = step;
  const setupPane = document.getElementById('tab-setup');
  if (setupPane && !setupPane.classList.contains('active')) {
    switchTab('setup');
  }
  document.querySelectorAll('.wizard-step').forEach(ws => ws.classList.add('hidden'));
  const target = document.getElementById('wstep-' + step);
  if (target) target.classList.remove('hidden');

  document.querySelectorAll('.step-dot').forEach(dot => {
    const s = parseInt(dot.dataset.step);
    dot.classList.remove('active', 'done');
    dot.textContent = s;
    if (s === step) dot.classList.add('active');
    else if (s < step) { dot.classList.add('done'); dot.innerHTML = '&#10003;'; }
  });

  renderQuickSetupSummary();
  renderWizardDoctors();
  renderWizardOffices();
  updateWizardSummary();
  if (step === 4) updateBlackoutDoctorSelect();
  if (step === 4) refreshBlackoutCalendar();
}

function wizardNext() {
  if (wizardStep < 4) { showWizardStep(wizardStep + 1); return; }
  showWizSchedulePreview();
}

function wizardPrev() {
	if (wizardStep > 1) showWizardStep(wizardStep - 1);
}

function showWizSchedulePreview() {
  const preview = document.getElementById('wiz-schedule-preview');
  if (!preview) return;
  preview.classList.remove('hidden');
  const mk = getMonthKey(currentScheduleYear, currentScheduleMonth);
  const data = STATE.schedules[mk];
  if (data) {
    const container = document.getElementById('wiz-calendar-container');
    if (container) container.innerHTML = buildCalendarHTML(currentScheduleYear, currentScheduleMonth, data);
    updateWizScheduleDisplay(data);
  }
  preview.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updateWizScheduleDisplay(data) {
  const label = document.getElementById('wiz-sched-month-label');
  const navLabel = document.getElementById('wiz-sched-nav-label');
  if (label) label.textContent = `${MONTHS[currentScheduleMonth]} ${currentScheduleYear}`;
  if (navLabel) navLabel.textContent = `${MONTHS[currentScheduleMonth].slice(0, 3)} ${currentScheduleYear}`;

  const statusEl = document.getElementById('wiz-sched-solver-status');
  const callGiniEl = document.getElementById('wiz-sched-call-gini');
  const sessGiniEl = document.getElementById('wiz-sched-session-gini');

  if (statusEl) {
    let statusText = data?.solverStatus || '—';
    if (statusText === 'optimal') statusText = 'Optimal';
    else if (statusText === 'not_solved') statusText = 'Not solved';
    else if (data?.partial) statusText = 'Partial';
    statusEl.textContent = statusText;
    statusEl.className = 'stat-val' + (data?.partial ? ' val-warn' : data?.solverStatus === 'optimal' ? ' val-ok' : '');
  }
  if (callGiniEl) {
    const v = data?.giniCalls;
    callGiniEl.textContent = v != null ? (v <= 0.10 ? 'Fair' : 'Uneven') : '—';
    callGiniEl.className = 'stat-val' + (v > 0.10 ? ' val-warn' : v != null ? ' val-ok' : '');
  }
  if (sessGiniEl) {
    const v = data?.giniSessions;
    sessGiniEl.textContent = v != null ? (v <= 0.10 ? 'Fair' : 'Uneven') : '—';
    sessGiniEl.className = 'stat-val' + (v > 0.10 ? ' val-warn' : v != null ? ' val-ok' : '');
  }
}

function changeWizScheduleMonth(delta) {
  currentScheduleMonth += delta;
  if (currentScheduleMonth > 11) { currentScheduleMonth = 0; currentScheduleYear++; }
  if (currentScheduleMonth < 0) { currentScheduleMonth = 11; currentScheduleYear--; }
  showWizSchedulePreview();
}

function updateWizardSummary() {
  const el = document.getElementById('wiz-summary');
  if (!el) return;
  const n = STATE.doctors.length;
  const o = STATE.offices.length;
  const h = STATE.offices.filter(x => x.isHospital).length;
  if (n === 0 && o === 0) {
    el.innerHTML = '<div class="text-muted text-sm">Add doctors and offices to see a summary.</div>';
    return;
  }
  el.innerHTML = `<div class="summary-grid">
  <div class="summary-row">
    <span class="summary-label">Doctors</span>
    <span class="summary-value">${n}</span>
  </div>
  <div class="summary-row">
    <span class="summary-label">Offices</span>
    <span class="summary-value">${o} ${h ? '(' + h + ' hospital)' : ''}</span>
  </div>
  <div class="summary-row">
    <span class="summary-label">Hospital-call eligible</span>
    <span class="summary-value">${STATE.doctors.filter(d => d.hospitalCallEligible).length}</span>
  </div>
  <div class="summary-row">
    <span class="summary-label">Surgical assist</span>
    <span class="summary-value">${STATE.doctors.filter(d => d.surgicalAssistEligible).length}</span>
  </div>
</div>`;
}

function renderQuickSetupSummary() {
  const el = document.getElementById('quick-setup-content');
  if (!el) return;
  const n = STATE.doctors.length;
  const o = STATE.offices.length;
  const h = STATE.offices.filter(x => x.isHospital).length;

  const docCountHtml = n > 0
    ? `<span class="quick-setup-count">${n}</span>`
    : `<span class="quick-setup-empty">None yet</span>`;
  const offCountHtml = o > 0
    ? `<span class="quick-setup-count">${o} ${h ? '(' + h + ' hospital)' : ''}</span>`
    : `<span class="quick-setup-empty">None yet</span>`;

  el.innerHTML = `
  <div class="quick-setup-row">
    <span class="quick-setup-label">Doctors</span>
    <div class="flex-row">${docCountHtml}<button class="btn btn-sm btn-ghost" onclick="addDoctor()">+ Add</button><button class="btn btn-sm btn-ghost" onclick="showWizardStep(2)">Edit</button></div>
  </div>
  <div class="quick-setup-row">
    <span class="quick-setup-label">Offices</span>
    <div class="flex-row">${offCountHtml}<button class="btn btn-sm btn-ghost" onclick="addOffice()">+ Add</button><button class="btn btn-sm btn-ghost" onclick="showWizardStep(3)">Edit</button></div>
  </div>`;
}

// ── Wizard doctor / office lists ────────────────────────────────────────────

function renderWizardDoctors() {
  const el = document.getElementById('wiz-doctors-list');
  if (!el) { console.warn('[renderWizardDoctors] #wiz-doctors-list not found'); return; }
  let html = '<div class="quick-add"><input type="text" id="quick-add-doctor-name" placeholder="Doctor name" onkeydown="if(event.key===\'Enter\')quickAddDoctor()"/><button class="btn btn-primary btn-sm" onclick="quickAddDoctor()">+ Add Doctor</button></div>';
  if (!STATE.doctors.length) {
    html += '<div class="empty-state"><div class="empty-state-icon">+</div><div class="empty-state-title">No doctors yet</div><div class="empty-state-desc">Type a name above and click Add Doctor, or press Enter.</div></div>';
  } else {
    html += '<div class="entity-list">';
    html += STATE.doctors.map((doc) => {
      const initials = doc.name.split(' ').map(p => p[0]).join('').toUpperCase().slice(0, 2);
      return `<div class="entity-card">
  <div class="avatar">${initials}</div>
  <div class="info">
    <div class="name">${escapeHtml(doc.name)}</div>
    <div class="toggles">
      <label class="toggle-label"><span class="toggle-text">Hospital Call</span>
      <div class="toggle-switch"><input type="checkbox" ${doc.hospitalCallEligible ? 'checked' : ''} onchange="updateDocField('${doc.id}', 'hospitalCallEligible', this.checked)"/><span class="toggle-slider"></span></div>
      </label>
      <label class="toggle-label"><span class="toggle-text">Surgical</span>
      <div class="toggle-switch"><input type="checkbox" ${doc.surgicalAssistEligible ? 'checked' : ''} onchange="updateDocField('${doc.id}', 'surgicalAssistEligible', this.checked)"/><span class="toggle-slider"></span></div>
      </label>
    </div>
  </div>
  <div class="actions">
    <button class="btn btn-sm btn-ghost" onclick="switchTab('doctors'); setTimeout(() => openDoctorAccordion('${doc.id}'), 80)">Edit</button>
    <button class="btn btn-sm btn-danger" onclick="removeDoctor('${doc.id}')">Remove</button>
  </div>
</div>`;
    }).join('');
    html += '</div>';
  }
  el.innerHTML = html;
}

function renderWizardOffices() {
  const el = document.getElementById('wiz-offices-list');
  if (!el) { console.warn('[renderWizardOffices] #wiz-offices-list not found'); return; }
  let html = '<div class="quick-add"><input type="text" id="quick-add-office-name" placeholder="Office name" onkeydown="if(event.key===\'Enter\')quickAddOffice()"/><button class="btn btn-primary btn-sm" onclick="quickAddOffice()">+ Add Office</button></div>';
  if (!STATE.offices.length) {
    html += '<div class="empty-state"><div class="empty-state-icon">+</div><div class="empty-state-title">No offices yet</div><div class="empty-state-desc">Type a name above and click Add Office. The first office will be marked as the hospital by default.</div></div>';
  } else {
    html += '<div class="entity-list">';
    html += STATE.offices.map(off => {
      const icon = off.isHospital ? '⌁' : '○';
      return `<div class="entity-card">
  <div class="avatar" style="${off.isHospital ? 'background:var(--accent-dim);color:var(--accent)' : ''}">${icon}</div>
  <div class="info" style="flex:1">
    <input type="text" class="doc-name-input" value="${escapeHtml(off.name)}" onchange="updateOfficeField('${off.id}', 'name', this.value)" style="margin-bottom:0.3rem"/>
    <div style="display:flex;gap:0.6rem;align-items:center;flex-wrap:wrap">
      <label class="toggle-label" style="margin:0"><span class="toggle-text">Hospital</span>
      <div class="toggle-switch"><input type="checkbox" ${off.isHospital ? 'checked' : ''} onchange="updateOfficeField('${off.id}', 'isHospital', this.checked)"/><span class="toggle-slider"></span></div>
      </label>
      <div class="limit-item" style="margin:0"><label>Max/Shift</label><input type="number" min="1" max="10" value="${off.maxPerShift}" onchange="updateOfficeField('${off.id}', 'maxPerShift', parseInt(this.value)||2)"/></div>
      <div class="limit-item" style="margin:0"><label>Restr. Tue Max</label><input type="number" min="0" max="10" value="${off.restrictedTuesdayMax}" onchange="updateOfficeField('${off.id}', 'restrictedTuesdayMax', parseInt(this.value)||1)"/></div>
    </div>
  </div>
  <div class="actions">
    <button class="btn btn-sm btn-danger" onclick="removeOffice('${off.id}')">Remove</button>
  </div>
</div>`;
    }).join('');
    html += '</div>';
  }
  el.innerHTML = html;
}

// ── Setup (backward compat for old tab IDs) ─────────────────────────────────

function renderSetup() {
	// old tab panes are hidden but kept for backward compat
	updateDataStatus();
}

// ── Doctors ─────────────────────────────────────────────────────────────────

function addDoctor() {
  STATE.doctors.push(defaultStateDoctor());
  saveState();
  if (wizardStep === 2) renderWizardDoctors();
  renderDoctorAccordion();
  updateWizardSummary();
  updateBlackoutDoctorSelect();
  renderQuickSetupSummary();
}

function quickAddDoctor() {
  const input = document.getElementById('quick-add-doctor-name');
  const name = input ? input.value.trim() : '';
  const doc = defaultStateDoctor();
  if (name) doc.name = name;
  STATE.doctors.push(doc);
  saveState();
  renderWizardDoctors();
  renderDoctorAccordion();
  updateWizardSummary();
  updateBlackoutDoctorSelect();
  renderQuickSetupSummary();
  const newInput = document.getElementById('quick-add-doctor-name');
  if (newInput) newInput.focus();
}

function removeDoctor(id) {
  STATE.doctors = STATE.doctors.filter(d => d.id !== id);
  for (const mk of Object.keys(STATE.blackouts)) {
    delete STATE.blackouts[mk][id];
    if (Object.keys(STATE.blackouts[mk]).length === 0) delete STATE.blackouts[mk];
  }
  saveState();
  if (wizardStep === 2) renderWizardDoctors();
  renderDoctorAccordion();
  updateWizardSummary();
  updateBlackoutDoctorSelect();
  renderQuickSetupSummary();
}

function addOffice() {
  const id = 'off_' + generateId().slice(0, 5);
  STATE.offices.push({
    id, name: 'Office ' + (STATE.offices.length + 1),
    isHospital: STATE.offices.length === 0,
    maxPerShift: 2, restrictedTuesdayMax: 1, locationAddress: ''
  });
  saveState();
  console.log('[addOffice] Added:', id, 'Total offices:', STATE.offices.length, 'wizardStep:', wizardStep);
  renderWizardOffices();
  updateWizardSummary();
  renderQuickSetupSummary();
}

function quickAddOffice() {
  const input = document.getElementById('quick-add-office-name');
  const name = input ? input.value.trim() : '';
  const id = 'off_' + generateId().slice(0, 5);
  const office = {
    id, name: name || ('Office ' + (STATE.offices.length + 1)),
    isHospital: STATE.offices.length === 0,
    maxPerShift: 2, restrictedTuesdayMax: 1, locationAddress: ''
  };
  STATE.offices.push(office);
  saveState();
  renderWizardOffices();
  updateWizardSummary();
  renderQuickSetupSummary();
  const newInput = document.getElementById('quick-add-office-name');
  if (newInput) newInput.focus();
}

function updateOfficeField(officeId, field, value) {
    const office = STATE.offices.find(o => o.id === officeId);
    if (!office) return;
    office[field] = value;
    saveState();
    if (field === 'isHospital' || field === 'name') renderWizardOffices();
    if (field === 'isHospital') renderDoctorAccordion();
    updateWizardSummary();
}

function removeOffice(id) {
  STATE.offices = STATE.offices.filter(o => o.id !== id);
  saveState();
  renderWizardOffices();
  updateWizardSummary();
  renderQuickSetupSummary();
}

function openDoctorAccordion(docId) {
	const items = document.querySelectorAll('.doc-item');
	for (const item of items) {
		if (item.dataset.docId === docId) {
			if (!item.classList.contains('open')) {
				toggleDocItem(item.querySelector('.doc-header'));
			}
			item.scrollIntoView({ behavior: 'smooth', block: 'center' });
			break;
		}
	}
}

// ── Blackout calendars ─────────────────────────────────────────────────────

function updateBlackoutDoctorSelect() {
  const sel = document.getElementById('blackout-doctor-select');
  if (sel) {
    sel.innerHTML = STATE.doctors.map(d =>
      `<option value="${d.id}">${escapeHtml(d.name)}</option>`
    ).join('');
  }
}

function getBlackoutYearMonth() {
  const yEl = document.getElementById('wiz-year');
  const mEl = document.getElementById('wiz-month');
  const year = yEl ? parseInt(yEl.value) : currentScheduleYear || new Date().getFullYear();
  const month = mEl ? parseInt(mEl.value) : currentScheduleMonth || new Date().getMonth();
  return { year, month };
}

// ── Generate (wizard step 4) ────────────────────────────────────────────────

function validateCallEligibility() {
  const hospitalExists = STATE.offices.some(o => o.isHospital);
  if (!hospitalExists) return null;
  const hasCallDoc = STATE.doctors.some(d => d.hospitalCallEligible);
  if (!hasCallDoc) return 'No doctors are hospital-call-eligible. Enable "Hospital Call" for at least one doctor before generating.';
  return null;
}

async function handleGenerate() {
    const year = parseInt(document.getElementById('wiz-year')?.value || 2026);
    const month = parseInt(document.getElementById('wiz-month')?.value || 8);
    const timeout = STATE.settings.solverTimeLimitSeconds || 900;
  const statusEl = document.getElementById('gen-status');
  const btn = document.getElementById('btn-generate');

  if (!STATE.doctors.length || !STATE.offices.length) {
    statusEl.innerHTML = '<span class="err">Add at least one doctor and one office first.</span>';
    return;
  }

  const eligibilityErr = validateCallEligibility();
  if (eligibilityErr) {
    statusEl.innerHTML = `<span class="err">${eligibilityErr}</span>`;
    return;
  }

  statusEl.innerHTML = '<span class="gen-loading"><span class="spinner"></span> Generating schedule…</span>';
  if (btn) btn.disabled = true;
  const panel = document.getElementById('conflict-panel');
  const list = document.getElementById('conflict-list');
  panel?.classList.add('hidden');

  try {
    STATE.settings.solverTimeLimitSeconds = timeout;
    const result = await apiGenerate(year, month);
    console.log('[handleGenerate] API result:', result?.solverStatus, 'assignments:', result?.assignments?.length, 'slots:', result?.slots?.length);
    if (!result || !result.assignments) {
      throw new Error('Invalid response from server — no assignments returned');
    }
    const mk = getMonthKey(year, month);
    STATE.schedules[mk] = result;
    updateTotalsFromSchedule(result);
    saveState();

		currentScheduleYear = year;
		currentScheduleMonth = month;

		statusEl.innerHTML = result.partial
    ? `<span class="err">Schedule created with ${result.unmetConstraints?.length || 0} issues. Review below.</span>`
    : '<span class="ok">&#10003; Schedule generated successfully!</span>';

		if (result.partial && result.unmetConstraints?.length) {
			if (list) {
				list.innerHTML = result.unmetConstraints.map(c =>
					`<li><strong>${escapeHtml(c.id || c.name || 'Constraint')}</strong>: ${escapeHtml(c.description || '')} → ${escapeHtml(c.suggestion || '')}</li>`
				).join('');
			}
			panel?.classList.remove('hidden');
		}

    updateCalendarView();
    showWizSchedulePreview();
    updateBalanceTable();
    updateDataStatus();
  } catch (err) {
    const msg = err.message || String(err);
    const isNetworkErr = msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('Network request');
    if (isNetworkErr) {
      statusEl.innerHTML = `<span class="err">Cannot reach the backend server at ${API_BASE}. Start the backend with: cd backend && PYTHONPATH=. python3 app.py</span>`;
    } else {
      statusEl.innerHTML = `<span class="err">Error: ${escapeHtml(msg)}</span>`;
    }
    console.error(err);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Schedule view ───────────────────────────────────────────────────────────

function updateCalendarView() {
	const container = document.getElementById('calendar-container');
	if (!container) return;
	const mk = getMonthKey(currentScheduleYear, currentScheduleMonth);
	const data = STATE.schedules[mk];
	container.innerHTML = buildCalendarHTML(currentScheduleYear, currentScheduleMonth, data);
	updateScheduleDisplay(data);
}

function updateScheduleDisplay(data) {
	const label = document.getElementById('sched-month-label');
	const navLabel = document.getElementById('sched-nav-label');
	if (label) label.textContent = `${MONTHS[currentScheduleMonth]} ${currentScheduleYear}`;
	if (navLabel) navLabel.textContent = `${MONTHS[currentScheduleMonth].slice(0, 3)} ${currentScheduleYear}`;

	const statusEl = document.getElementById('sched-solver-status');
	const callGiniEl = document.getElementById('sched-call-gini');
	const sessGiniEl = document.getElementById('sched-session-gini');

	const applyClass = (el, val, warnThresh = 0.10) => {
		if (!el) return;
		el.textContent = val != null ? (typeof val === 'number' ? val.toFixed(3) : val) : '—';
		el.className = 'stat-val';
		if (data?.partial) el.classList.add('val-warn');
		else if (data?.solverStatus === 'optimal') el.classList.add('val-ok');
	};

  if (statusEl) {
    let statusText = data?.solverStatus || '—';
    if (statusText === 'optimal') statusText = 'Optimal';
    else if (statusText === 'not_solved') statusText = 'Not solved';
    else if (data?.partial) statusText = 'Partial';
    statusEl.textContent = statusText;
    statusEl.className = 'stat-val' + (data?.partial ? ' val-warn' : data?.solverStatus === 'optimal' ? ' val-ok' : '');
  }
  if (callGiniEl) {
    const v = data?.giniCalls;
    callGiniEl.textContent = v != null ? (v <= 0.10 ? 'Fair' : 'Uneven') : '—';
    callGiniEl.className = 'stat-val' + (v > 0.10 ? ' val-warn' : v != null ? ' val-ok' : '');
  }
  if (sessGiniEl) {
    const v = data?.giniSessions;
    sessGiniEl.textContent = v != null ? (v <= 0.10 ? 'Fair' : 'Uneven') : '—';
    sessGiniEl.className = 'stat-val' + (v > 0.10 ? ' val-warn' : v != null ? ' val-ok' : '');
  }
}

function changeScheduleMonth(delta) {
  currentScheduleMonth += delta;
  if (currentScheduleMonth > 11) { currentScheduleMonth = 0; currentScheduleYear++; }
  if (currentScheduleMonth < 0) { currentScheduleMonth = 11; currentScheduleYear--; }
  updateCalendarView();
}

function handleClearMonth() {
  const mk = getMonthKey(currentScheduleYear, currentScheduleMonth);
  if (!STATE.schedules[mk]) return;
  if (!confirm('Clear the schedule for ' + MONTHS[currentScheduleMonth] + ' ' + currentScheduleYear + '? This cannot be undone.')) return;
  delete STATE.schedules[mk];
  updateTotalsFromSchedule({});
  saveState();
  updateCalendarView();
  updateBalanceTable();
  updateDataStatus();
}

function updateScheduleControls() {
	updateCalendarView();
}

// ── Balance table ──────────────────────────────────────────────────────────

function updateBalanceTable() {
    const wrapper = document.getElementById('balance-table-wrapper');
    const monthsWrapper = document.getElementById('balance-months-wrapper');
    if (!wrapper) return;

    const hasData = STATE.schedules && Object.keys(STATE.schedules).length > 0;
    if (!hasData) {
        wrapper.innerHTML = '<p class="empty-msg">Generate a schedule to see the cumulative balance report.</p>';
        if (monthsWrapper) monthsWrapper.innerHTML = '';
        return;
    }

    const doctors = STATE.doctors;
    const nonHosp = STATE.offices.filter(o => !o.isHospital);
    const callCols = ['Wk Day', 'Wk Night', 'Fri Night', 'Wknd'];
    const sessCols = ['Sessions', 'AM', 'PM', 'Late'];
    const officeCols = nonHosp.map(o => o.name);

    let html = '<table class="sheet-table balance-table">';
    html += '<thead><tr><th>Doctor</th>';
    for (const c of [...callCols, ...sessCols]) html += `<th>${escapeHtml(c)}</th>`;
    for (const o of officeCols) html += `<th>${escapeHtml(o)}</th>`;
    html += '<th>Pref</th></tr></thead><tbody>';

    for (const doc of doctors) {
        const t = STATE.totals[doc.id] || {};
        const visits = t.office_visits || {};
        html += `<tr><td>${escapeHtml(doc.name)}</td>`;
        html += `<td>${t.weekday_day || 0}</td>`;
        html += `<td>${t.weekday_night || 0}</td>`;
        html += `<td>${t.friday_night || 0}</td>`;
        html += `<td>${t.weekend_blocks || 0}</td>`;
        html += `<td>${t.total_sessions || 0}</td>`;
        html += `<td>${t.am_sessions || 0}</td>`;
        html += `<td>${t.pm_sessions || 0}</td>`;
        html += `<td>${t.late_sessions || 0}</td>`;
        for (const o of nonHosp) {
            html += `<td>${visits[o.id] || 0}</td>`;
        }
        const mc = Object.values(STATE.schedules).pop()?.counts?.[doc.id];
        const prefRate = mc?.preferredDayCallRate;
        html += `<td>${prefRate != null ? (prefRate * 100).toFixed(0) + '%' : '—'}</td>`;
        html += '</tr>';
    }

    const gini = calculateGiniFromTotals();
    html += `<tr class="gini-row"><td>Call Fairness</td>`;
    html += `<td class="${gini > 0.10 ? 'gini-warn' : 'gini-ok'}" colspan="4">${gini <= 0.10 ? 'Fair' : 'Uneven'} (${gini.toFixed(3)})</td>`;
    html += '<td colspan="5"></td>';
    for (const o of officeCols) html += '<td></td>';
    html += '<td></td></tr></tbody></table>';
    wrapper.innerHTML = html;

    if (monthsWrapper) {
        const monthKeys = Object.keys(STATE.schedules).sort();
        if (!monthKeys.length) {
            monthsWrapper.innerHTML = '';
            return;
        }
        let mHtml = '';
        for (const mk of monthKeys) {
            const sched = STATE.schedules[mk];
            const parts = mk.split('-');
            const mLabel = MONTHS[parseInt(parts[1])] + ' ' + parts[0];
            const counts = sched.counts || {};
            mHtml += `<div class="balance-month-block">`;
            mHtml += `<div class="balance-month-title">${escapeHtml(mLabel)}</div>`;
            mHtml += '<table class="sheet-table balance-table balance-month-table"><thead><tr><th>Doctor</th>';
            for (const c of callCols) mHtml += `<th>${escapeHtml(c)}</th>`;
            for (const c of sessCols) mHtml += `<th>${escapeHtml(c)}</th>`;
            mHtml += '</tr></thead><tbody>';
            for (const doc of doctors) {
                const c = counts[doc.id];
                if (!c) continue;
                mHtml += `<tr><td>${escapeHtml(doc.name)}</td>`;
                mHtml += `<td>${c.weekdayDayCalls || 0}</td>`;
                mHtml += `<td>${c.weekdayNightCalls || 0}</td>`;
                mHtml += `<td>${c.fridayNightCalls || 0}</td>`;
                mHtml += `<td>${c.weekendBlocks || 0}</td>`;
                mHtml += `<td>${c.totalSessions || 0}</td>`;
                mHtml += `<td>${c.amSessions || 0}</td>`;
                mHtml += `<td>${c.pmSessions || 0}</td>`;
                mHtml += `<td>${c.lateSessions || 0}</td>`;
                mHtml += '</tr>';
            }
            mHtml += '</tbody></table></div>';
        }
        monthsWrapper.innerHTML = mHtml;
    }
}

function calculateGiniFromTotals() {
	const values = Object.values(STATE.totals || {}).map(t =>
		(t.weekday_day || 0) + (t.weekday_night || 0) + (t.friday_night || 0) + (t.weekend_blocks || 0)
	);
	if (!values.length) return 0;
	values.sort((a, b) => a - b);
	let iSum = 0;
	for (let i = 0; i < values.length; i++) iSum += (i + 1) * values[i];
	const total = values.reduce((a, b) => a + b, 0);
	if (total === 0) return 0;
	return (2 * iSum) / (values.length * total) - (values.length + 1) / values.length;
}

// ── CSV handlers ────────────────────────────────────────────────────────────

function parseDoctorsCSV(csvText) {
	const lines = csvText.trim().split('\n');
	if (lines.length < 2) return [];
	const headers = lines[0].split(',').map(h => h.trim().replace(/"/g, ''));
	return lines.slice(1).map(line => {
		const vals = line.match(/("([^"]*)"|[^,]*)/g) || [];
		const cleanVals = vals.map(v => v.replace(/^"|"$/g, '').trim());
		const row = {};
		headers.forEach((h, i) => row[h] = cleanVals[i] || '');
		return row;
	});
}

function parseOfficesCSV(csvText) { return parseDoctorsCSV(csvText); }

function handleImportDoctors(file) {
	const reader = new FileReader();
	reader.onload = function(e) {
		try {
			const rows = parseDoctorsCSV(e.target.result);
			const imported = [];
			for (const row of rows) {
				if (!row.name && !row.Name) continue;
				imported.push({
					id: row.id || ('d_' + generateId().slice(0, 5)),
					name: row.name || row.Name || 'Dr. Unknown',
					allowedOffices: row.allowedOffices ? row.allowedOffices.split(';').map(s => s.trim()).filter(Boolean) : null,
					officePreferences: [],
					requiredSessionsPerWeek: parseInt(row.requiredSessionsPerWeek || row.required_sessions_per_week || 5) || 5,
					hospitalCallEligible: !(['false','0','no'].includes(String(row.hospitalCallEligible).toLowerCase())),
					surgicalAssistEligible: !(['false','0','no'].includes(String(row.surgicalAssistEligible).toLowerCase())),
					maxWeekdayDayCalls: parseInt(row.maxWeekdayDayCalls || row.max_weekday_day_calls || 5) || 5,
					maxWeekdayNightCalls: parseInt(row.maxWeekdayNightCalls || row.max_weekday_night_calls || 5) || 5,
					maxFridayNightCalls: parseInt(row.maxFridayNightCalls || row.max_friday_night_calls || 2) || 2,
					maxWeekendBlocks: parseInt(row.maxWeekendBlocks || row.max_weekend_blocks || 2) || 2,
					preferredCallDays: row.preferredCallDays ? row.preferredCallDays.split(';').map(Number).filter(n => !isNaN(n)) : [],
					postCallPreference: row.postCallPreference || 'no_preference',
					callShiftPreference: row.callShiftPreference || 'no_preference',
					dayNightPreference: row.dayNightPreference || 'balanced',
					amPmPreference: row.amPmPreference || 'balanced',
					standingDaysOff: row.standingDaysOff ? row.standingDaysOff.split(';').map(Number).filter(n => !isNaN(n)) : [],
					fixedRecurring: [],
					oneTimeOverrides: [],
				});
			}
			if (!imported.length) { alert('No valid doctors found.'); return; }
			STATE.doctors = imported;
			saveState();
			renderWizardDoctors();
			renderDoctorAccordion();
			updateWizardSummary();
			updateBlackoutDoctorSelect();
			updateBalanceTable();
			alert(`Imported ${imported.length} doctor(s)`);
		} catch (err) { alert('Import failed: ' + err.message); }
	};
	reader.readAsText(file);
}

function handleImportOffices(file) {
	const reader = new FileReader();
	reader.onload = function(e) {
		try {
			const rows = parseOfficesCSV(e.target.result);
			const imported = [];
			for (const row of rows) {
				if (!row.name && !row.Name && !row.id) continue;
				const id = row.id || row.Name?.toLowerCase().replace(/\s+/g, '_').slice(0, 8) || ('off_' + generateId().slice(0, 5));
				imported.push({
					id,
					name: row.name || row.Name || id,
					isHospital: row.isHospital === 'true' || row.isHospital === '1' || row.isHospital === 'yes',
					maxPerShift: parseInt(row.maxPerShift || row.max_per_shift || 2) || 2,
					restrictedTuesdayMax: parseInt(row.restrictedTuesdayMax || row.restricted_tuesday_max || 1) || 1,
					locationAddress: row.locationAddress || row.location_address || '',
				});
			}
			if (!imported.length) { alert('No valid offices found.'); return; }
			if (!imported.some(o => o.isHospital)) imported[0].isHospital = true;
			STATE.offices = imported;
			saveState();
			renderWizardOffices();
			updateWizardSummary();
			alert(`Imported ${imported.length} office(s)`);
		} catch (err) { alert('Import failed: ' + err.message); }
	};
	reader.readAsText(file);
}

function handleExportDoctors() {
	const headers = ['name','id','hospitalCallEligible','surgicalAssistEligible','requiredSessionsPerWeek','maxWeekdayDayCalls','maxWeekdayNightCalls','maxFridayNightCalls','maxWeekendBlocks','preferredCallDays','standingDaysOff','allowedOffices'];
	let csv = headers.map(h => `"${h}"`).join(',') + '\n';
	for (const doc of STATE.doctors) {
		csv += [ `"${doc.name}"`, doc.id, doc.hospitalCallEligible, doc.surgicalAssistEligible,
			doc.requiredSessionsPerWeek, doc.maxWeekdayDayCalls, doc.maxWeekdayNightCalls,
			doc.maxFridayNightCalls, doc.maxWeekendBlocks,
			(doc.preferredCallDays||[]).join(';'), (doc.standingDaysOff||[]).join(';'), (doc.allowedOffices||[]).join(';')
		].join(',') + '\n';
	}
	downloadBlob(csv, 'doctors_template.csv');
}

function handleExportOffices() {
	const headers = ['id','name','isHospital','maxPerShift','restrictedTuesdayMax'];
	let csv = headers.map(h => `"${h}"`).join(',') + '\n';
	for (const off of STATE.offices) {
		csv += [off.id, `"${off.name}"`, off.isHospital, off.maxPerShift, off.restrictedTuesdayMax].join(',') + '\n';
	}
	downloadBlob(csv, 'offices_template.csv');
}

async function handleExportBalance() {
	try {
		const csv = await apiExportBalance(STATE.doctors, STATE.offices, STATE.totals);
		downloadBlob(csv, 'balance.csv');
	} catch (e) { alert('Export failed: ' + e.message); }
}

async function handleImportBalance() {
	const input = document.getElementById('import-balance-file');
	if (!input.files.length) return;
	try {
		const result = await apiImportBalance(input.files[0]);
		for (const [docId, data] of Object.entries(result)) STATE.totals[docId] = data;
		saveState();
		updateBalanceTable();
		alert('Balance imported');
	} catch (e) { alert('Import failed: ' + e.message); }
}

async function handleExportSchedule() {
	const mk = getMonthKey(currentScheduleYear, currentScheduleMonth);
	const data = STATE.schedules[mk];
	if (!data) { alert('No schedule for this month'); return; }
	try {
		const csv = await apiExportSchedule(currentScheduleYear, currentScheduleMonth, data.assignments);
		downloadBlob(csv, `schedule-${mk}.csv`);
	} catch (e) { alert('Export failed: ' + e.message); }
}

function downloadBlob(content, filename) {
	const blob = new Blob([content], { type: 'text/csv' });
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url; a.download = filename; a.click();
	setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ── Tab switching ────────────────────────────────────────────────────────────

function switchTab(tabName) {
	document.querySelectorAll('.tab-btn').forEach(btn =>
		btn.classList.toggle('active', btn.dataset.tab === tabName)
	);
	document.querySelectorAll('.tab-pane').forEach(pane =>
		pane.classList.toggle('active', pane.id === 'tab-' + tabName)
	);
  if (tabName === 'setup') { showWizardStep(wizardStep); refreshBlackoutCalendar(); }
  if (tabName === 'doctors') renderDoctorAccordion();
  if (tabName === 'schedule') { updateScheduleControls(); updateCalendarView(); }
  if (tabName === 'balance') updateBalanceTable();
}

function updateDataStatus() {
	const el = document.getElementById('data-status');
	if (!el) return;
	const schedCount = Object.keys(STATE.schedules || {}).length;
	const docCount = STATE.doctors.length;
	el.textContent = `${schedCount} month(s) generated · ${docCount} doctor(s)`;
}

function escapeHtml(text) {
	const d = document.createElement('div');
	d.textContent = text || '';
	return d.innerHTML;
}

function refreshUI() {
    const activeTab = document.querySelector('.tab-btn.active');
    const tabName = activeTab ? activeTab.dataset.tab : 'setup';
  if (tabName === 'setup') {
    showWizardStep(wizardStep);
    refreshBlackoutCalendar();
  } else if (tabName === 'doctors') {
    renderDoctorAccordion();
  } else if (tabName === 'schedule') {
    updateScheduleControls();
    updateCalendarView();
  } else if (tabName === 'balance') {
    updateBalanceTable();
  }
  updateDataStatus();
  updateWizardSummary();
  renderQuickSetupSummary();
}

// ── Event listeners ─────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const wizYear = document.getElementById('wiz-year');
  if (wizYear && !wizYear.value) wizYear.value = new Date().getFullYear();
  showWizardStep(wizardStep);
  updateBlackoutDoctorSelect();
  refreshBlackoutCalendar();
  updateBalanceTable();
  updateScheduleControls();
  updateWizardSummary();
  renderQuickSetupSummary();

  // Tab nav
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

    // Wizard step dots clickable
    document.querySelectorAll('.step-dot').forEach(dot => {
        dot.addEventListener('click', (e) => {
            e.stopPropagation();
            showWizardStep(parseInt(dot.dataset.step));
        });
    });

  // Wizard step 4 blackout select
  document.getElementById('blackout-doctor-select')?.addEventListener('change', refreshBlackoutCalendar);

	// Wizard file imports
	document.getElementById('import-doctors-file')?.addEventListener('change', function() {
		if (this.files.length) { handleImportDoctors(this.files[0]); this.value = ''; }
	});
	document.getElementById('import-offices-file')?.addEventListener('change', function() {
		if (this.files.length) { handleImportOffices(this.files[0]); this.value = ''; }
	});

	// Balance export/import
	document.getElementById('btn-export-balance')?.addEventListener('click', handleExportBalance);
	document.getElementById('import-balance-file')?.addEventListener('change', handleImportBalance);

	// API health check
	apiHealth()
		.then(() => {
			const el = document.getElementById('api-status');
			if (el) { el.textContent = 'API Online'; el.className = 'api-online'; }
		})
		.catch(() => {
			const el = document.getElementById('api-status');
			if (el) { el.textContent = 'API Offline'; el.className = 'api-offline'; }
		});

	updateDataStatus();
});