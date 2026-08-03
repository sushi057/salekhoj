"""Phase 0 step 2: probe each candidate site, classify how hard it is to scrape.

Tier 1 = Shopify /products.json (structured, has compare_at_price -> discounts for free)
Tier 2 = HTML with JSON-LD Product markup
Tier 3 = needs a real browser (Camoufox) or per-site selectors
dead    = unreachable

Usage: python3 fingerprint.py sites.txt > ../data/sites.json
"""
import json, re, sys, concurrent.futures as cf, urllib.request, urllib.error

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
TIMEOUT = 20


def get(url, limit=400_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read(limit).decode("utf-8", "replace"), r.geturl()


def probe(domain):
    out = {"domain": domain, "tier": "dead", "platform": None, "notes": []}
    base = f"https://{domain}"

    # Tier 1: Shopify products.json — the jackpot. compare_at_price is the discount.
    try:
        st, body, _ = get(f"{base}/products.json?limit=5")
        data = json.loads(body)
        prods = data.get("products", [])
        if prods:
            variants = [v for p in prods for v in p.get("variants", [])]
            on_sale = sum(1 for v in variants if v.get("compare_at_price"))
            out.update(tier="1", platform="shopify",
                       sample_products=len(prods),
                       sample_variants=len(variants),
                       variants_with_compare_at=on_sale,
                       sample_title=prods[0].get("title"))
            return out
    except Exception as e:
        out["notes"].append(f"products.json: {type(e).__name__}")

    # Tier 2/3: fetch homepage, look for platform markers and JSON-LD
    try:
        st, html, final = get(base)
    except Exception as e:
        out["notes"].append(f"home: {type(e).__name__}: {e}")
        return out

    out["final_url"] = final
    low = html.lower()
    for marker, name in (("cdn.shopify.com", "shopify"), ("woocommerce", "woocommerce"),
                         ("wp-content", "wordpress"), ("wixstatic", "wix"),
                         ("magento", "magento"), ("opencart", "opencart"),
                         ("nuxt", "nuxt/vue"), ("__next_data__", "next.js")):
        if marker in low:
            out["platform"] = name
            break

    ldjson = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I)
    types = set()
    for block in ldjson:
        try:
            d = json.loads(block)
        except Exception:
            continue
        for node in (d if isinstance(d, list) else [d]):
            if isinstance(node, dict):
                t = node.get("@type")
                types.update(t if isinstance(t, list) else [t])
    out["ldjson_types"] = sorted(t for t in types if t)

    # WooCommerce exposes a public REST product endpoint on many installs
    if out["platform"] in ("woocommerce", "wordpress"):
        try:
            st, body, _ = get(f"{base}/wp-json/wc/store/products?per_page=5")
            wc = json.loads(body)
            if isinstance(wc, list) and wc:
                sale = sum(1 for p in wc if (p.get("prices") or {}).get("sale_price")
                           != (p.get("prices") or {}).get("regular_price"))
                out.update(tier="1", platform="woocommerce-store-api",
                           sample_products=len(wc), variants_with_compare_at=sale,
                           sample_title=wc[0].get("name"))
                return out
        except Exception as e:
            out["notes"].append(f"wc-store-api: {type(e).__name__}")

    # Does the raw HTML even contain prices? If not, it's JS-rendered -> tier 3.
    has_price = bool(re.search(r'(Rs\.?|NPR|रू)\s?\d{2,}', html))
    out["price_in_html"] = has_price
    out["tier"] = "2" if (has_price or "Product" in out["ldjson_types"]) else "3"
    return out


def parse_sites(path):
    """domain<TAB>vertical, one per line. Missing vertical = no hint."""
    out = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        domain = parts[0]
        hint = parts[1] if len(parts) > 1 else None
        out.append((domain, hint))
    return out


def main():
    sites = parse_sites(sys.argv[1])
    hints = dict(sites)
    domains = [d for d, _ in sites]
    with cf.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(probe, domains))
    for r in results:
        r["vertical_hint"] = hints.get(r["domain"])
    results.sort(key=lambda r: (r["tier"], r["domain"]))
    json.dump(results, sys.stdout, indent=2, ensure_ascii=False)
    by_tier = {}
    for r in results:
        by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    print(f"\n// tiers: {by_tier}", file=sys.stderr)


if __name__ == "__main__":
    main()
