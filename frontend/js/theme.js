/* =========================
   Theme Loader — Must run before all other scripts
   Loads tenant theme config and applies before first paint
   ========================= */

const THEME_CONFIG = (function() {
  const DEFAULT_CONFIG = {
    id: 'default',
    name: 'Call Scheduler',
    tagline: 'Automated on-call scheduling for medical practices',
    logoUrl: null,
    faviconEmoji: '📋',
    faviconUrl: null,
    footer: null,
    colors: null,
    avatarColors: null
  };

  function deepMerge(base, override) {
    if (!override) return base;
    const result = {};
    for (const key in base) {
      if (override.hasOwnProperty(key) && typeof base[key] === 'object' && base[key] !== null && !Array.isArray(base[key])) {
        result[key] = deepMerge(base[key], override[key]);
      } else if (override[key] !== undefined) {
        result[key] = override[key];
      } else {
        result[key] = base[key];
      }
    }
    for (const key in override) {
      if (!result.hasOwnProperty(key)) result[key] = override[key];
    }
    return result;
  }

  function getTenantId() {
    const params = new URLSearchParams(window.location.search);
    const urlTenant = params.get('tenant');
    if (urlTenant) return urlTenant;
    try {
      const cached = localStorage.getItem('theme_id');
      if (cached) return cached;
    } catch(e) {}
    return 'default';
  }

  function loadConfigFile(tenantId, callback) {
    if (tenantId === 'default') {
      try {
        const stored = localStorage.getItem('theme_default');
        if (stored) {
          try { callback(JSON.parse(stored)); return; } catch(e) {}
        }
      } catch(e) {}
    }
    const xhr = new XMLHttpRequest();
    xhr.overrideMimeType('application/json');
    xhr.open('GET', 'theme-config.json', false);
    xhr.onload = function() {
      if (xhr.status === 200) {
        try {
          const parsed = JSON.parse(xhr.responseText);
          try { localStorage.setItem('theme_default', xhr.responseText); } catch(e) {}
          callback(parsed);
          return;
        } catch(e) {}
      }
      callback(null);
    };
    xhr.onerror = function() { callback(null); };
    xhr.send();
  }

  function applyConfig(config) {
    if (!config) return;

    if (config.name) {
      const h1 = document.querySelector('.app-header h1');
      if (h1) {
        if (config.logoUrl) {
          h1.innerHTML = '<img src="' + config.logoUrl + '" alt="' + escHtml(config.name) + '" class="theme-logo" />';
        } else {
          const parts = config.name.split(' ');
          if (parts.length > 1) {
            h1.innerHTML = escHtml(parts[0]) + '<span>' + escHtml(parts.slice(1).join(' ')) + '</span>';
          } else {
            h1.textContent = config.name;
          }
        }
      }
      document.title = config.name;
    }

    if (config.faviconUrl) {
      const existing = document.querySelector('link[rel="icon"]');
      if (existing) existing.href = config.faviconUrl;
      else {
        const link = document.createElement('link');
        link.rel = 'icon';
        link.href = config.faviconUrl;
        document.head.appendChild(link);
      }
    } else if (config.faviconEmoji) {
      const encoded = encodeURIComponent(config.faviconEmoji);
      const svgDataUri = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">' + encoded + '</text></svg>';
      let iconLink = document.querySelector('link[rel="icon"]');
      if (!iconLink) {
        iconLink = document.createElement('link');
        iconLink.rel = 'icon';
        document.head.appendChild(iconLink);
      }
      iconLink.href = svgDataUri;
      const metaTheme = document.querySelector('meta[name="theme-color"]');
      if (config.colors && config.colors['--bg-primary']) {
        if (metaTheme) metaTheme.content = config.colors['--bg-primary'];
      }
    }

    if (config.footer) {
      const footer = document.querySelector('.app-footer');
      if (footer) {
        const statusSpan = footer.querySelector('#api-status');
        footer.innerHTML = '';
        const txt = document.createElement('span');
        txt.textContent = config.footer;
        footer.appendChild(txt);
        if (statusSpan) {
          footer.appendChild(document.createTextNode(' · '));
          footer.appendChild(statusSpan);
        }
      }
    }

    if (config.colors) {
      for (const [prop, value] of Object.entries(config.colors)) {
        if (prop.startsWith('--')) {
          document.documentElement.style.setProperty(prop, value);
        }
      }
    }
  }

  function escHtml(text) {
    const d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
  }

  const tenantId = getTenantId();
  let finalConfig = Object.assign({}, DEFAULT_CONFIG);

  try {
    const storedKey = 'theme_' + tenantId;
    const stored = localStorage.getItem(storedKey);
    if (stored) {
      try {
        finalConfig = deepMerge(finalConfig, JSON.parse(stored));
        applyConfig(finalConfig);
      } catch(e) {}
    }
  } catch(e) {}

  const xhr = new XMLHttpRequest();
  xhr.open('GET', 'theme-config.json', false);
  xhr.send();
  if (xhr.status === 200 && xhr.responseText) {
    try {
      const loaded = JSON.parse(xhr.responseText);
      finalConfig = deepMerge(finalConfig, loaded);
      applyConfig(finalConfig);
    } catch(e) {}
  }

  try { localStorage.setItem('theme_id', tenantId); } catch(e) {}

  return finalConfig;
})();

function applyThemeConfig(config) {
  if (!config) return;
  if (config.colors) {
    for (const [prop, value] of Object.entries(config.colors)) {
      if (prop.startsWith('--')) {
        document.documentElement.style.setProperty(prop, value);
      }
    }
  }
}