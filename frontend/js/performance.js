/* =========================
   Performance Monitoring
   Time-to-interactive, render timing, calendar perf marks
   ========================= */

const PERF = {
  marks: {},

  mark(label) {
    this.marks[label] = performance.now();
    if (typeof performance.mark === 'function') {
      try { performance.mark('callsched-' + label); } catch(e) {}
    }
  },

  measure(label, startMark, endMark) {
    const start = this.marks[startMark] || 0;
    const end = endMark ? (this.marks[endMark] || performance.now()) : performance.now();
    const duration = end - start;
    if (typeof performance.measure === 'function') {
      try {
        performance.measure('callsched-' + label, 'callsched-' + startMark);
      } catch(e) {}
    }
    return duration;
  },

  getEntries() {
    if (typeof performance.getEntriesByType === 'function') {
      return performance.getEntriesByType('resource').filter(e =>
        e.name.includes(window.location.origin)
      );
    }
    return [];
  },

  getTimings() {
    const result = {};
    for (const [label, time] of Object.entries(this.marks)) {
      result[label] = Math.round(time * 100) / 100;
    }
    return result;
  },

  getResourceTiming(urlPattern) {
    const entries = this.getEntries();
    return entries.filter(e => e.name.includes(urlPattern));
  },
};

// Mark key lifecycle events
PERF.mark('page_load');
PERF.mark('dom_ready');

document.addEventListener('DOMContentLoaded', () => {
  PERF.mark('dom_content_loaded');
  const navTiming = PERF.getResourceTiming('/api/health').find(e => e.responseStart > 0);
  if (navTiming) {
    PERF.marks['ttfb'] = navTiming.responseStart;
  }
});

window.addEventListener('load', () => {
  PERF.mark('window_load');
});

window.addEventListener('load', () => {
  setTimeout(() => {
    PERF.marks['tti'] = performance.now();
    if (typeof console === 'object' && console.log) {
      const tti = Math.round(PERF.marks['tti'] || 0);
      const timings = PERF.getTimings();
      console.log('[Perf] TTI:', tti + 'ms', '|', JSON.stringify(timings));
    }
  }, 0);
});

// ── Calendar render timing helper ──────────────────────────────────────────
function measureRender(label, fn, ...args) {
  const t0 = performance.now();
  const result = fn(...args);
  const ms = performance.now() - t0;
  PERF.marks['render_' + label] = ms;
  console.log('[Perf] render.' + label + ':', Math.round(ms) + 'ms');
  return result;
}