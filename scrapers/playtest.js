const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = '/home/sushi/.cache/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome';
const BASE = 'http://localhost:8811';
const OUT = '/tmp/salekhoj-pt';
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const checks = [];
const check = (name, ok, detail = '') => {
  checks.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
};

async function measureCLS(browser, url) {
  const p = await browser.newPage();
  await p.setViewport({ width: 1400, height: 900 });
  const cdp = await p.target().createCDPSession();
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });   // surface the transient
  await p.evaluateOnNewDocument(() => {
    window.__cls = [];
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls.push(e.value);
    }).observe({ type: 'layout-shift', buffered: true });
  });
  await p.goto(url, { waitUntil: 'networkidle2' });
  await sleep(2500);
  const cls = (await p.evaluate(() => window.__cls)).reduce((a, x) => a + x, 0);
  await p.close();
  return cls;
}

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
  check('home: no vertical subnav', await page.$('.subnav-wrap') === null);
  check('home: footer is standard', await page.evaluate(() => {
    const legal = document.querySelector('.foot-legal')?.textContent || '';
    return document.querySelectorAll('.foot-nav a').length === 4 && /©\s*\d{4}\s*SaleKhoj/.test(legal);
  }));

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

  const feat = await page.evaluate(() => {
    const sec = document.querySelector('#featured-section');
    const b = document.querySelector('.feat');
    return {
      visible: sec && !sec.hidden,
      name: b?.querySelector('.feat-name')?.textContent,
      cards: b ? b.querySelectorAll('.card').length : 0,
      allSameStore: b ? [...b.querySelectorAll('.card')]
        .every((c) => c.dataset.brand === 'muscleblaze.com.np') : false,
      more: b?.querySelector('.more')?.getAttribute('href'),
    };
  });
  check('home: featured section visible', feat.visible === true);
  check('home: featured store named', feat.name === 'MuscleBlaze', feat.name);
  check('home: featured cards all from that store', feat.cards > 0 && feat.allSameStore,
    `${feat.cards} cards`);
  check('home: featured links to brand page',
    (feat.more || '').includes('b=muscleblaze.com.np'), feat.more);

  const tiles = await page.$$('#tiles .tile');
  check('home: category tiles rendered', tiles.length >= 4, `${tiles.length} tiles`);
  check('home: under-1500 rail populated', (await page.$$('#under .card')).length === 12);

  // Images actually load (not 404 hotlink blocks). Cards are loading="lazy" and the
  // featured block now sits above this rail, so scroll it into view first — otherwise
  // this measures the lazy-loader, not the CDNs.
  // Wait for them to settle rather than sleeping a fixed time — several Nepali hosts are
  // slow enough that a fixed wait reports "broken" for an image that is merely still in
  // flight (img.complete === false). Only a finished-but-zero-width image is really broken.
  await page.evaluate(() => document.querySelector('#top-deals').scrollIntoView());
  const brokenImgs = await page.evaluate(async () => {
    const imgs = () => [...document.querySelectorAll('#top-deals img')];
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline && imgs().some((i) => !i.complete)) {
      await new Promise((r) => setTimeout(r, 250));
    }
    return imgs().filter((i) => i.complete && i.naturalWidth === 0).length;
  });
  check('home: thumbnails load from source CDNs', brokenImgs === 0, `${brokenImgs} broken`);
  await page.evaluate(() => window.scrollTo(0, 0));
  await sleep(300);

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

  // subnav belongs to the deals page only, and reflects the ?v= filter
  await page.goto(`${BASE}/deals.html?v=Fashion`, { waitUntil: 'networkidle2' });
  await sleep(700);
  check('deals: vertical subnav present', (await page.$$('.subnav a')).length === 5);
  check('deals: subnav marks current vertical', await page.$eval('.subnav a[aria-current]',
    (e) => e.textContent) === 'Fashion');
  const fieldBox = await page.evaluate(() => {
    const els = [...document.querySelectorAll('.filters .field')];
    const boxes = els.map((e) => e.getBoundingClientRect());
    return {
      n: els.length,
      sameLeft: new Set(boxes.map((b) => Math.round(b.left))).size === 1,
      sameWidth: new Set(boxes.map((b) => Math.round(b.width))).size === 1,
      sameHeight: new Set(boxes.map((b) => Math.round(b.height))).size === 1,
    };
  });
  check('deals: filter fields share one box model',
    fieldBox.n === 3 && fieldBox.sameLeft && fieldBox.sameWidth && fieldBox.sameHeight,
    JSON.stringify(fieldBox));
  // The panel's box model must live in the stylesheet, not in inline attributes — that
  // drift is what made the search input and the selects disagree. The range's inline
  // --pct is a live value, not layout, so it is allowed.
  // An open <details> puts its contents in an anonymous box, which silently swallowed the
  // flex gap between filter groups. Assert the rhythm actually renders: every group evenly
  // separated, and that separation clearly larger than the label-to-control gap.
  const rhythm = await page.evaluate(() => {
    const gs = [...document.querySelectorAll('.filters .fgroup')];
    const gaps = gs.slice(1).map((g, i) =>
      Math.round(g.getBoundingClientRect().top - gs[i].getBoundingClientRect().bottom));
    const inner = gs.map((g) => Math.round(
      g.querySelector('.field,.chips,input[type=range],.select-wrap').getBoundingClientRect().top
      - g.querySelector('label,legend').getBoundingClientRect().bottom));
    return { gaps, inner };
  });
  // The panel is taller than the window with every category chip shown; if it doesn't
  // scroll itself, its tail is unreachable while sticky. Everything except the long
  // Category list must also be usable without scrolling the panel at all.
  // Worst case is the unfiltered list, where every category chip is shown.
  await page.goto(`${BASE}/deals.html`, { waitUntil: 'networkidle2' });
  await sleep(1200);
  const reach = await page.evaluate(() => {
    const f = document.querySelector('.filters');
    const fr = f.getBoundingClientRect();
    const groups = [...document.querySelectorAll('.filters .fgroup')];
    const last = groups[groups.length - 1];
    return {
      fitsViewport: fr.height <= window.innerHeight,
      scrollsItself: f.scrollHeight > f.clientHeight,
      lastIsCategory: /Category/i.test(last.querySelector('legend,label').textContent),
      restReachable: groups.slice(0, -1)
        .every((g) => g.getBoundingClientRect().bottom <= fr.bottom + 1),
    };
  });
  check('deals: filter panel fits the viewport', reach.fitsViewport && reach.scrollsItself,
    JSON.stringify(reach));
  check('deals: every filter but Category reachable unscrolled',
    reach.lastIsCategory && reach.restReachable, JSON.stringify(reach));

  check('deals: filter groups evenly spaced',
    new Set(rhythm.gaps).size === 1 && rhythm.gaps[0] > 0, JSON.stringify(rhythm.gaps));
  check('deals: group gap exceeds label gap',
    rhythm.gaps[0] > Math.max(...rhythm.inner) * 1.5,
    `gap ${rhythm.gaps[0]} vs label ${Math.max(...rhythm.inner)}`);

  check('deals: no inline layout styles in filter panel', await page.evaluate(() =>
    [...document.querySelectorAll('.filters [style]')].every((el) =>
      [...el.style].every((prop) => prop.startsWith('--')))));
  await page.screenshot({ path: `${OUT}/22-filters.png`, fullPage: false });

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

  await page.goto(`${BASE}/brands.html`, { waitUntil: 'networkidle2' });
  await sleep(900);
  const ov3 = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check('mobile: brands page no overflow', ov3 <= 0, `${ov3}px`);
  await page.screenshot({ path: `${OUT}/11-mobile-brands.png`, fullPage: false });

  // ---------- dark mode ----------
  await page.setViewport({ width: 1400, height: 1000 });
  await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
  await page.goto(`${BASE}/index.html`, { waitUntil: 'networkidle2' });
  await sleep(1000);
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  check('dark mode: dark background applied', bg !== 'rgb(246, 245, 241)', bg);
  // Without color-scheme the OS draws <select> popups light on a dark page — the Store and
  // Sort dropdowns were white-on-white and unreadable.
  await page.goto(`${BASE}/deals.html`, { waitUntil: 'networkidle2' });
  await sleep(1200);
  const native = await page.evaluate(() => ({
    scheme: getComputedStyle(document.documentElement).colorScheme,
    optionBg: getComputedStyle(document.querySelector('#sort option')).backgroundColor,
    optionColor: getComputedStyle(document.querySelector('#sort option')).color,
  }));
  check('dark mode: native controls follow the theme',
    native.scheme === 'dark' && native.optionBg !== 'rgb(255, 255, 255)',
    JSON.stringify(native));
  await page.screenshot({ path: `${OUT}/08-dark.png`, fullPage: false });

  // Layout stability. The footer used to be appended before any card existed, so it
  // painted under the header and was then shoved down the page — a horizontal rule that
  // flashed on every load. Same story for the featured block revealing at the top.
  // Google's "good" CLS threshold is 0.1; these pages measured 0.14–0.31 before the fix.
  await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }]);
  for (const path of ['index.html', 'deals.html', 'brands.html', 'about.html']) {
    const cls = await measureCLS(browser, `${BASE}/${path}`);
    check(`layout: ${path} CLS under 0.1`, cls < 0.1, cls.toFixed(4));
  }

  // ---------- SEO ----------
  // The site is client-rendered, so what a crawler gets from the raw HTML is exactly these
  // tags. They are the whole on-page story until pages are prerendered.
  for (const path of ['index.html', 'deals.html', 'brands.html', 'about.html']) {
    const res = await fetch(`${BASE}/${path}`);
    const html = await res.text();
    const one = (re) => (html.match(re) || []).length;
    const ok = one(/<title>[^<]{10,70}<\/title>/) === 1
      && one(/<meta name="description" content="[^"]{50,170}"/) === 1
      && one(/<link rel="canonical"/) === 1
      && one(/<meta property="og:title"/) === 1
      && one(/<meta property="og:image"/) === 1
      && one(/<meta name="twitter:card"/) === 1
      && one(/<h1[\s>]/) === 1;
    check(`seo: ${path} has title, description, canonical, OG and one h1`, ok);
    const ld = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)];
    let ldOk = ld.length > 0;
    for (const m of ld) { try { JSON.parse(m[1]); } catch { ldOk = false; } }
    check(`seo: ${path} JSON-LD parses`, ldOk, `${ld.length} block(s)`);
  }
  // brand.html serves ?b=<domain>; every variant would be a near-duplicate, so it must
  // stay out of the index while still passing crawlers through to the stores.
  const brandHtml = await (await fetch(`${BASE}/brand.html`)).text();
  check('seo: brand.html is noindex,follow',
    /<meta name="robots" content="noindex,follow">/.test(brandHtml));

  const robots = await (await fetch(`${BASE}/robots.txt`)).text();
  check('seo: robots.txt points at the sitemap', /Sitemap:\s*https?:\/\/\S+sitemap\.xml/.test(robots));
  const sitemap = await (await fetch(`${BASE}/sitemap.xml`)).text();
  check('seo: sitemap lists the indexable pages',
    ['/', 'deals.html', 'brands.html', 'about.html'].every((u) => sitemap.includes(u))
    && !sitemap.includes('brand.html?'));
  const og = await fetch(`${BASE}/og.png`);
  check('seo: og.png is served', og.ok && +og.headers.get('content-length') > 10000,
    `${og.status}, ${og.headers.get('content-length')} bytes`);

  check('no console/page errors', errors.length === 0, errors.slice(0, 3).join(' | '));

  await browser.close();
  const failed = checks.filter((c) => !c.ok);
  console.log(`\n${checks.length - failed.length}/${checks.length} passed`);
  process.exit(failed.length ? 1 : 0);
})();
