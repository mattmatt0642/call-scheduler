/* =========================
   App Controller — Wizard-first design
   ========================= */

const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

function showToast(msg, duration = 2500) {
  const c = document.getElementById('toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => { t.classList.add('toast-out'); setTimeout(() => t.remove(), 250); }, duration);
}

function alertMsg(msg) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `<div class="modal-box">
      <div class="modal-body">${escapeHtml(msg)}</div>
      <div class="modal-actions"><button class="btn btn-primary modal-ok">OK</button></div>
    </div>`;
    document.body.appendChild(overlay);
    const ok = overlay.querySelector('.modal-ok');
    const close = () => { overlay.remove(); resolve(); };
    ok.addEventListener('click', close);
    overlay.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    ok.focus();
  });
}

function confirmAction(msg) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `<div class="modal-box">
      <div class="modal-body">${escapeHtml(msg)}</div>
      <div class="modal-actions">
        <button class="btn btn-ghost modal-cancel">Cancel</button>
        <button class="btn btn-danger modal-confirm">Confirm</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    const confirm = overlay.querySelector('.modal-confirm');
    const cancel = overlay.querySelector('.modal-cancel');
    const done = (val) => { overlay.remove(); resolve(val); };
    confirm.addEventListener('click', () => done(true));
    cancel.addEventListener('click', () => done(false));
    overlay.addEventListener('keydown', e => { if (e.key === 'Escape') done(false); });
    cancel.focus();
  });
}
let currentScheduleYear = new Date().getFullYear();
let currentScheduleMonth = new Date().getMonth();
let wizViewYear = currentScheduleYear;
let wizViewMonth = currentScheduleMonth;
let wizardStep = 1;

let _undoSnapshot = null;
let _undoTimer = null;

function _saveUndoSnapshot() {
  _undoSnapshot = structuredClone ? structuredClone(STATE) : JSON.parse(JSON.stringify(STATE));
}

function _clearUndo() {
  _undoSnapshot = null;
  clearTimeout(_undoTimer);
  _undoTimer = null;
}

function performUndo() {
  if (!_undoSnapshot) return;
  STATE = _undoSnapshot;
  _undoSnapshot = null;
  clearTimeout(_undoTimer);
  _undoTimer = null;
  saveState();
  refreshUI();
  showToast('Action undone');
}

function _showUndoToast(msg, duration = 5000) {
  const c = document.getElementById('toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = 'toast toast-undo';
  t.innerHTML = `<span>${escapeHtml(msg)}</span> <button class="btn btn-sm btn-ghost toast-undo-btn" onclick="performUndo(); this.closest('.toast').remove()">Undo</button>`;
  c.appendChild(t);
  _undoTimer = setTimeout(() => { t.classList.add('toast-out'); setTimeout(() => t.remove(), 250); _undoSnapshot = null; }, duration);
}

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

  document.querySelectorAll('.step-item').forEach(item => {
    const s = parseInt(item.dataset.step);
    const dot = item.querySelector('.step-dot');
    if (!dot) return;
    dot.classList.remove('active', 'done');
    dot.textContent = s;
    if (s === step) dot.classList.add('active');
    else if (s < step) { dot.classList.add('done'); dot.innerHTML = '&#10003;'; }
  });

  document.querySelectorAll('.step-line').forEach((line, i) => {
    const leftStep = i + 1;
    const rightStep = i + 2;
    if (leftStep < step && rightStep <= step) line.classList.add('done');
    else line.classList.remove('done');
  });

  try { renderQuickSetupSummary(); } catch(e) { console.error('[showWizardStep] renderQuickSetupSummary error:', e); }
  try { renderWizardDoctors(); } catch(e) { console.error('[showWizardStep] renderWizardDoctors error:', e); }
  try { renderWizardOffices(); } catch(e) { console.error('[showWizardStep] renderWizardOffices error:', e); }
  try { updateWizardSummary(); } catch(e) { console.error('[showWizardStep] updateWizardSummary error:', e); }
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
  const mk = getMonthKey(wizViewYear, wizViewMonth);
  const data = STATE.schedules[mk];
  if (data) {
    const container = document.getElementById('wiz-calendar-container');
    if (container) container.innerHTML = buildCalendarHTML(wizViewYear, wizViewMonth, data);
    updateWizScheduleDisplay(data);
  } else {
    const container = document.getElementById('wiz-calendar-container');
    if (container) container.innerHTML = '';
    updateWizScheduleDisplay(null);
  }
  preview.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updateWizScheduleDisplay(data) {
  const label = document.getElementById('wiz-sched-month-label');
  const navLabel = document.getElementById('wiz-sched-nav-label');
  if (label) label.textContent = `${MONTHS[wizViewMonth]} ${wizViewYear}`;
  if (navLabel) navLabel.textContent = `${MONTHS[wizViewMonth].slice(0, 3)} ${wizViewYear}`;

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
  const wizUnfilledEl = document.getElementById('wiz-sched-unfilled');
  if (wizUnfilledEl) {
    const totalSlots = data?.slots?.length || 0;
    const filledSlots = data?.assignments?.length || 0;
    const unfilled = totalSlots - filledSlots;
    wizUnfilledEl.textContent = unfilled > 0 ? String(unfilled) : '0';
    wizUnfilledEl.className = 'stat-val' + (unfilled > 0 ? ' val-warn' : totalSlots > 0 ? ' val-ok' : '');
  }
}

function changeWizScheduleMonth(delta) {
  wizViewMonth += delta;
  if (wizViewMonth > 11) { wizViewMonth = 0; wizViewYear++; }
  if (wizViewMonth < 0) { wizViewMonth = 11; wizViewYear--; }
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
  if (!STATE.doctors.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">+</div><div class="empty-state-title">No doctors yet</div><div class="empty-state-desc">Type a name above and click Add Doctor, or press Enter.</div></div>';
  } else {
    let html = '<div class="entity-list">';
    html += STATE.doctors.map((doc) => {
      const initials = doc.name.split(' ').map(p => p[0]).join('').toUpperCase().slice(0, 2);
      const avatarColorSet = THEME_CONFIG.avatarColors || ['#4f8ff7','#34d399','#a78bfa','#2dd4bf','#fbbf24','#f87171'];
const avatarColor = avatarColorSet[STATE.doctors.indexOf(doc) % avatarColorSet.length];
return `<div class="entity-card fade-in-item">
  <div class="avatar" style="background:${avatarColor}">${initials}</div>
  <div class="info">
  <div class="name">${escapeHtml(doc.name)}</div>
  <div class="toggles">
  <label class="toggle-label"><span class="toggle-text">Hospital Call</span>
  <div class="toggle-switch"><input type="checkbox" ${doc.hospitalCallEligible ? 'checked' : ''} onchange="updateDocField('${doc.id}', 'hospitalCallEligible', this.checked)"/><span class="toggle-slider"></span></div>
  </label>
        <label class="toggle-label"><span class="toggle-text">Surgical</span>
        <div class="toggle-switch"><input type="checkbox" ${doc.surgicalAssistEligible ? 'checked' : ''} onchange="updateDocField('${doc.id}', 'surgicalAssistEligible', this.checked)"/><span class="toggle-slider"></span></div>
        </label>
        <label class="toggle-label"><span class="toggle-text">No Wknd Call</span>
        <div class="toggle-switch"><input type="checkbox" ${doc.weekendCallOff ? 'checked' : ''} onchange="updateDocField('${doc.id}', 'weekendCallOff', this.checked)"/><span class="toggle-slider"></span></div>
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
    el.innerHTML = html;
  }
}

function renderWizardOffices() {
  const el = document.getElementById('wiz-offices-list');
  if (!el) { console.warn('[renderWizardOffices] #wiz-offices-list not found'); return; }
  if (!STATE.offices.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">+</div><div class="empty-state-title">No offices yet</div><div class="empty-state-desc">Type a name above and click Add Office. The first office will be marked as the hospital by default.</div></div>';
  } else {
    let html = '<div class="entity-list">';
    html += STATE.offices.map(off => {
      const icon = off.isHospital ? '⌁' : '○';
      const avatarColor = off.isHospital ? '#4f8ff7' : '#2dd4bf';
      const avatarCls = 'avatar';
      return `<div class="entity-card fade-in-item">
  <div class="${avatarCls}" style="background:${avatarColor}">${icon}</div>
  <div class="info">
  <input type="text" class="doc-name-input office-name-input" value="${escapeHtml(off.name)}" onchange="updateOfficeField('${off.id}', 'name', this.value)"/>
  <div class="office-toggles-row">
  <label class="toggle-label"><span class="toggle-text">Hospital</span>
  <div class="toggle-switch"><input type="checkbox" ${off.isHospital ? 'checked' : ''} onchange="updateOfficeField('${off.id}', 'isHospital', this.checked)"/><span class="toggle-slider"></span></div>
  </label>
  <div class="limit-item"><label>Max/Shift</label><input type="number" min="1" max="10" value="${off.maxPerShift}" onchange="updateOfficeField('${off.id}', 'maxPerShift', parseInt(this.value)||2)"/></div>
  <div class="limit-item"><label>Restr. Tue Max</label><input type="number" min="0" max="10" value="${off.restrictedTuesdayMax}" onchange="updateOfficeField('${off.id}', 'restrictedTuesdayMax', parseInt(this.value)||1)"/></div>
  </div>
  </div>
  <div class="actions">
  <button class="btn btn-sm btn-danger" onclick="removeOffice('${off.id}')">Remove</button>
  </div>
  </div>`;
    }).join('');
    html += '</div>';
    el.innerHTML = html;
  }
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
  renderWizardDoctors();
  renderDoctorAccordion();
  updateWizardSummary();
  updateBlackoutDoctorSelect();
  renderQuickSetupSummary();
}

function quickAddDoctor() {
  const input = document.getElementById('quick-add-doctor-name');
  const name = input ? input.value.trim() : '';
  if (!name) { if (input) input.focus(); return; }
  if (STATE.doctors.some(d => d.name.toLowerCase() === name.toLowerCase())) {
    showToast('Doctor already exists'); return;
  }
  const doc = defaultStateDoctor();
  doc.name = name;
  STATE.doctors.push(doc);
  saveState();
  renderWizardDoctors();
  renderDoctorAccordion();
  updateWizardSummary();
  updateBlackoutDoctorSelect();
  renderQuickSetupSummary();
  if (input) { input.value = ''; input.focus(); }
  showToast(`Added ${name}`);
}

async function removeDoctor(id) {
  const doc = STATE.doctors.find(d => d.id === id);
  const name = doc ? doc.name : 'this doctor';
  if (!(await confirmAction(`Remove ${name}? This will also clear their time-off data.`))) return;
  _saveUndoSnapshot();
  STATE.doctors = STATE.doctors.filter(d => d.id !== id);
  for (const mk of Object.keys(STATE.blackouts)) {
    delete STATE.blackouts[mk][id];
    if (Object.keys(STATE.blackouts[mk]).length === 0) delete STATE.blackouts[mk];
  }
  saveState();
  renderWizardDoctors();
  renderDoctorAccordion();
  updateWizardSummary();
  updateBlackoutDoctorSelect();
  refreshBlackoutCalendar();
  renderQuickSetupSummary();
  _showUndoToast(`${name} removed`);
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
  if (!name) { if (input) input.focus(); return; }
  if (STATE.offices.some(o => o.name.toLowerCase() === name.toLowerCase())) {
    showToast('Office already exists'); return;
  }
  const id = 'off_' + generateId().slice(0, 5);
  const office = {
    id, name, isHospital: STATE.offices.length === 0,
    maxPerShift: 2, restrictedTuesdayMax: 1, locationAddress: ''
  };
  STATE.offices.push(office);
  saveState();
  renderWizardOffices();
  updateWizardSummary();
  renderQuickSetupSummary();
  if (input) { input.value = ''; input.focus(); }
  showToast(`Added ${name}`);
}

function updateOfficeField(officeId, field, value) {
    const office = STATE.offices.find(o => o.id === officeId);
    if (!office) return;
    office[field] = value;
    saveState();
    if (field === 'isHospital' || field === 'name') renderWizardOffices();
    if (field === 'isHospital' || field === 'name') renderDoctorAccordion();
    updateWizardSummary();
}

async function removeOffice(id) {
  const off = STATE.offices.find(o => o.id === id);
  const name = off ? off.name : 'this office';
  if (!(await confirmAction(`Remove ${name}?`))) return;
  _saveUndoSnapshot();
  STATE.offices = STATE.offices.filter(o => o.id !== id);
  saveState();
  renderWizardOffices();
  updateWizardSummary();
  renderQuickSetupSummary();
  renderDoctorAccordion();
  _showUndoToast(`${name} removed`);
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

let _generateLock = false;

async function handleGenerate() {
  const year = parseInt(document.getElementById('wiz-year')?.value || 2026);
  const month = parseInt(document.getElementById('wiz-month')?.value || 8);
  const timeout = STATE.settings.solverTimeLimitSeconds || 900;
  const statusEl = document.getElementById('gen-status');
  const btn = document.getElementById('btn-generate');

  if (_generateLock) return;
  if (isNaN(year) || year < 2020 || year > 2099) {
    statusEl.innerHTML = '<span class="err">Enter a valid year (2020-2099).</span>';
    document.getElementById('wiz-year')?.focus();
    return;
  }

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
  _generateLock = true;
  const panel = document.getElementById('conflict-panel');
  const list = document.getElementById('conflict-list');
  panel?.classList.add('hidden');
  const t0 = performance.now();

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
		wizViewYear = year;
		wizViewMonth = month;

      const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
      statusEl.innerHTML = result.partial
        ? `<span class="err">Schedule created with ${result.unmetConstraints?.length || 0} issues (${elapsed}s). Review below.</span>`
        : `<span class="ok">&#10003; Schedule generated in ${elapsed}s</span>`;
      if (btn && !result.partial) { btn.classList.add('flash-success'); setTimeout(() => btn.classList.remove('flash-success'), 700); }

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
    _generateLock = false;
    if (btn) btn.disabled = false;
  }
}

// ── Schedule view ───────────────────────────────────────────────────────────

function updateCalendarView() {
  const container = document.getElementById('calendar-container');
  if (!container) return;
  const mk = getMonthKey(currentScheduleYear, currentScheduleMonth);
  const data = STATE.schedules[mk];
  if (!data) {
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#128197;</div><div class="empty-state-title">No schedule yet</div><div class="empty-state-desc">Go to Setup &rarr; Generate to create a schedule for this month.</div></div>';
    updateScheduleDisplay(null);
    return;
  }
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
  const unfilledEl = document.getElementById('sched-unfilled');
  if (unfilledEl) {
    const totalSlots = data?.slots?.length || 0;
    const filledSlots = data?.assignments?.length || 0;
    const unfilled = totalSlots - filledSlots;
    unfilledEl.textContent = unfilled > 0 ? String(unfilled) : '0';
    unfilledEl.className = 'stat-val' + (unfilled > 0 ? ' val-warn' : totalSlots > 0 ? ' val-ok' : '');
  }
}

function changeScheduleMonth(delta) {
  currentScheduleMonth += delta;
  if (currentScheduleMonth > 11) { currentScheduleMonth = 0; currentScheduleYear++; }
  if (currentScheduleMonth < 0) { currentScheduleMonth = 11; currentScheduleYear--; }
  updateCalendarView();
}

async function handleClearMonth() {
  const mk = getMonthKey(currentScheduleYear, currentScheduleMonth);
  if (!STATE.schedules[mk]) return;
  if (!(await confirmAction('Clear the schedule for ' + MONTHS[currentScheduleMonth] + ' ' + currentScheduleYear + '?'))) return;
  _saveUndoSnapshot();
  delete STATE.schedules[mk];
  updateTotalsFromSchedule({});
  saveState();
  updateCalendarView();
  updateBalanceTable();
  updateDataStatus();
  const wizContainer = document.getElementById('wiz-calendar-container');
  if (wizContainer && wizViewYear === currentScheduleYear && wizViewMonth === currentScheduleMonth) {
    wizContainer.innerHTML = '';
    const wizPreview = document.getElementById('wiz-schedule-preview');
    if (wizPreview) wizPreview.classList.add('hidden');
    updateWizScheduleDisplay(null);
  }
  _showUndoToast('Schedule cleared');
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
        wrapper.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#9878;</div><div class="empty-state-title">No balance data</div><div class="empty-state-desc">Generate a schedule to see the cumulative balance report.</div></div>';
        if (monthsWrapper) monthsWrapper.innerHTML = '';
        return;
    }

    const doctors = STATE.doctors;
    const nonHosp = STATE.offices.filter(o => !o.isHospital);
    const callCols = ['Wk Day', 'Wk Night', 'Fri Night', 'Wknd'];
    const sessCols = ['Sessions', 'AM', 'PM', 'Late'];
    const officeCols = nonHosp.map(o => o.name);

    let html = '<div class="balance-sheet"><table class="sheet-table balance-table">';
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
        const latestMk = Object.keys(STATE.schedules).sort().pop();
        const mc = latestMk ? STATE.schedules[latestMk]?.counts?.[doc.id] : null;
        const prefRate = mc?.preferredDayCallRate;
        html += `<td>${prefRate != null ? (prefRate * 100).toFixed(0) + '%' : '—'}</td>`;
        html += '</tr>';
    }

    const gini = calculateGiniFromTotals();
    html += `<tr class="gini-row"><td>Call Fairness</td>`;
    html += `<td class="${gini > 0.10 ? 'gini-warn' : 'gini-ok'}" colspan="4">${gini <= 0.10 ? 'Fair' : 'Uneven'} (${gini.toFixed(3)})</td>`;
    html += '<td colspan="5"></td>';
    for (const o of officeCols) html += '<td></td>';
    html += '<td></td></tr></tbody></table></div>';
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
		weekendCallOff: ['true','1','yes'].includes(String(row.weekendCallOff || row.weekend_call_off).toLowerCase()),
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
			if (!imported.length) { alertMsg('No valid doctors found.'); return; }
			const importedIds = new Set(imported.map(d => d.id));
			const kept = STATE.doctors.filter(d => !importedIds.has(d.id));
			STATE.doctors = [...kept, ...imported];
			saveState();
			renderWizardDoctors();
			renderDoctorAccordion();
			updateWizardSummary();
			updateBlackoutDoctorSelect();
			updateBalanceTable();
			alertMsg(`Imported ${imported.length} doctor(s)`);
		} catch (err) { alertMsg('Import failed: ' + err.message); }
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
			if (!imported.length) { alertMsg('No valid offices found.'); return; }
			if (!imported.some(o => o.isHospital)) imported[0].isHospital = true;
			const importedIds = new Set(imported.map(o => o.id));
			const kept = STATE.offices.filter(o => !importedIds.has(o.id));
			STATE.offices = [...kept, ...imported];
			saveState();
			renderWizardOffices();
			updateWizardSummary();
			alertMsg(`Imported ${imported.length} office(s)`);
		} catch (err) { alertMsg('Import failed: ' + err.message); }
	};
	reader.readAsText(file);
}

function handleExportDoctors() {
  const headers = ['name','id','hospitalCallEligible','surgicalAssistEligible','weekendCallOff','requiredSessionsPerWeek','maxWeekdayDayCalls','maxWeekdayNightCalls','maxFridayNightCalls','maxWeekendBlocks','preferredCallDays','standingDaysOff','allowedOffices'];
  let csv = headers.map(h => `"${h}"`).join(',') + '\n';
  for (const doc of STATE.doctors) {
    csv += [ `"${doc.name}"`, doc.id, doc.hospitalCallEligible, doc.surgicalAssistEligible, doc.weekendCallOff,
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
	} catch (e) { await alertMsg('Export failed: ' + e.message); }
}

async function handleImportBalance() {
	const input = document.getElementById('import-balance-file');
	if (!input?.files?.length) return;
	try {
		const result = await apiImportBalance(input.files[0]);
		for (const [docId, data] of Object.entries(result)) STATE.totals[docId] = data;
		saveState();
		updateBalanceTable();
		alertMsg('Balance imported');
	} catch (e) { alertMsg('Import failed: ' + e.message); }
}

async function handleExportSchedule() {
	const mk = getMonthKey(currentScheduleYear, currentScheduleMonth);
	const data = STATE.schedules[mk];
	if (!data) { alertMsg('No schedule for this month'); return; }
	try {
		const csv = await apiExportSchedule(currentScheduleYear, currentScheduleMonth, data.assignments);
		downloadBlob(csv, `schedule-${mk}.csv`);
	} catch (e) { alertMsg('Export failed: ' + e.message); }
}

function downloadBlob(content, filename) {
 	const blob = new Blob([content], { type: 'text/csv' });
 	const url = URL.createObjectURL(blob);
 	const a = document.createElement('a');
 	a.href = url; a.download = filename; a.click();
 	setTimeout(() => URL.revokeObjectURL(url), 2000);
 }

 function toggleExportDropdown(btn) {
 	const dropdown = btn.closest('.export-dropdown');
 	const menu = dropdown.querySelector('.dropdown-menu');
 	const isOpen = menu.classList.toggle('open');
 	btn.setAttribute('aria-expanded', String(isOpen));
 }

 function closeExportDropdowns() {
 	document.querySelectorAll('.dropdown-menu.open').forEach(m => m.classList.remove('open'));
 	document.querySelectorAll('.dropdown-toggle[aria-expanded="true"]').forEach(b => b.setAttribute('aria-expanded', 'false'));
 }

 function handleDownloadICS() {
 	closeExportDropdowns();
 	const activeTab = document.querySelector('.tab-pane.active');
 	let year, month, data;
 	if (activeTab?.id === 'tab-schedule') {
 		year = currentScheduleYear; month = currentScheduleMonth;
 		const mk = getMonthKey(year, month);
 		data = STATE.schedules[mk];
 	} else {
 		year = wizViewYear; month = wizViewMonth;
 		const mk = getMonthKey(year, month);
 		data = STATE.schedules[mk];
 	}
 	if (!data) { alertMsg('No schedule to export.'); return; }
 	downloadICS(year, month, data);
 }

 function handleOpenGoogleCalendar() {
 	closeExportDropdowns();
 	let year, month, data;
 	if (document.querySelector('#tab-schedule.active')) {
 		year = currentScheduleYear; month = currentScheduleMonth;
 		const mk = getMonthKey(year, month);
 		data = STATE.schedules[mk];
 	} else {
 		year = wizViewYear; month = wizViewMonth;
 		const mk = getMonthKey(year, month);
 		data = STATE.schedules[mk];
 	}
 	if (!data) { alertMsg('No schedule to export.'); return; }
 	openGoogleCalendar(year, month, data);
 }

 document.addEventListener('click', e => {
 	if (!e.target.closest('.export-dropdown')) closeExportDropdowns();
 });

// ── Tab switching ────────────────────────────────────────────────────────────

function switchTab(tabName) {
	document.querySelectorAll('.tab-btn').forEach(btn => {
		const isActive = btn.dataset.tab === tabName;
		btn.classList.toggle('active', isActive);
		btn.setAttribute('aria-selected', isActive);
	});
	document.querySelectorAll('.tab-pane').forEach(pane =>
		pane.classList.toggle('active', pane.id === 'tab-' + tabName)
	);
	const mainEl = document.querySelector('main');
	if (mainEl) mainEl.scrollTop = 0;
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

function safeRender(label, fn, fallbackHTML) {
  try {
    fn();
  } catch (err) {
    console.error('[safeRender] ' + label + ' failed:', err);
    if (typeof logError === 'function') logError('render_error', err.message, { label, stack: err.stack });
    if (fallbackHTML !== undefined) {
      const el = document.querySelector('[data-render-target="' + label + '"]') ||
                 document.getElementById('wiz-' + label) ||
                 document.getElementById(label + '-container') ||
                 document.getElementById('doctor-accordion') ||
                 document.getElementById('balance-table-wrapper');
      if (el) el.innerHTML = fallbackHTML;
    }
    showToast('Something went wrong displaying ' + label + '. Try reloading.', 4000);
  }
}

function showStaleDataWarning() {
  if (typeof isDataStale !== 'function') return;
  if (!isDataStale(60 * 60 * 1000)) return;
  const existing = document.getElementById('stale-data-banner');
  if (existing) return;
  const banner = document.createElement('div');
  banner.id = 'stale-data-banner';
  banner.className = 'conn-banner conn-banner-warn';
  banner.setAttribute('role', 'alert');
  banner.innerHTML = '<span class="conn-banner-icon">&#9200;</span><span class="conn-banner-msg">Viewing older data — reconnect to sync latest</span><button class="conn-banner-dismiss btn btn-sm btn-ghost" onclick="this.closest(\'#stale-data-banner\').remove()">&times;</button>';
  const header = document.querySelector('.app-header');
  if (header) header.insertAdjacentElement('afterend', banner);
}

function handleBackupState() {
  const blob = new Blob([JSON.stringify(STATE, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'callsched-backup-' + new Date().toISOString().slice(0, 10) + '.json'; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  showToast('Backup downloaded');
}

function handleRestoreState(file) {
  const reader = new FileReader();
  reader.onload = function(e) {
    try {
      const parsed = JSON.parse(e.target.result);
      if (!parsed.doctors && !parsed.schedules) {
        alertMsg('Invalid backup file — missing doctors or schedules.');
        return;
      }
      _saveUndoSnapshot();
      _mergeDefaults(parsed);
      STATE = parsed;
      migrateBlackoutFormat();
      saveState();
      refreshUI();
      showToast('Backup restored — changes saved');
    } catch (err) {
      alertMsg('Failed to restore backup: ' + err.message);
    }
  };
  reader.readAsText(file);
}

function showSnapshotsModal() {
  const snaps = typeof getSnapshots === 'function' ? getSnapshots() : [];
  if (!snaps.length) {
    alertMsg('No backups yet. Backups are created automatically every 10 minutes when the app is open.');
    return;
  }
  const rows = snaps.map((s, i) => {
    const date = new Date(s.ts).toLocaleString();
    return `<tr><td>${i + 1}</td><td>${date}</td><td>${s.doctorCount} docs</td><td>${s.scheduleMonths} months</td><td>${s.sizeKB}KB</td><td><button class="btn btn-sm btn-ghost" onclick="restoreSnapshotFromModal('${s.key}')">Restore</button></td></tr>`;
  }).join('');
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `<div class="modal-box" style="max-width:520px;width:95vw;">
    <div class="modal-body" style="padding:0;">
      <h3 style="padding:1rem 1rem 0.5rem;font-size:1rem;">Backups</h3>
      <p style="padding:0 1rem 0.75rem;color:var(--text-muted);font-size:0.8rem;">Restoring a backup replaces current data. This can be undone.</p>
      <table class="sheet-table" style="width:100%;font-size:0.8rem;">
        <thead><tr><th>#</th><th>Date</th><th>Doctors</th><th>Months</th><th>Size</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="modal-actions"><button class="btn btn-ghost modal-ok">Close</button></div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('.modal-ok').addEventListener('click', () => overlay.remove());
  overlay.addEventListener('keydown', e => { if (e.key === 'Escape') overlay.remove(); });
}

function restoreSnapshotFromModal(key) {
  if (typeof restoreSnapshot !== 'function') return;
  try {
    _saveUndoSnapshot();
    restoreSnapshot(key);
    refreshUI();
    showToast('Backup restored');
    document.querySelectorAll('.modal-overlay').forEach(el => el.remove());
  } catch (err) {
    alertMsg('Restore failed: ' + err.message);
  }
}

function getSyncQueueStatus() {
  if (typeof getSyncQueueSize !== 'function') return '';
  const n = getSyncQueueSize();
  if (n === 0) return '';
  return ' · ' + n + ' pending sync';
}

function updateScheduleDisplaySafe(data) {
  safeRender('schedule-display', () => updateScheduleDisplay(data));
}

function updateBalanceTableSafe() {
  safeRender('balance-table', () => updateBalanceTable());
}

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

    // Wizard step dots clickable — click step-item (dot + label)
    document.querySelectorAll('.step-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.stopPropagation();
            const step = parseInt(item.dataset.step);
            if (step) showWizardStep(step);
        });
        item.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                const step = parseInt(item.dataset.step);
                if (step) showWizardStep(step);
            }
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

	// Balance export/import/backup
	document.getElementById('btn-export-balance')?.addEventListener('click', handleExportBalance);
	document.getElementById('import-balance-file')?.addEventListener('change', handleImportBalance);
	document.getElementById('btn-backup-state')?.addEventListener('click', handleBackupState);
	document.getElementById('import-backup-file')?.addEventListener('change', function() {
		if (this.files.length) { handleRestoreState(this.files[0]); this.value = ''; }
	});
	document.getElementById('btn-view-snapshots')?.addEventListener('click', showSnapshotsModal);

	// API health check
	apiHealth()
		.then(() => {
			const el = document.getElementById('api-status');
			if (el) { el.innerHTML = '<span class="api-dot online"></span>API Online'; el.className = 'api-online'; }
		})
		.catch(() => {
			const el = document.getElementById('api-status');
			if (el) { el.innerHTML = '<span class="api-dot offline"></span>API Offline'; el.className = 'api-offline'; }
		});

	updateDataStatus();
	showStaleDataWarning();

	const syncStatus = getSyncQueueStatus();
	if (syncStatus) {
		const dataEl = document.getElementById('data-status');
		if (dataEl) dataEl.textContent += syncStatus;
		showToast('Some changes are pending sync — will upload when connected', 4000);
	}
});