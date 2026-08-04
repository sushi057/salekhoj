# Analytics

## Comparison (verified August 2026)

| Option | Cost | Free-tier events | Outbound-link / custom events on free tier | Script size | Cookieless / no consent |
|---|---|---|---|---|---|
| **GoatCounter (hosted)** | Free for non-commercial/low-traffic use | "reasonable" use, no hard cap | Yes — `event: true` in `count()`, built-in | ~3.5 KB | Yes, no cookies |
| Plausible Cloud | No free tier, 30-day trial then from $9/mo | 10,000/mo on cheapest paid plan | Yes, but paid only | ~1 KB | Yes |
| Umami Cloud | Free Hobby plan | 100,000 events/mo, 3 sites | Yes, on free plan | ~2 KB | Yes |
| Cloudflare Web Analytics | Free | Unlimited pageviews | **No** — no custom events at all | tiny (beacon) | Yes |
| Counter.dev | Free | Unlimited pageviews | **No** — pageviews only, no events endpoint | tiny | Yes |

Cloudflare and Counter.dev are disqualified outright: no custom-event support means no per-store
outbound click counts, which is the entire point of this exercise. Plausible has no free tier
anymore. Umami's free tier is generous and would also work, but requires an account with a
100K/mo cap that Umami's own product cross-sells past.

## Recommendation: GoatCounter (hosted, free plan)

- Free for a non-commercial/low-traffic site like this one; no card required.
- Cookieless, GDPR-friendly by design — no consent banner needed.
- Custom/click events are a first-class feature (`goatcounter.count({path, event: true})`),
  exactly what "outbound click per store" needs.
- Tiny script (`count.js`, ~3.5 KB), loaded async — no render-blocking, no measurable slowdown.
- If it's ever outgrown, GoatCounter is also open source and self-hostable as a single Go
  binary — no VPS/Postgres commitment required today, but an escape hatch exists later.

## What the human must do (I cannot create accounts)

1. Sign up at https://www.goatcounter.com/signup — pick a site code, e.g. `salekhoj`.
2. In `site/app.js`, replace the placeholder:
   ```js
   const GOATCOUNTER_CODE = 'REPLACE-WITH-GOATCOUNTER-SITE-CODE';
   ```
   with the real site code (the subdomain part of `https://<code>.goatcounter.com`).
3. Nothing else — no DNS changes needed for the hosted plan.

## Implementation notes

- `chrome()` in `site/app.js` runs on every page already (shared header/footer injection), so
  the GoatCounter script tag and the outbound-click listener are added once there — no changes
  needed to any of the 5 HTML files.
- Each product card (`card()` in `app.js`) now carries `data-brand="<store domain>"`. A single
  delegated `click` listener on `document` (set up once per page load, not per card — there are
  10,876 products) reads `data-brand` off the clicked `.card` and fires
  `goatcounter.count({ path: 'click-<brand>', event: true })`. GoatCounter's dashboard groups
  by `path`, so "click-tudoholic.com" becomes a countable per-store event — that's the number
  behind "we sent your store N visitors."
- Pageviews are tracked automatically by `count.js` on load — no extra code needed for that.

## Custom events for later ("Notify me when price drops")

Not built (out of scope for this task), but the mechanism is already proven: call
`window.goatcounter.count({ path: 'notify-<brand>-<product-id>', event: true })` from the
button's click handler and do nothing else. GoatCounter counts it as a distinct event with no
extra setup, quota, or paid tier required.

## Querying analytics from Claude Code (MCP server)

`.mcp.json` at the repo root wires up [goatcounter-mcp-server](https://github.com/rafaljanicki/goatcounter-mcp-server)
(read-only: `get_me`, `list_sites`, `list_paths`, `get_stats_total`, `get_stats_hits`,
`get_stats_refs`, `get_stats_browsers`, `get_stats_systems`, `get_stats_sizes`,
`get_stats_locations` — GET requests to `{code}.goatcounter.com` only, no write/delete
endpoints wired up). Runs via `uvx`, no vendored copy. Needs `fastmcp==2.2.6` pinned exactly
(newer fastmcp removed a constructor kwarg the server uses and crashes on startup) — already
pinned in `.mcp.json` via `--with`.

Once the GoatCounter account exists (see above), a human must:

1. Log in to `https://<code>.goatcounter.com`, go to **Settings → API**.
2. Create a new API token. Grant it the **read-only** permission scope only — GoatCounter's
   token permissions are scoped per-section (e.g. "Read stats"/export); do not grant the
   write/count-import or site-settings scopes, the MCP server never needs them.
3. Export the token and site code as env vars wherever you launch `claude` from this repo
   (shell profile, or a project-root `.env` file — already covered by `.gitignore`'s `.env*`):
   ```sh
   export GOATCOUNTER_CODE=salekhoj          # the subdomain, no ".goatcounter.com"
   export GOATCOUNTER_API_KEY=<the token>
   ```
4. Restart Claude Code in this project. Confirm it worked by asking Claude to call the
   `list_sites` or `get_me` MCP tool — it should return real account/site JSON instead of an
   env-var error.
