const { test, expect, beforeEach } = require('@playwright/test');

const BASE = 'http://localhost:5000';

async function dismissAuthOverlay(page) {
  try {
    const overlay = page.locator('#auth-overlay');
    if (await overlay.isVisible({ timeout: 2000 })) {
      await overlay.evaluate(el => el.style.display = 'none');
    }
  } catch (e) {}
}

test.describe('Call Scheduler — Smoke Tests', () => {

  test.beforeEach(async ({ page }) => {
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    page.on('pageerror', err => errors.push(err.message));

    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.waitForSelector('#root', { timeout: 10000 });

    // Clear console error stash for non-critical errors
    page._consoleErrors = errors;
  });

  test('page loads without console errors', async ({ page }) => {
    await page.waitForSelector('.app-header h1', { timeout: 10000 });

    const criticalErrors = page._consoleErrors.filter(e =>
      !e.includes('favicon') &&
      !e.includes('manifest') &&
      !e.includes('sw.js') &&
      !e.includes('service worker') &&
      !e.includes('Failed to register') &&
      !e.includes('net::ERR')
    );
    expect(criticalErrors, 'Console errors: ' + criticalErrors.join('; ')).toHaveLength(0);
  });

  test('app renders header and tabs', async ({ page }) => {
    await page.waitForSelector('.app-header h1', { timeout: 10000 });

    const h1 = await page.textContent('.app-header h1');
    expect(h1).toBeTruthy();

    const tabs = await page.$$('.tab-btn');
    expect(tabs.length).toBeGreaterThanOrEqual(4);
  });

  test('tab navigation works after auth overlay handled', async ({ page }) => {
    await page.waitForSelector('.app-header', { timeout: 10000 });
    await dismissAuthOverlay(page);

    await page.click('[data-tab="doctors"]');
    await page.waitForSelector('#tab-doctors.active', { timeout: 5000 });

    await page.click('[data-tab="schedule"]');
    await page.waitForSelector('#tab-schedule.active', { timeout: 5000 });

    await page.click('[data-tab="balance"]');
    await page.waitForSelector('#tab-balance.active', { timeout: 5000 });

    await page.click('[data-tab="setup"]');
    await page.waitForSelector('#tab-setup.active', { timeout: 5000 });
  });

  test('wizard step navigation works', async ({ page }) => {
    await page.waitForSelector('.wizard-step', { timeout: 10000 });
    await dismissAuthOverlay(page);

    await page.click('#wstep-1 button:text("Next: Doctors")');
    await page.waitForSelector('#wstep-2:not(.hidden)', { timeout: 5000 });

    await page.click('#wstep-2 button:text("Next: Offices")');
    await page.waitForSelector('#wstep-3:not(.hidden)', { timeout: 5000 });

    await page.click('#wstep-3 .wizard-nav .btn-ghost');
    await page.waitForSelector('#wstep-2:not(.hidden)', { timeout: 5000 });
  });

  test('can add a doctor via quick-add', async ({ page }) => {
    await page.waitForSelector('.wizard-step', { timeout: 10000 });
    await dismissAuthOverlay(page);

    await page.click('button:text("Next: Doctors")');
    await page.waitForSelector('#wstep-2:not(.hidden)', { timeout: 5000 });

    const input = page.locator('#quick-add-doctor-name');
    await input.fill('Dr. Test Smith');
    await page.click('button:text("+ Add Doctor")');
    await page.waitForTimeout(500);

    const doctorText = await page.textContent('#wiz-doctors-list');
    expect(doctorText).toContain('Dr. Test Smith');
  });

  test('add doctor from Doctors tab', async ({ page }) => {
    await page.waitForSelector('.app-header', { timeout: 10000 });
    await dismissAuthOverlay(page);

    await page.click('[data-tab="doctors"]');
    await page.waitForSelector('#tab-doctors.active', { timeout: 5000 });

    await page.locator('#doctor-accordion ~ button.btn-add').click();
    await page.waitForTimeout(500);

    const accordion = page.locator('#doctor-accordion');
    await expect(accordion).not.toBeEmpty();
  });

  test('offline page exists and is accessible', async ({ page }) => {
    const res = await page.request.get(BASE + '/offline.html');
    expect(res.status()).toBe(200);
    const html = await res.text();
    expect(html).toContain('Offline');
    expect(html).toContain('Call Scheduler');
  });

  test('manifest.json is valid and has required fields', async ({ page }) => {
    const res = await page.request.get(BASE + '/manifest.json');
    expect(res.status()).toBe(200);
    const manifest = await res.json();
    expect(manifest.name).toBeTruthy();
    expect(manifest.short_name).toBeTruthy();
    expect(manifest.start_url).toBe('/');
    expect(manifest.display).toBe('standalone');
    expect(manifest.icons).toBeTruthy();
    expect(manifest.icons.length).toBeGreaterThan(0);
  });

  test('service worker file is accessible', async ({ page }) => {
    const res = await page.request.get(BASE + '/sw.js');
    expect(res.status()).toBe(200);
    const sw = await res.text();
    expect(sw).toContain('addEventListener');
    expect(sw).toContain('fetch');
    expect(sw).toContain('Cache');
  });

  test('theme-config.json is accessible', async ({ page }) => {
    const res = await page.request.get(BASE + '/theme-config.json');
    expect(res.status()).toBe(200);
    const config = await res.json();
    expect(config.name).toBeTruthy();
    expect(config.id).toBeTruthy();
  });

  test('API health check returns expected shape', async ({ page }) => {
    const res = await page.request.get(BASE + '/api/health');
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(data).toBeTruthy();
  });

  test('schedule tab shows empty state when no schedule generated', async ({ page }) => {
    await page.waitForSelector('.app-header', { timeout: 10000 });
    await dismissAuthOverlay(page);

    await page.click('[data-tab="schedule"]');
    await page.waitForTimeout(1000);

    const activePane = page.locator('#tab-schedule.active');
    await expect(activePane).toBeVisible({ timeout: 5000 });

    const emptyState = page.locator('#tab-schedule.active .empty-state');
    await expect(emptyState).toBeVisible({ timeout: 5000 });
    const text = await emptyState.textContent();
    expect(text).toContain('No schedule');
  });

  test('connection indicator shows API status', async ({ page }) => {
    await page.waitForSelector('.app-header', { timeout: 10000 });
    await dismissAuthOverlay(page);

    const apiStatus = page.locator('#api-status');
    await expect(apiStatus).toBeVisible({ timeout: 5000 });
    const statusText = await apiStatus.textContent();
    expect(statusText).toMatch(/API (Online|Offline|Checking)/);
  });

  test('wizard step 4 shows generate UI', async ({ page }) => {
    await page.waitForSelector('.wizard-step', { timeout: 10000 });
    await dismissAuthOverlay(page);

    await page.click('#wstep-1 button:text("Next: Doctors")');
    await page.waitForSelector('#wstep-2:not(.hidden)', { timeout: 5000 });
    await page.click('#wstep-2 button:text("Next: Offices")');
    await page.waitForSelector('#wstep-3:not(.hidden)', { timeout: 5000 });
    await page.click('#wstep-3 button:text("Next: Availability")');
    await page.waitForSelector('#wstep-4:not(.hidden)', { timeout: 5000 });

    const genBtn = page.locator('#btn-generate');
    await expect(genBtn).toBeVisible({ timeout: 5000 });
    await expect(genBtn).toContainText('Generate');

    const blackoutSelect = page.locator('#blackout-doctor-select');
    await expect(blackoutSelect).toBeVisible({ timeout: 3000 });
  });

  test('export dropdown opens and has options', async ({ page }) => {
    await page.waitForSelector('.app-header', { timeout: 10000 });
    await dismissAuthOverlay(page);

    await page.click('[data-tab="schedule"]');
    await page.waitForTimeout(800);

    const activeTab = page.locator('#tab-schedule.active');
    await expect(activeTab).toBeVisible({ timeout: 5000 });

    const dropdown = page.locator('#tab-schedule.active .export-dropdown .dropdown-toggle');
    await dropdown.scrollIntoViewIfNeeded();
    await dropdown.click();
    await page.waitForSelector('#tab-schedule.active .dropdown-menu.open', { timeout: 5000 });

    const items = await page.$$('#tab-schedule.active .dropdown-item');
    expect(items.length).toBeGreaterThanOrEqual(3);
  });
});