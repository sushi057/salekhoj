/* SaleKhoj — one shared script for every page. Data is a static JSON build artifact. */

const PAGES = [
  ['index.html', 'Home'],
  ['deals.html', 'All deals'],
  ['brands.html', 'Stores'],
  ['about.html', 'About'],
];

const VERTICALS = ['Fashion', 'Electronics', 'Beauty', 'Fitness'];

const money = (p) => p.currency === 'NPR' || !p.currency
  ? 'Rs ' + Math.round(p.price).toLocaleString('en-IN')
  : new Intl.NumberFormat('en', { style: 'currency', currency: p.currency,
      maximumFractionDigits: 0 }).format(p.price);

const wasMoney = (p) => p.currency === 'NPR' || !p.currency
  ? 'Rs ' + Math.round(p.original_price).toLocaleString('en-IN')
  : new Intl.NumberFormat('en', { style: 'currency', currency: p.currency,
      maximumFractionDigits: 0 }).format(p.original_price);

const storeName = (domain) => domain
  .replace(/\.(com|np|com\.np|store|shop)$/g, '')
  .replace(/\.com$/, '').replace(/[-.]/g, ' ')
  .replace(/\b\w/g, (c) => c.toUpperCase());

const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* Biggest-discount-first alone lets one store own the whole homepage: it's sorted by
   number, and one store's markdowns are always deepest. Cap each store at two on a rail. */
function spread(products, n, perBrand = 2) {
  const seen = {};
  const out = [];
  const ranked = [...products].sort((a, b) => b.discount_pct - a.discount_pct);
  for (const p of ranked) {
    if ((seen[p.brand] = (seen[p.brand] || 0) + 1) <= perBrand) out.push(p);
    if (out.length === n) break;
  }
  return out;
}

function card(p) {
  return `<a class="card" href="${esc(p.url)}" target="_blank" rel="noopener nofollow sponsored">
    <span class="sticker ${p.discount_pct >= 40 ? 'hot' : ''}">${p.discount_pct}<small>% off</small></span>
    <div class="thumb">${p.image
      ? `<img src="${esc(p.image)}" alt="" loading="lazy" decoding="async">` : ''}</div>
    <div class="card-body">
      <span class="card-brand">${esc(storeName(p.brand))}</span>
      <h3 class="card-title">${esc(p.title)}</h3>
      <div class="prices"><span class="now">${money(p)}</span><s class="was">${wasMoney(p)}</s>
        ${p.currency && p.currency !== 'NPR'
          ? `<span class="approx">≈ Rs ${p.price_npr.toLocaleString('en-IN')}</span>` : ''}</div>
    </div>
  </a>`;
}

/* ---------- theme ---------- */
const THEME_KEY = 'salekhoj-theme';
const THEME_ICON = { auto: '◐', light: '☀', dark: '☾' };
const THEME_LABEL = { auto: 'Auto', light: 'Light', dark: 'Dark' };

function resolveTheme(choice) {
  if (choice === 'light' || choice === 'dark') return choice;
  const dark = window.matchMedia('(prefers-color-scheme: dark)');
  const light = window.matchMedia('(prefers-color-scheme: light)');
  if (dark.matches) return 'dark';
  if (light.matches) return 'light';
  const h = new Date().getHours();
  return (h >= 19 || h < 6) ? 'dark' : 'light';
}

function initThemeToggle() {
  const btn = document.querySelector('#theme-toggle');
  if (!btn) return;
  const order = ['auto', 'light', 'dark'];

  function paint() {
    const choice = localStorage.getItem(THEME_KEY) || 'auto';
    document.documentElement.setAttribute('data-theme', resolveTheme(choice));
    btn.textContent = THEME_ICON[choice];
    btn.setAttribute('aria-label', `Theme: ${THEME_LABEL[choice]}. Click to change.`);
  }

  btn.addEventListener('click', () => {
    const choice = localStorage.getItem(THEME_KEY) || 'auto';
    const next = order[(order.indexOf(choice) + 1) % order.length];
    localStorage.setItem(THEME_KEY, next);
    paint();
  });

  // Auto mode should keep following the OS preference while the page stays open.
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if ((localStorage.getItem(THEME_KEY) || 'auto') === 'auto') paint();
  });

  paint();
}

function chrome(page) {
  const nav = PAGES.map(([href, label]) =>
    `<a href="${href}"${href === page ? ' aria-current="page"' : ''}>${label}</a>`).join('');
  // Second-level bar rather than cramming 4 more links into .nav — that's the row the
  // playtest counts (`.nav a` === 4), and 8 links in one row doesn't fit at 360px anyway.
  const currentV = new URLSearchParams(location.search).get('v') || '';
  const onDeals = page === 'deals.html';
  const subnav = `<a href="deals.html"${onDeals && !currentV ? ' aria-current="page"' : ''}>All</a>` +
    VERTICALS.map((v) => `<a href="deals.html?v=${encodeURIComponent(v)}"${onDeals && v === currentV
      ? ' aria-current="page"' : ''}>${v}</a>`).join('');
  document.body.insertAdjacentHTML('afterbegin', `
    <a class="skip" href="#main">Skip to content</a>
    <header class="top"><div class="wrap top-in">
      <a class="mark" href="index.html">Sale<em>Khoj</em></a>
      <form class="top-search" role="search" action="deals.html">
        <input type="search" name="q" placeholder="Search deals" aria-label="Search deals">
      </form>
      <nav class="nav">${nav}</nav>
      <button class="theme-btn" id="theme-toggle" type="button" aria-label="Theme"></button>
    </div></header>
    <div class="subnav-wrap"><nav class="subnav wrap">${subnav}</nav></div>`);
  document.body.insertAdjacentHTML('beforeend', `
    <footer class="foot"><div class="wrap foot-in">
      <p>Prices pulled straight from each store. We link you there; we never take payment.</p>
      <nav>${PAGES.map(([h, l]) => `<a href="${h}">${l}</a>`).join('')}</nav>
    </div></footer>`);
  initThemeToggle();
}

async function loadData() {
  const res = await fetch('data.json');
  if (!res.ok) throw new Error('data.json missing — run the scrapers');
  return res.json();
}

/* ---------- pages ---------- */

function renderHome(db) {
  const { products, brands } = db;
  document.querySelector('#stat-deals').textContent = products.length.toLocaleString();
  document.querySelector('#stat-stores').textContent = brands.length;
  document.querySelector('#updated').textContent =
    new Date(db.generated_at).toLocaleDateString('en-GB',
      { day: 'numeric', month: 'short', year: 'numeric' });

  const top = spread(products, 12);
  document.querySelector('#top-deals').innerHTML = top.map(card).join('');

  const counts = {};
  for (const p of products) counts[p.bucket] = (counts[p.bucket] || 0) + 1;
  document.querySelector('#tiles').innerHTML = Object.entries(counts)
    .filter(([k]) => k !== 'Other').sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `<a class="tile" href="deals.html?c=${encodeURIComponent(k)}">
      <b>${k}</b><span>${n.toLocaleString()} deals</span></a>`).join('');

  document.querySelector('#vertical-rails').innerHTML = VERTICALS.map((v) => {
    const items = products.filter((p) => p.vertical === v);
    const rail = spread(items, 8);
    return `<div class="v-rail">
      <div class="section-head">
        <h3>${v}</h3>
        <p>${items.length.toLocaleString()} deals live</p>
        <a class="more" href="deals.html?v=${encodeURIComponent(v)}">All ${v} &rarr;</a>
      </div>
      <div class="grid">${rail.map(card).join('')}</div>
    </div>`;
  }).join('');

  // Don't repeat what the rail above already showed — the steepest cuts are mostly cheap
  // items, so without this both rails render the same twelve products.
  const shown = new Set(top.map((p) => p.url));
  document.querySelector('#under').innerHTML = spread(
    products.filter((p) => p.price_npr <= 1500 && !shown.has(p.url)), 12).map(card).join('');
}

const PAGE_SIZE = 48;

// A closed <details> makes its contents inert (unfocusable) in every browser, no CSS override
// undoes that — so "always open above 860px" needs this one line of JS to hold the native
// open attribute in sync with viewport width. The collapse/expand click itself stays native.
function initFiltersDetails() {
  const d = document.querySelector('#filters');
  if (!d) return;
  const wide = window.matchMedia('(min-width: 861px)');
  const sync = () => { d.open = wide.matches; };
  wide.addEventListener('change', sync);
  sync();
}

function renderDeals(db) {
  initFiltersDetails();
  const params = new URLSearchParams(location.search);
  const state = {
    q: params.get('q') || '',
    v: VERTICALS.includes(params.get('v')) ? params.get('v') : '',
    c: params.get('c') || '',
    b: params.get('b') || '',
    min: +(params.get('min') || 0),
    sort: params.get('sort') || 'discount',
    shown: PAGE_SIZE,
  };

  const q = document.querySelector('#q');
  q.value = state.q;
  document.querySelector('#vchips').innerHTML = VERTICALS.map((v) =>
    `<button class="chip" data-v="${v}" aria-pressed="${v === state.v}">${v}</button>`).join('');
  document.querySelector('#brand').innerHTML = '<option value="">Every store</option>' +
    db.brands.map((b) => `<option value="${b}"${b === state.b ? ' selected' : ''}>${storeName(b)}</option>`).join('');
  document.querySelector('#sort').value = state.sort;
  document.querySelector('#min').value = state.min;

  // No vertical picked -> every bucket, same as before verticals existed. Pick one and the
  // chip list narrows to just its buckets — "Footwear, Phones, Skincare" together was noise.
  function renderBucketChips() {
    const scoped = state.v ? db.products.filter((p) => p.vertical === state.v) : db.products;
    const buckets = [...new Set(scoped.map((p) => p.bucket))].sort();
    if (state.c && !buckets.includes(state.c)) state.c = '';
    document.querySelector('#chips').innerHTML = buckets.map((b) =>
      `<button class="chip" data-c="${b}" aria-pressed="${b === state.c}">${b}</button>`).join('');
  }
  renderBucketChips();

  function apply() {
    const needle = state.q.toLowerCase().trim();
    let out = db.products.filter((p) =>
      (!state.v || p.vertical === state.v) &&
      (!state.c || p.bucket === state.c) &&
      (!state.b || p.brand === state.b) &&
      p.discount_pct >= state.min &&
      (!needle || p.title.toLowerCase().includes(needle) || p.brand.includes(needle)));

    const sorts = {
      discount: (a, b) => b.discount_pct - a.discount_pct,
      cheap: (a, b) => a.price_npr - b.price_npr,
      dear: (a, b) => b.price_npr - a.price_npr,
      saving: (a, b) => (b.original_price - b.price) * (b.currency === 'NPR' ? 1 : 141)
                      - (a.original_price - a.price) * (a.currency === 'NPR' ? 1 : 141),
    };
    out.sort(sorts[state.sort] || sorts.discount);

    document.querySelector('#count').textContent =
      `${out.length.toLocaleString()} deal${out.length === 1 ? '' : 's'}`;
    const page = out.slice(0, state.shown);
    document.querySelector('#results').innerHTML = page.length
      ? page.map(card).join('')
      : `<div class="empty"><b>Nothing matches</b>
         <p>Try a wider discount range or clear the store filter.</p></div>`;
    const more = document.querySelector('#more');
    more.hidden = out.length <= state.shown;
    more.textContent = `Show ${Math.min(PAGE_SIZE, out.length - state.shown)} more`;

    const url = new URLSearchParams();
    for (const k of ['q', 'v', 'c', 'b', 'sort']) if (state[k]) url.set(k, state[k]);
    if (state.min) url.set('min', state.min);
    history.replaceState(null, '', url.toString() ? '?' + url : location.pathname);

    const active = ['q', 'v', 'c', 'b', 'min'].filter((k) => state[k]).length;
    document.querySelector('#filter-count').textContent = active ? `(${active} active)` : '';
  }

  const reset = (fn) => (e) => { fn(e); state.shown = PAGE_SIZE; apply(); };
  q.addEventListener('input', reset((e) => { state.q = e.target.value; }));
  document.querySelector('#vchips').addEventListener('click', reset((e) => {
    const btn = e.target.closest('.chip'); if (!btn) return;
    state.v = btn.getAttribute('aria-pressed') === 'true' ? '' : btn.dataset.v;
    document.querySelectorAll('#vchips .chip').forEach((c) =>
      c.setAttribute('aria-pressed', c.dataset.v === state.v));
    renderBucketChips();
  }));
  document.querySelector('#chips').addEventListener('click', reset((e) => {
    const btn = e.target.closest('.chip'); if (!btn) return;
    state.c = btn.getAttribute('aria-pressed') === 'true' ? '' : btn.dataset.c;
    document.querySelectorAll('#chips .chip').forEach((c) =>
      c.setAttribute('aria-pressed', c.dataset.c === state.c));
  }));
  document.querySelector('#brand').addEventListener('change', reset((e) => { state.b = e.target.value; }));
  document.querySelector('#sort').addEventListener('change', reset((e) => { state.sort = e.target.value; }));
  document.querySelector('#min').addEventListener('input', reset((e) => {
    state.min = +e.target.value;
    document.querySelector('#min-out').textContent = state.min ? state.min + '%+' : 'Any';
  }));
  document.querySelector('#more').addEventListener('click', () => { state.shown += PAGE_SIZE; apply(); });

  document.querySelector('#min-out').textContent = state.min ? state.min + '%+' : 'Any';
  apply();
}

function renderBrands(db) {
  const by = {};
  for (const p of db.products) (by[p.brand] ||= []).push(p);
  const rows = Object.entries(by)
    .map(([domain, items]) => ({
      domain, n: items.length,
      best: Math.max(...items.map((p) => p.discount_pct)),
      verticals: [...new Set(items.map((p) => p.vertical))].sort(),
    }))
    .sort((a, b) => b.n - a.n);

  const vfilter = new URLSearchParams(location.search).get('v') || '';
  document.querySelector('#brand-vchips').innerHTML =
    `<button class="chip" data-v="" aria-pressed="${!vfilter}">All</button>` +
    VERTICALS.map((v) => `<button class="chip" data-v="${v}" aria-pressed="${v === vfilter}">${v}</button>`).join('');

  function paint(v) {
    const shown = v ? rows.filter((r) => r.verticals.includes(v)) : rows;
    document.querySelector('#brand-grid').innerHTML = shown.map((r) =>
      `<a class="brand-card" href="brand.html?b=${encodeURIComponent(r.domain)}">
        <b>${esc(storeName(r.domain))}</b>
        <span class="meta">${r.domain}</span>
        <span class="v-tags">${r.verticals.map((x) => `<em>${x}</em>`).join('')}</span>
        <span class="best">up to ${r.best}% off</span>
        <span class="meta">${r.n.toLocaleString()} deals live</span>
      </a>`).join('');
    document.querySelector('#brand-count').textContent = shown.length;
    history.replaceState(null, '', v ? `?v=${encodeURIComponent(v)}` : location.pathname);
  }

  document.querySelector('#brand-vchips').addEventListener('click', (e) => {
    const btn = e.target.closest('.chip'); if (!btn) return;
    document.querySelectorAll('#brand-vchips .chip').forEach((c) =>
      c.setAttribute('aria-pressed', c === btn));
    paint(btn.dataset.v);
  });

  paint(vfilter);
}

function renderBrand(db) {
  const domain = new URLSearchParams(location.search).get('b');
  const items = db.products.filter((p) => p.brand === domain)
    .sort((a, b) => b.discount_pct - a.discount_pct);
  const verticals = [...new Set(items.map((p) => p.vertical))].sort();
  document.title = `${storeName(domain)} deals — SaleKhoj`;
  document.querySelector('#brand-name').textContent = storeName(domain);
  document.querySelector('#brand-sub').innerHTML = items.length
    ? `${items.length.toLocaleString()} deals live in ${verticals.join(', ')} &middot;
       <a href="https://${esc(domain)}" target="_blank" rel="noopener nofollow">${esc(domain)}</a>`
    : 'No deals from this store right now.';
  document.querySelector('#brand-results').innerHTML = items.map(card).join('');
}

const RENDERERS = { home: renderHome, deals: renderDeals, brands: renderBrands, brand: renderBrand };

document.addEventListener('DOMContentLoaded', async () => {
  const page = document.body.dataset.page;
  chrome(document.body.dataset.nav || 'index.html');
  const render = RENDERERS[page];
  if (!render) return;
  try {
    render(await loadData());
  } catch (err) {
    document.querySelector('#main').innerHTML =
      `<div class="wrap empty"><b>Deals aren't loading</b><p>${esc(err.message)}</p></div>`;
  }
});
