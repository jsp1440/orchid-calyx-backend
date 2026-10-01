// Edith Bramble live-runtime journeys and accessibility, executed with Playwright
// on a GitHub-hosted runner against the registered Famous runtime.
//
// Usage: node edith_runtime_journeys.mjs <runtime-url> <out.json>
//
// Writes CertificationGate objects. Every journey is attempted at desktop, iPad
// (touch) and phone viewports; a journey PASSes only if it passes on all three.
// Accessibility uses axe-core (WCAG 2.0/2.1/2.2 A+AA); serious or critical
// violations FAIL. A journey that cannot run is BLOCKED, never PASS. Read-only:
// no sign-up, sign-in, form submission or other state change is performed.

import { writeFileSync } from 'node:fs';
import { chromium, devices } from 'playwright';
import { AxeBuilder } from '@axe-core/playwright';

const [, , runtimeArg, outPath] = process.argv;
const RUNTIME = runtimeArg.replace(/\/$/, '');
const TIMEOUT = 45_000;

const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 } },
  ipad: { ...devices['iPad Pro 11'] },
  phone: { ...devices['iPhone 13'] },
};

// Elements the hosting platform injects (not in the built index.html; proven
// by runtime_html_correspondence). The app is scored without them; they get
// their own accessibility gate so the defect stays visible.
const INJECTED = (process.env.INJECTED_SELECTORS || '#aiappbuilder-badge').split(',').filter(Boolean);
const results = {}; // journey -> viewport -> {ok, detail}
const a11y = {}; // page -> viewport -> {ok, detail}

async function settle(page) {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
}

async function goto(page, path) {
  const response = await page.goto(`${RUNTIME}${path}`, { timeout: TIMEOUT });
  await settle(page);
  if (!response || response.status() >= 400) throw new Error(`GET ${path} -> ${response?.status()}`);
}

const featured = (page) => page.locator('section[aria-labelledby="featured-genus-title"]');

async function speciesReady(page) {
  const section = featured(page);
  await section.waitFor({ timeout: TIMEOUT });
  await section.locator('ul[aria-busy="false"] button[aria-pressed]').first().waitFor({ timeout: TIMEOUT });
  return section;
}

const JOURNEYS = {
  async homepage(page) {
    await goto(page, '/');
    const h1 = page.locator('h1').first();
    await h1.waitFor({ timeout: TIMEOUT });
    return `h1="${(await h1.innerText()).trim().slice(0, 80)}"`;
  },
  async chronicle_i(page) {
    await goto(page, '/chronicle-1');
    const h1 = page.locator('h1').first();
    await h1.waitFor({ timeout: TIMEOUT });
    return `h1="${(await h1.innerText()).trim().slice(0, 80)}"`;
  },
  async chronicle_ii_five_chapters(page) {
    await goto(page, '/chronicle-2');
    const nav = page.locator('nav[aria-label="Chapters"]');
    await nav.waitFor({ timeout: TIMEOUT });
    const chapters = nav.locator('button[aria-label^="Chapter"]');
    const labels = (await chapters.evaluateAll((els) => els.map((e) => e.getAttribute('aria-label'))));
    if (labels.length !== 5) throw new Error(`expected 5 chapters, found ${labels.length}: ${labels}`);
    await chapters.nth(4).click();
    await page.getByText('The Greenhouse Remembers').first().waitFor({ timeout: TIMEOUT });
    return `chapters=${JSON.stringify(labels)}; Chapter Five opened`;
  },
  async featured_genus_loads(page) {
    await goto(page, '/explore');
    const section = await speciesReady(page);
    const genus = (await section.locator('#featured-genus-title').innerText()).trim();
    const count = await section.locator('ul button[aria-pressed]').count();
    return `genus="${genus}", ${count} species buttons`;
  },
  async genus_selection(page) {
    await goto(page, '/explore');
    const section = await speciesReady(page);
    const select = section.locator('select').first();
    const before = (await section.locator('#featured-genus-title').innerText()).trim();
    const options = await select.locator('option').evaluateAll((os) => os.map((o) => o.value));
    const next = options.find((v) => v && v !== before);
    if (!next) throw new Error(`no alternative genus among ${options}`);
    await select.selectOption(next);
    await page.waitForFunction(
      (want) => document.querySelector('#featured-genus-title')?.textContent?.trim() === want, next, { timeout: TIMEOUT });
    await speciesReady(page);
    return `${before} -> ${next}`;
  },
  async species_beyond_first_nine(page) {
    await goto(page, '/explore');
    const section = await speciesReady(page);
    const names = () => section.locator('ul button[aria-pressed]').evaluateAll((bs) => bs.map((b) => b.innerText.trim()));
    const first = await names();
    const nextBtn = section.getByRole('button', { name: /Next 9/ });
    if (await nextBtn.isDisabled()) throw new Error('Next 9 disabled: genus has <= 9 species');
    await nextBtn.click();
    await page.waitForFunction(
      (prev) => {
        const s = document.querySelector('section[aria-labelledby="featured-genus-title"]');
        const now = [...(s?.querySelectorAll('ul[aria-busy="false"] button[aria-pressed]') ?? [])].map((b) => b.innerText.trim());
        return now.length > 0 && now.join('|') !== prev.join('|');
      }, first, { timeout: TIMEOUT });
    const second = await names();
    return `page 1 first="${first[0]}", page 2 first="${second[0]}" (${second.length} species)`;
  },
  async species_selection_updates_hero(page) {
    await goto(page, '/explore');
    const section = await speciesReady(page);
    const link = section.getByRole('link', { name: /Open Species Dossier/ });
    const before = await link.getAttribute('href');
    // Pin the target by position: an aria-pressed="false" locator re-resolves to
    // a different button once the click flips this one to true.
    const buttons = section.locator('ul button[aria-pressed]');
    const pressed = await buttons.evaluateAll((bs) => bs.map((b) => b.getAttribute('aria-pressed')));
    const index = pressed.indexOf('false');
    if (index < 0) throw new Error(`no unselected species to click: ${pressed}`);
    const target = buttons.nth(index);
    const name = (await target.innerText()).trim();
    await target.click();
    await page.waitForFunction(
      (prev) => [...document.querySelectorAll('a')].some((a) => /Open Species Dossier/.test(a.textContent) && a.getAttribute('href') !== prev),
      before, { timeout: TIMEOUT });
    const after = await link.getAttribute('href');
    if ((await target.getAttribute('aria-pressed')) !== 'true') throw new Error('clicked species not marked selected');
    return `selected "${name.slice(0, 60)}"; dossier link ${before} -> ${after}`;
  },
  async no_broken_images_honest_state(page) {
    await goto(page, '/explore');
    const section = await speciesReady(page);
    await page.waitForTimeout(3000);
    const imgs = await section.locator('img').evaluateAll((is) => is.map((i) => ({ src: i.currentSrc || i.src, ok: i.complete && i.naturalWidth > 0, alt: i.alt })));
    const broken = imgs.filter((i) => !i.ok);
    const noImage = await section.getByText('No image available').count();
    if (broken.length) throw new Error(`broken images: ${JSON.stringify(broken.slice(0, 3))}`);
    const unlabeled = imgs.filter((i) => !i.alt);
    if (unlabeled.length) throw new Error(`images without alt: ${unlabeled.length}`);
    return `${imgs.length} images all loaded with alt text; ${noImage} honest "No image available" placeholders`;
  },
  async species_dossier_opens(page) {
    await goto(page, '/explore');
    const section = await speciesReady(page);
    const href = await section.getByRole('link', { name: /Open Species Dossier/ }).getAttribute('href');
    await goto(page, href);
    const h1 = page.locator('h1').first();
    await h1.waitFor({ timeout: TIMEOUT });
    const body = await page.locator('body').innerText();
    if (/\bundefined\b|\bNaN\b|\[object Object\]/.test(body)) throw new Error('rendering artefact (undefined/NaN/[object Object]) on dossier');
    return `${href} -> h1="${(await h1.innerText()).trim().slice(0, 80)}"`;
  },
  async go_deeper_no_stale_not_live_claim(page) {
    await goto(page, '/go-deeper');
    const body = await page.locator('body').innerText();
    if (/integration is not live/i.test(body)) throw new Error('page tells readers "The Orchid Continuum / Calyx integration is not live"');
    return 'no stale "not live" statement';
  },
  async no_horizontal_overflow(page) {
    const offenders = [];
    for (const path of ['/', '/chronicle-2', '/explore', '/greenhouse']) {
      await goto(page, path);
      const { sw, iw } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
      if (sw > iw + 1) offenders.push(`${path} scrollWidth=${sw} > ${iw}`);
    }
    if (offenders.length) throw new Error(offenders.join('; '));
    return 'no horizontal overflow on /, /chronicle-2, /explore, /greenhouse';
  },
};

const A11Y_PAGES = { homepage: '/', chronicle_ii: '/chronicle-2', explore: '/explore', greenhouse: '/greenhouse' };

async function main() {
  const browser = await chromium.launch();
  for (const [vpName, vp] of Object.entries(VIEWPORTS)) {
    const context = await browser.newContext(vp);
    for (const [name, fn] of Object.entries(JOURNEYS)) {
      const page = await context.newPage();
      const errors = [];
      const network = [];
      page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));
      page.on('requestfailed', (r) => network.push(`${r.method()} ${r.url().slice(0, 120)} failed: ${r.failure()?.errorText}`));
      page.on('response', (r) => { if (r.status() >= 400) network.push(`${r.request().method()} ${r.url().slice(0, 120)} -> ${r.status()}`); });
      try {
        const detail = await fn(page);
        results[name] ??= {};
        results[name][vpName] = errors.length
          ? { ok: false, detail: `${detail}; uncaught page errors: ${errors.slice(0, 2)}` }
          : { ok: true, detail };
      } catch (e) {
        results[name] ??= {};
        const state = await page.evaluate(() => {
          const s = document.querySelector('section[aria-labelledby="featured-genus-title"]');
          return {
            url: location.pathname,
            genus: s?.querySelector('#featured-genus-title')?.textContent?.trim() ?? null,
            busy: s?.querySelector('ul')?.getAttribute('aria-busy') ?? null,
            buttons: s ? s.querySelectorAll('ul button[aria-pressed]').length : null,
            honestError: /could not be loaded just now|could not be reached just now/i.test(s?.innerText ?? ''),
            text: (s ?? document.body).innerText.replace(/\s+/g, ' ').slice(0, 160),
          };
        }).catch(() => null);
        results[name][vpName] = {
          ok: false,
          detail: `${String(e.message || e).split('\n')[0].slice(0, 200)}; page state ${JSON.stringify(state)}; ` +
            `network failures ${JSON.stringify(network.slice(0, 4))}`,
        };
      } finally {
        await page.close();
      }
    }
    for (const [pageName, path] of Object.entries(A11Y_PAGES)) {
      const page = await context.newPage();
      try {
        await goto(page, path);
        if (path === '/explore') await speciesReady(page).catch(() => {});
        let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']);
        for (const sel of INJECTED) builder = builder.exclude(sel);
        const r = await builder.analyze();
        const severe = r.violations.filter((v) => ['serious', 'critical'].includes(v.impact));
        const other = r.violations.filter((v) => !['serious', 'critical'].includes(v.impact));
        a11y[pageName] ??= {};
        a11y[pageName][vpName] = {
          ok: severe.length === 0,
          detail: `serious/critical: ${severe.map((v) => `${v.id}(${v.nodes.length}: ${v.nodes.slice(0, 2).map((n) => `${n.target.join(' ')} ${n.html.slice(0, 120)}`).join(' ; ')})`).join(', ') || 'none'}; ` +
            `moderate/minor: ${other.map((v) => `${v.id}(${v.nodes.length})`).join(', ') || 'none'}`,
        };
      } catch (e) {
        a11y[pageName] ??= {};
        a11y[pageName][vpName] = { ok: null, detail: String(e.message || e).split('\n')[0].slice(0, 300) };
      } finally {
        await page.close();
      }
    }
    {
      const page = await context.newPage();
      try {
        await goto(page, '/');
        const present = [];
        for (const sel of INJECTED) if (await page.locator(sel).count()) present.push(sel);
        let detail = `injected elements present: ${JSON.stringify(present)}`;
        let ok = true;
        if (present.length) {
          let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']);
          for (const sel of present) builder = builder.include(sel);
          const r = await builder.analyze();
          const severe = r.violations.filter((v) => ['serious', 'critical'].includes(v.impact));
          ok = severe.length === 0;
          detail += `; serious/critical: ${severe.map((v) => `${v.id}(${v.nodes.length})`).join(', ') || 'none'}`;
        }
        a11y.hosting_injected ??= {};
        a11y.hosting_injected[vpName] = { ok, detail };
      } catch (e) {
        a11y.hosting_injected ??= {};
        a11y.hosting_injected[vpName] = { ok: null, detail: String(e.message || e).split('\n')[0].slice(0, 300) };
      } finally {
        await page.close();
      }
    }
    await context.close();
  }
  await browser.close();

  const gates = [];
  const summarise = (byVp) => Object.entries(byVp).map(([vp, r]) => `${vp}: ${r.ok === true ? 'ok' : r.ok === null ? 'not run' : 'FAILED'} -- ${r.detail}`).join(' | ');
  for (const [name, byVp] of Object.entries(results)) {
    const ok = Object.values(byVp).every((r) => r.ok);
    gates.push({
      gate_id: `journey_${name}`, status: ok ? 'PASS' : 'FAIL', evidence_type: 'browser',
      observed_evidence: `${RUNTIME}: ${summarise(byVp)}`,
      blocker: ok ? null : `Journey ${name} failed on at least one viewport.`,
      smallest_next_action: ok ? null : `Repair the ${name} journey in the application, redeploy, then re-run certification.`,
    });
  }
  for (const [name, byVp] of Object.entries(a11y)) {
    const states = Object.values(byVp).map((r) => r.ok);
    const status = states.includes(null) ? 'BLOCKED' : states.every(Boolean) ? 'PASS' : 'FAIL';
    gates.push({
      gate_id: `accessibility_${name}`, status, evidence_type: 'browser',
      observed_evidence: name === 'hosting_injected'
        ? `axe-core WCAG 2.x A/AA on hosting-injected elements ${JSON.stringify(INJECTED)} (absent from the application build): ${summarise(byVp)}`
        : `axe-core WCAG 2.x A/AA on ${RUNTIME}${A11Y_PAGES[name]} excluding hosting-injected ${JSON.stringify(INJECTED)}: ${summarise(byVp)}`,
      blocker: status === 'PASS' ? null : `Accessibility check for ${name} did not pass on every viewport.`,
      smallest_next_action: status === 'PASS' ? null : 'Fix the serious/critical axe violations listed, redeploy, then re-run.',
    });
  }
  writeFileSync(outPath, JSON.stringify(gates, null, 2) + '\n');
  for (const g of gates) console.log(`${g.gate_id}: ${g.status} -- ${g.observed_evidence.slice(0, 600)}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
