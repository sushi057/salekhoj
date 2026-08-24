# SaleKhoj — working notes for Claude

Aggregates live fashion / electronics / beauty / fitness discounts from **Nepal-based** online
stores onto one static site. Scrapers emit JSON; the site reads it. No database, no server, no
framework, no build step for the frontend.

## Run it

```sh
./build.sh                       # probe sites -> extract deals -> write site/data.json + coverage
python3 -m http.server 8811 -d site     # serve the site locally
python3 scrapers/extract.py --check     # logic self-check, runs first inside build.sh
```

There is no backend. The site is static files all the way down — any static host serves it.

`build.sh` hits the live network and takes several minutes. Don't run it to test a frontend
change — `site/data.json` is already there.

**Price history was removed** (Aug 2026, user's call): `scrapers/archive.py` and `data/history/`
are gone and `build.sh` no longer appends daily snapshots. This matches the long-standing
"Price history" entry under Non-goals, which `archive.py` had been quietly contradicting.

## Deploy and refresh

Public repo -> free GitHub Pages at `https://sushi057.github.io/salekhoj/` (a **subpath**, so
every link and asset reference must stay relative — no leading `/`).

- `.github/workflows/refresh.yml` — daily at `00:17 UTC` (~06:00 Nepal, deliberately off the
  hour; GitHub's scheduler congests at `:00`). Builds, gates, commits the small records,
  deploys to Pages.
- `scrapers/gate.py` — refuses to publish a collapsed build (floors: 70% of last-good deals,
  80% of last-good contributing domains). `data/last-good.json` is the baseline. `--force`
  overrides. Tested against simulated collapses; keep it that way.
- **No `push` trigger, on purpose.** CI does not commit `site/data.json`, so a
  push-triggered deploy would publish the frozen committed copy and roll live prices back
  until the next nightly run. Re-scraping on every push would instead hammer 211 stores and
  could retrigger itself, since the refresh commits to `master`. After a UI change, dispatch
  the workflow manually: `gh workflow run refresh.yml`.

Two traps worth knowing:

- **`site/data.json` is never committed by CI.** 5 MB of single-line JSON daily is ~300 MB/year
  of history. CI builds it and uploads it to Pages as an artifact. The committed copy is a
  stale-but-usable fixture for local frontend work — refresh it by hand when it drifts.
- **The gate step sets `shell: bash`.** That is load-bearing: GitHub's default `run` shell is
  `bash -e` *without* pipefail, so `gate.py ... | tee` would swallow a non-zero exit and deploy
  the collapsed build while reporting success. Verified: `bash -e -c 'false | tee' ` exits 0.

## Layout

```
scrapers/all_sites.txt    domain<TAB>vertical, the input list
scrapers/fingerprint.py   probe each domain -> tier 1/2/3/dead      -> data/sites.json
scrapers/extract.py       tier-1 sites -> classified, priced deals  -> data/products.json
scrapers/playtest.js      60 headless checks (puppeteer)
site/                     5 static pages + app.js + style.css + data.json + og.png/sitemap
scrapers/gate.py          publish-or-refuse guard for the automated refresh
.github/workflows/        refresh.yml — daily rebuild -> gate -> GitHub Pages
data/coverage.md          generated every build — never hand-edit
```

`site/data.json` is a copy of `data/products.json`. `build.sh` does the copying.

## The rules that matter

**A deal is two prices or it doesn't exist.** The store must publish a current price *and* a
higher original price. Never infer a discount from a "SALE" badge, never guess a percentage.
See `deal()`.

**Discount band is 5–85%, floor-rounded.** Floor because that's how stores label it. The 85%
ceiling is not arbitrary — above it the data is dominated by decimal-shift typos in store
compare-at prices (one store listed a Rs 77,000 laptop as Rs 760,000, i.e. a fake "90% off").
A few genuine clearances are lost; publishing a fake headline number is the worse failure.

**Nepal-based only.** Shopify `/meta.json` declares `country` and `currency`; the gate is
`NP` + `NPR`. This deliberately excludes brands that are Nepali in spirit but sell abroad in
USD/INR/EUR — a shopper in Kathmandu can't act on those. `NPR_ONLY` in `extract.py` flips it.
Do not "fix" the drop in volume by loosening this.

**The vertical hint is a hint.** `all_sites.txt` tags each domain with a vertical, but the
product's own title/category decides. The hint only breaks ties (a "gym shirt" matching both
Fitness and Fashion) and resolves words that mean different things per store ("case", "cover",
"strap"). **No text signal ⇒ drop the product.** Never fall back to the hint alone: Nepali
stores are frequently multi-category grab-bags, and hint-fallback confidently filed a pressure
washer under Fitness and a jewelry box under Beauty.

## Scraper tiers

| Tier | Meaning | Status |
|---|---|---|
| 1 | Shopify `/products.json` or WooCommerce Store API | working, no per-site code |
| 2 | Prices in HTML: sitemap -> product pages -> JSON-LD price + struck original | working, no per-site selectors |
| 3 | JS-rendered or blocking, needs a real browser | not built |

Three extractors cover every tier-1/2 site with zero per-site code. Camoufox was planned for
tier 3 and turned out to be unnecessary so far — don't install it without a concrete site that
needs it.

Tier 2 (`from_html` in `extract.py`) trusts only structured markup for the current price
(JSON-LD `offers.price` or an og/product price meta) and only text struck through
(`<del>/<s>/<strike>` or an old/was/regular/compare class) for the original — never guessed
from loose page text. The struck-price search is windowed to text near where the current price
itself is printed on the page; without that a "related products"/"recently viewed" rail lower
on the page can contribute its own struck price as if it were this product's original. A
domain is dropped outright if more than 2 parsed items share one identical title — several
"stores" are JS apps that serve one identical prerendered page for every product URL.

## Coverage report

`data/coverage.md` is regenerated by every build and is the record of what we search and what we
get, **including the failures** — that's the point. Every zero carries a specific reason
("dead/unreachable", "not Nepal-based (country=US)", "no structured feed (tier 2, extractor not
built)", "feed OK but zero discounts right now"). Zero-yield sites are grouped by reason.

**Counts move between runs.** Nepali hosting is slow and flaky; a site that times out
contributes zero that day (maayus.com: 718 deals one run, "dead" the next). Don't read
run-to-run deltas as signal — use the coverage report to tell real decay from noise.

## Frontend

Vanilla JS + CSS. `app.js` injects the shared header/footer via `chrome()` and dispatches on
`document.body.dataset.page`. Pages: index (home), deals (filters), brands, brand, about.

- Theme: three-state toggle (auto/light/dark). Auto follows the OS, falling back to local time
  (dark 19:00–06:00) when the OS states no preference. An **inline synchronous script in each
  `<head>`** stamps `data-theme` before first paint — it must stay inline, deferred is too late.
  `:root[data-theme=…]` must beat the media query in both directions.
- `spread()` caps each store to 2 products per rail. Without it the deepest-discounting store
  owns the entire homepage, since rails sort by discount.
- Bucket chips are scoped to the selected vertical. Showing "Footwear, Phones, Skincare,
  Supplements" in one list is meaningless.
- **SEO**: the site is client-rendered, so the raw HTML a crawler receives is exactly the head
  tags — that is the whole on-page story until pages are prerendered. Every page carries title,
  description, canonical, OG/Twitter, one `<h1>` and JSON-LD; `brand.html` is `noindex,follow`
  because it serves `?b=<domain>` and every variant is a near-duplicate of `brands.html`.
  `site/og.png` is generated from a template, not hand-drawn. Playtest asserts all of it.
- A closed `<details>` makes its contents inert (unfocusable) — that's why the deals filter
  panel needs one line of JS to hold `open` in sync with viewport width.
- **An open `<details>` lays its contents out in one anonymous content box.** A flex `gap` on
  the `<details>` itself therefore applies between `<summary>` and that box — *not* between the
  children you meant. The filter panel's group spacing silently did nothing for this reason;
  the rhythm now hangs off an explicit `.filters-body`. Playtest asserts the gaps really render.
- **`color-scheme` must be declared per theme.** The `<select>` popup list, scrollbars and
  other native widgets are drawn by the OS, not by our CSS. Styling the closed `<select>` dark
  is not enough — without `color-scheme: dark` Chrome drew the Store and Sort popups white on
  a dark page, unreadable. Set alongside the colour tokens in all three `:root` blocks.
- The filter panel is **taller than the viewport** whenever no vertical is selected (24 category
  chips, 1284px against a 900px window), so `position: sticky` alone left its tail unreachable
  unless you scrolled to the bottom of the results. It now caps at `calc(100vh - 104px)` and
  scrolls itself, with the long Category list ordered last so every other filter is usable
  without scrolling at all. Below 860px the cap is removed — there it's a static `<details>`
  and an inner scroller would just trap the page scroll.
- Filter controls share one `.field` class (same height, padding, border, radius). Before that
  the search input carried inline styles and drifted out of alignment with the selects. The
  panel must stay free of inline *layout* styles — playtest checks this; the range's inline
  `--pct` is a live value and is allowed.
- The vertical bar (Fashion/Electronics/…) is a **deals-page control only**. On other pages it
  was a second nav row pointing somewhere else, and its 1px border was the line that flashed.
- Featured stores are a hardcoded list, `FEATURED` in `app.js` — `{domain, name, blurb}`, where
  `domain` matches the `brand` field in data.json and `name` overrides `storeName()` (which
  title-cases from the domain and can't know "MuscleBlaze" is camel-cased). Zero-deal stores are
  skipped; the section hides itself if none have deals.

### Layout stability (don't regress this)

Everything renders from a 5 MB `data.json` fetched after `DOMContentLoaded`, so anything
`chrome()` appends paints *before* a single card exists. Two shifts came from that, both fixed
and both now asserted by playtest (`CLS < 0.1` per page):

- **The footer** was appended while `#results` was empty, so it painted just under the header —
  a stray horizontal rule that then shot down the page. `main { min-height: calc(100vh - 64px) }`
  keeps it below the fold from the first paint. Measured 0.145–0.183 of the shift on its own.
- **The featured block** sits at the top of the home page, so revealing it after the fetch shoved
  everything down (0.26 CLS by itself). `renderFeaturedSkeleton()` runs synchronously before the
  fetch and reserves the exact space: store name and blurb come from `FEATURED` with no data
  needed, `.thumb` is a fixed `aspect-ratio: 3/4`, and `.card-title` is pinned to two lines so
  every card is a known height. `featShell()` is shared by the skeleton and the real render —
  **if you change one, change the other, or the swap starts shifting again.**

Before: index 0.307, deals 0.235, brands 0.145. After: 0.000–0.041.

## Verification — required, not optional

Any change to visible UI or scraping logic must be verified by running it, not by reasoning
about it. Every real bug in this project so far was found by looking at a rendered page or a
data sample, never by reading code: US stores masquerading as Nepali, USD prices shown as
rupees, one store owning the homepage, a pressure washer classified as fitness gear, a fake 90%
laptop discount.

```sh
python3 -m http.server 8811 -d site &
node scrapers/playtest.js        # 60 checks: desktop, mobile, dark mode, layout stability
```

Playwright MCP does not work here (no `/opt/google/chrome`). Use puppeteer-core with the cached
Chrome at `~/.cache/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome`.

After changing scraper logic: run `extract.py --check`, rebuild, then **eyeball a random sample
per vertical** — title, price, original price, classified bucket.

## Environment gotchas

- **Reddit is hard-blocked.** WebFetch refuses `reddit.com` and `old.reddit.com`, and the search
  index returns nothing for `site:reddit.com`. "What do real users recommend" research is not
  possible with current tooling. The current store lists are search-indexed, not user-vetted —
  a real weakness, not a solved problem. Don't burn agent time retrying this.
- WSL2, no system browser, no `jq`. Use Python or Node for JSON.
- Store discovery returns confident false positives — foreign brands with Nepali-sounding names
  (Neu Nomads/NY, Sherpa Adventure Gear/Colorado, several INR stores). Never trust a discovery
  list's nationality claim; `/meta.json` is the arbiter.

## Money

None yet, by decision. Outbound links are plain links. Affiliate links come later and get
labelled when they do. The sort order is never sold — the sort the user picks is the sort they
get. Keep `about.html` honest about this.

## Non-goals (deliberate)

Price history, user accounts, notifications, mobile app, a production backend. Don't add
speculative abstraction — this codebase is small on purpose. The site is a list of current
offers and nothing more.

**Price comparison was built and then removed** (Aug 2026) along with `server.js` and
`scrapers/marketplaces.js`. Cross-store matching worked, but a shopper can get the same answer
from a Google search and its AI summary, so the feature carried a live-scraper dependency and a
non-static backend for no real advantage. Don't rebuild it without a reason that survives that
comparison. If you do, the matcher lives in git history (`CMP` in `site/app.js`, before this
removal) and was precision-tuned against real data — recover it rather than re-deriving it.
