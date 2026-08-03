# SaleKhoj — Nepal fashion sale aggregator

Aggregate discounts/sales from Nepali fashion brands (clothing, shoes, bags) into one
browsable site. Outbound links now, affiliate/commission later.

## Decisions (locked)

- **Phase 0 must prove:** we can scrape 20–30 Nepali fashion sites and reliably detect
  a *real* discount (orig price vs sale price). Money comes later.
- **Revenue:** build for traffic first. Plain outbound links. Add Daraz affiliate /
  brand deals once there's traffic. Not a phase-0 blocker.
- **Scraping:** simplest thing that works, escalate only when forced —
  1. sitemap / JSON feed (Shopify `/products.json`, WooCommerce REST) ← free, structured
  2. plain HTTP + HTML parse (selectolax)
  3. Camoufox stealth browser ← only for JS-rendered or blocking sites
  Rate-limited, cached, daily refresh.
- **Stack:** scrapers (Python) emit `data/*.json`; static site reads it. No DB, no server.

## Phase 0 — RESULT: passed (2026-08-03)

92 domains probed. **56 were tier 1** — Shopify `/products.json` or the WooCommerce Store
API, both of which hand over the original price as structured JSON. Two extractors, no
per-site code, no browser. **Camoufox turned out to be unnecessary and was never installed**;
tiers 2 and 3 stay unbuilt until the coverage gap justifies the maintenance.

Verified, not assumed: pulled a live tudoholic product page and confirmed Rs 1,199 from
Rs 2,699 against the store's own "55% OFF" label. Rounding switched to floor to match.

Three data problems the raw numbers hid, all found by looking at the rendered page:

- **Non-fashion contamination.** Stores bolt gadgets/home/beauty onto the same catalogue
  (630 such items on tudoholic alone). Filtered by category, title keywords as fallback.
- **Foreign stores.** The discovery pass returned plenty of false positives — Neu Nomads
  (New York), Scott's Sweaters, Sherpa Adventure Gear (Colorado) — plus Nepali exporters
  pricing in USD/INR/EUR for customers abroad. A shopper in Kathmandu can't act on any of
  them. Shopify `/meta.json` states country and currency outright, so that's the gate now:
  NP + NPR or it doesn't ship.
- **One store owning the homepage.** Sorting purely by discount let the deepest-discounting
  store take every slot. Rails now cap each store at two.

Final: **3,656 fashion deals across 28 verified Nepal-based stores** (92 domains probed), every one with both
prices parsed from the store's own feed. Site playtested headless, 28/28 checks passing.

## Phase 0 — original plan (kept for the record)

**Kill criteria:** if <15 of 30 sites yield structured product+discount data, the
project isn't viable as designed and we rethink (fewer sites / manual curation).

1. **Discover + verify brands.** Seed list below is *unverified from memory* — first
   job is to confirm each domain exists, is a Nepali fashion retailer, and is
   reachable. Fill gaps to reach 30 via search.
2. **Fingerprint each site.** For each: platform (Shopify/WooCommerce/Wix/custom),
   robots.txt stance, whether products render without JS, whether a structured feed
   exists. Output: `data/sites.json` with a `tier` (1/2/3) per the escalation ladder.
3. **Build one generic extractor** that handles the two boring cases (Shopify
   products.json, WooCommerce/JSON-LD `Product` schema) — these likely cover most of
   the list with zero per-site code. Per-site selectors only for the stragglers.
4. **Discount detection.** A product counts as on sale only if we have both a
   compare-at/original price and a lower current price, both parsed as NPR integers,
   and 5% ≤ discount ≤ 90%. Everything else is "no discount", never guessed.
5. **Run it.** Produce `data/products.json` — real items, real prices, real links.
   Spot-check 20 random rows against the live pages by hand. Report the hit rate.

Deliverable: a number. "X of 30 sites working, N products, M on sale, spot-check
accuracy P%." Then we decide whether to build the site.

## Phase 1 — the site (only after Phase 0 passes)

Static HTML/JS reading `products.json`. Grid of sale items, filter by brand /
category / discount %, sort by discount. Search. That's it. No accounts, no
wishlists, no backend.

## Phase 2 — keep it fresh

Daily GitHub Actions cron: run scrapers, commit updated JSON, redeploy. Dead-site
alerting = a line in the run summary, not a monitoring stack.

## Phase 3 — money

Daraz Nepal affiliate. Direct brand deals. Sponsored placement. Revisit once traffic
is real.

## Seed brand list (UNVERIFIED — phase 0 step 1 confirms/replaces these)

Marketplaces: Daraz Nepal, SastoDeal, Bhatbhateni Online, Gyapu, Muncha, Hamrobazar
Footwear: Goldstar, Caravan, Kiwi, Shikhar, Nike/Adidas NP distributors
Apparel/bags: Kasa Style, Juju Wears, Thaili, Aarambha, Sanjhya, Fashion Hub NP,
Nepal Knot, Everest Fashion, Newroad-based multi-brand stores

30 is a target, not a constraint — 20 sites that actually work beat 30 that don't.

## Model routing

Opus: planning only (this doc). Sonnet: extractor + site code. Haiku: per-site
fingerprinting, link verification, bulk grunt work.

## Deliberate non-goals (v1)

Price history, user accounts, notifications, mobile app, non-fashion categories,
real-time scraping. All easy to add later; none needed to learn if this works.
