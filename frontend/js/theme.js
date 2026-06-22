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

  function escHtml(text) {
    const d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
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

  function applyColors(config) {
    if (!config || !config.colors) return;
    for (const [prop, value] of Object.entries(config.colors)) {
      if (prop.startsWith('--')) {
        document.documentElement.style.setProperty(prop, value);
      }
    }
  }

  function applyFavicon(config) {
    if (!config) return;
    if (config.faviconUrl) {
      let iconLink = document.querySelector('link[rel="icon"]');
      if (!iconLink) {
        iconLink = document.createElement('link');
        iconLink.rel = 'icon';
        document.head.appendChild(iconLink);
      }
      iconLink.href = config.faviconUrl;
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
    }
    if (config.colors && config.colors['--bg-primary']) {
      const metaTheme = document.querySelector('meta[name="theme-color"]');
      if (metaTheme) metaTheme.content = config.colors['--bg-primary'];
    }
  }

  function applyDOM(config) {
    if (!config) return;
    if (config.name) {
      document.title = config.name;
      const h1 = document.querySelector('.app-header h1');
      if (h1) {
        if (config.logoUrl) {
          h1.innerHTML = '<img src="' + escHtml(config.logoUrl) + '" alt="' + escHtml(config.name) + '" class="theme-logo" />';
        } else {
          const parts = config.name.split(' ');
          if (parts.length > 1) {
            h1.innerHTML = escHtml(parts[0]) + '<span>' + escHtml(parts.slice(1).join(' ')) + '</span>';
          } else {
            h1.textContent = config.name;
          }
        }
      }
    }
    if (config.footer !== null && config.footer !== undefined) {
      const footer = document.getElementById('app-footer');
      if (footer) {
        const statusSpan = document.getElementById('api-status');
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
  }

  const tenantId = getTenantId();
  let finalConfig = Object.assign({}, DEFAULT_CONFIG);

  try { localStorage.setItem('theme_id', tenantId); } catch(e) {}

  try {
    const storedKey = 'theme_' + tenantId;
    const stored = localStorage.getItem(storedKey);
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        finalConfig = deepMerge(finalConfig, parsed);
        applyColors(finalConfig);
        applyFavicon(finalConfig);
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
      applyColors(finalConfig);
      applyFavicon(finalConfig);
    } catch(e) {}
  }

  document.addEventListener('DOMContentLoaded', function() {
    applyDOM(finalConfig);
  });

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
  if (config.name) document.title = config.name;
  const h1 = document.querySelector('.app-header h1');
  if (h1 && config.name) {
    if (config.logoUrl) {
      const d = document.createElement('div');
      d.textContent = config.name;
      h1.innerHTML = '<img src="' + escHtml(config.logoUrl) + '" alt="' + escHtml(d.innerHTML) + '" class="theme-logo" />';
    } else {
      const parts = config.name.split(' ');
      if (parts.length > 1) {
        h1.innerHTML = escHtml(parts[0]) + '<span>' + escHtml(parts.slice(1).join(' ')) + '</span>';
      } else {
        h1.textContent = config.name;
      }
    }
  }
  if (config.footer !== null && config.footer !== undefined) {
    const footer = document.getElementById('app-footer');
    if (footer) {
      const statusSpan = document.getElementById('api-status');
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
}

function escHtml(text) {
  const d = document.createElement('div');
  d.textContent = text || '';
  return d.innerHTML;
}