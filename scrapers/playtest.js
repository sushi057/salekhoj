const puppeteer = require('puppeteer-core');
const CHROME = '/home/sushi/.cache/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome';
const BASE = 'http://localhost:8811';
const OUT = '/tmp/claude-1000/-home-sushi-Code-projects/e79a7988-c973-407d-8188-7d780889cd84/scratchpad';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const checks = [];
const check = (name, ok, detail = '') => {
  checks.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
};

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));

  // ---------- home ----------
  await page.setViewport({ width: 1400, height: 1000 });
  await page.goto(`${BASE}/index.html`, { waitUntil: 'networkidle2', timeout: 60000 });
  await sleep(1200);

  check('home: header rendered', await page.$('.top .mark') !== null);
  check('home: nav has 4 links', (await page.$$('.nav a')).length === 4);

  const stats = await page.evaluate(() => ({
    deals: document.querySelector('#stat-deals')?.textContent,
    stores: document.querySelector('#stat-stores')?.textContent,
    updated: document.querySelector('#updated')?.textContent,
  }));
  check('home: deal count filled from data', /[0-9],[0-9]{3}/.test(stats.deals || ''), JSON.stringify(stats));

  const topCards = await page.$$('#top-deals .card');
  check('home: top deals grid populated', topCards.length === 12, `${topCards.length} cards`);

  const firstCard = await page.evaluate(() => {
    const c = document.querySelector('#top-deals .card');
    return c && {
      href: c.getAttribute('href'),
      badge: c.querySelector('.sticker')?.textContent,
      title: c.querySelector('.card-title')?.textContent,
      now: c.querySelector('.now')?.textContent,
      was: c.querySelector('.was')?.textContent,
      hasImg: !!c.querySelector('.thumb img'),
    };
  });
  check('home: card has real link', /^https?:\/\//.test(firstCard?.href || ''), firstCard?.href);
  check('home: card shows both prices', !!firstCard?.now && !!firstCard?.was,
    `${firstCard?.now} / ${firstCard?.was}`);
  check('home: card has image', firstCard?.hasImg === true);
  check('home: discount sticker present', /%\s*off/i.test(firstCard?.badge || ''), firstCard?.badge);

  const tiles = await page.$$('#tiles .tile');
  check('home: category tiles rendered', tiles.length >= 4, `${tiles.length} tiles`);
  check('home: under-1500 rail populated', (await page.$$('#under .card')).length === 12);

  // images actually load (not 404 hotlink blocks)
  const brokenImgs = await page.evaluate(() =>
    [...document.querySelectorAll('#top-deals img')].filter((i) => i.naturalWidth === 0).length);
  check('home: thumbnails load from source CDNs', brokenImgs === 0, `${brokenImgs} broken`);

  await page.screenshot({ path: `${OUT}/01-home.png`, fullPage: false });
  await page.screenshot({ path: `${OUT}/02-home-full.png`, fullPage: true });

  // ---------- deals + filters ----------
  await page.goto(`${BASE}/deals.html`, { waitUntil: 'networkidle2' });
  await sleep(900);
  const all = await page.$eval('#count', (e) => e.textContent);
  check('deals: count rendered', /deal/.test(all), all);
  check('deals: first page capped at 48', (await page.$$('#results .card')).length === 48);

  await page.click('#more');
  await sleep(400);
  check('deals: show-more appends', (await page.$$('#results .card')).length === 96);

  // category chip
  await page.evaluate(() => [...document.querySelectorAll('.chip')]
    .find((c) => c.dataset.c === 'Footwear').click());
  await sleep(400);
  const footwearOnly = await page.evaluate(() =>
    [...document.querySelectorAll('#results .card')].length);
  const chipCount = await page.$eval('#count', (e) => e.textContent);
  check('deals: category filter narrows results', footwearOnly > 0 && chipCount !== all,
    `Footwear -> ${chipCount}`);
  check('deals: url reflects filter', page.url().includes('c=Footwear'), page.url());

  // search
  await page.type('#q', 'boot');
  await sleep(500);
  const searchCount = await page.$eval('#count', (e) => e.textContent);
  const titlesMatch = await page.evaluate(() =>
    [...document.querySelectorAll('#results .card-title')].every((t) =>
      t.textContent.toLowerCase().includes('boot')));
  check('deals: search filters titles', titlesMatch, `"boot" -> ${searchCount}`);

  // min discount slider
  await page.evaluate(() => {
    const el = document.querySelector('#min');
    el.value = 50; el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(400);
  const allAbove50 = await page.evaluate(() =>
    [...document.querySelectorAll('#results .sticker')]
      .every((s) => parseInt(s.textContent) >= 50));
  check('deals: min-discount slider respected', allAbove50);

  // sort cheapest
  await page.evaluate(() => {
    document.querySelector('#q').value = '';
    document.querySelector('#q').dispatchEvent(new Event('input', { bubbles: true }));
    const el = document.querySelector('#min');
    el.value = 0; el.dispatchEvent(new Event('input', { bubbles: true }));
    const s = document.querySelector('#sort');
    s.value = 'cheap'; s.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await sleep(500);
  // Sort is by NPR-equivalent, so compare that — displayed prices are in each store's
  // own currency and a $4 sweater legitimately sits above a Rs 200 t-shirt.
  const ascending = await page.evaluate(() => {
    const n = [...document.querySelectorAll('#results .card')].map((c) => {
      const ap = c.querySelector('.approx');
      return ap ? +ap.textContent.replace(/[^0-9]/g, '')
                : +c.querySelector('.now').textContent.replace(/[^0-9]/g, '');
    });
    return n.every((v, i) => i === 0 || n[i - 1] <= v);
  });
  check('deals: cheapest-first sort ordered (NPR-equivalent)', ascending);

  await page.screenshot({ path: `${OUT}/03-deals.png`, fullPage: false });

  // empty state
  await page.evaluate(() => {
    const q = document.querySelector('#q');
    q.value = 'zzzzqqqq'; q.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(400);
  check('deals: empty state shown', await page.$('#results .empty') !== null);

  // ---------- brands ----------
  await page.goto(`${BASE}/brands.html`, { waitUntil: 'networkidle2' });
  await sleep(700);
  const brandCards = await page.$$('.brand-card');
  check('brands: store cards rendered', brandCards.length >= 15, `${brandCards.length} stores`);
  await page.screenshot({ path: `${OUT}/04-brands.png`, fullPage: false });

  const href = await page.$eval('.brand-card', (a) => a.getAttribute('href'));
  await page.goto(`${BASE}/${href}`, { waitUntil: 'networkidle2' });
  await sleep(700);
  check('brand: page has deals', (await page.$$('#brand-results .card')).length > 0);
  check('brand: title set from query', !/^Store$/.test(
    await page.$eval('#brand-name', (e) => e.textContent)),
    await page.$eval('#brand-name', (e) => e.textContent));
  await page.screenshot({ path: `${OUT}/05-brand.png`, fullPage: false });

  // ---------- about ----------
  await page.goto(`${BASE}/about.html`, { waitUntil: 'networkidle2' });
  await sleep(400);
  check('about: prose rendered', (await page.$$('.prose h2')).length >= 4);

  // ---------- mobile ----------
  await page.setViewport({ width: 390, height: 844, isMobile: true });
  await page.goto(`${BASE}/index.html`, { waitUntil: 'networkidle2' });
  await sleep(1000);
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check('mobile: no horizontal overflow', overflow <= 0, `${overflow}px`);
  await page.screenshot({ path: `${OUT}/06-mobile.png`, fullPage: false });

  await page.goto(`${BASE}/deals.html`, { waitUntil: 'networkidle2' });
  await sleep(900);
  const ov2 = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check('mobile: deals page no overflow', ov2 <= 0, `${ov2}px`);
  await page.screenshot({ path: `${OUT}/07-mobile-deals.png`, fullPage: false });

  // ---------- dark mode ----------
  await page.setViewport({ width: 1400, height: 1000 });
  await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
  await page.goto(`${BASE}/index.html`, { waitUntil: 'networkidle2' });
  await sleep(1000);
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  check('dark mode: dark background applied', bg !== 'rgb(246, 245, 241)', bg);
  await page.screenshot({ path: `${OUT}/08-dark.png`, fullPage: false });

  check('no console/page errors', errors.length === 0, errors.slice(0, 3).join(' | '));

  await browser.close();
  const failed = checks.filter((c) => !c.ok);
  console.log(`\n${checks.length - failed.length}/${checks.length} passed`);
  process.exit(failed.length ? 1 : 0);
})();
