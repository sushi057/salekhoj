"""Phase 0 steps 3-5: pull products from tier-1 sites, keep only real discounts.

Two extractors cover every tier-1 site we found:
  shopify              -> /products.json          (variants[].compare_at_price)
  woocommerce-store-api-> /wp-json/wc/store/products (prices.regular_price vs sale_price)

A product is "on sale" only if we parsed BOTH an original and a lower current price
and the discount lands in [5%, 90%]. Anything else is dropped, never guessed.

Usage: python3 extract.py ../data/sites.json > ../data/products.json
"""
import json, re, sys, time, html, concurrent.futures as cf, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
TIMEOUT = 30
# 85% ceiling, not 90%: at the top of the range a "discount" is nearly always a decimal-shift
# typo in the store's compare-at price (a Lenovo IdeaPad listed at Rs 760,000 -> Rs 68,499).
# Costs a handful of genuine clearances; a fake headline number is the worse failure here.
MIN_PCT, MAX_PCT = 5, 85
MAX_PAGES = 12          # ponytail: hard cap on pagination; raise if a store outgrows it


def get_json(url, tries=3):
    """Nepali hosting is slow and flaky; retry before giving up on a page."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def money(v):
    """Parse a price to float NPR. Returns None for junk/zero."""
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").strip())
    except ValueError:
        return None
    return f if f > 0 else None


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def deal(orig, now):
    """The whole point of the project. Both prices or nothing."""
    if not orig or not now or now >= orig:
        return None
    pct = int((orig - now) / orig * 100)   # floor, matching how the stores label it
    return pct if MIN_PCT <= pct <= MAX_PCT else None


# ponytail: hardcoded FX. Only used to sort/filter mixed-currency stores by price.
# Swap for a rates API if we ever list many non-NPR sellers.
FX_TO_NPR = {"NPR": 1, "USD": 141, "INR": 1.6, "EUR": 153, "GBP": 180, "AUD": 92}

# Products that belong to none of our four verticals: groceries, furniture, books, toys...
DROP_HINT = re.compile(
    r"grocery|furniture|sofa|book\b|stationer|\btoy\b|decor|kitchen(?!.*appliance)|"
    r"rice.?cooker|utensil|crockery|curtain", re.I)

# Each vertical's own-title/category signal. Checked in this order; first match wins
# UNLESS the site hint disagrees and the match is weak (see classify()).
VERTICAL_HINTS = {
    "Electronics": re.compile(
        r"phone|smartphone|mobile|laptop|desktop|computer|pc\b|tablet|ipad|earphone|"
        r"earbud|headphone|speaker|charger|power ?bank|camera|dslr|drone|console|"
        r"gaming|router|cctv|smartwatch|smart.?watch|gadget|adapter|cable\b|ssd|"
        r"processor|monitor|keyboard|mouse\b|projector|television|\btv\b|appliance|"
        r"refrigerator|microwave|air ?conditioner|washing machine", re.I),
    "Beauty": re.compile(
        r"skincare|skin care|makeup|make-?up|cosmetic|lipstick|foundation|concealer|"
        r"mascara|eyeliner|serum|moisturi[sz]er|sunscreen|cleanser|toner|shampoo|"
        r"conditioner|haircare|hair care|fragrance|perfume|attar|deodorant|grooming|"
        r"razor|shaving|nail polish|face wash|body lotion|beauty", re.I),
    "Fitness": re.compile(
        r"protein|whey|supplement|creatine|bcaa|multivitamin|gym|dumbbell|barbell|"
        r"treadmill|yoga mat|resistance band|kettlebell|fitness|workout|activewear|"
        r"gymwear|fitness tracker|smartband|shaker\b|exercise", re.I),
    "Fashion": re.compile(
        r"shirt|t-?shirt|top|dress|skirt|pant|trouser|jean|short|jacket|coat|hoodie|"
        r"sweater|knit|merino|v-?neck|high-?neck|crew-?neck|turtleneck|blazer|"
        r"kurta|saree|sari|kurti|lehenga|suit|blouse|legging|sock|shoe|"
        r"sneaker|boot|sandal|heel|slipper|footwear|bag|backpack|purse|wallet|belt|"
        r"cap|hat|beanie|scarf|shawl|glove|accessor|apparel|clothing|wear|outfit|"
        r"unisex|necklace|pendant|earring|bangle|bracelet|mangalsutra|jewel|"
        r"sunglass|eyeglass|optical frame|eyewear", re.I),
}

# A generic word like "case" or "accessories" means something different per vertical —
# resolved only via the site hint, never on its own.
AMBIGUOUS_ACCESSORY = re.compile(r"\bcase\b|\baccessor|\bstrap\b|\bcover\b", re.I)


def classify(item, hint=None):
    """Which of the four verticals this product belongs to, or None to drop it.

    Own title/category is the primary signal; the site hint only breaks ties or
    resolves generic words ("case", "accessories") that mean different things on
    an electronics site vs. a fashion site.
    """
    hay = " ".join(filter(None, [item.get("category"), item["title"], *(item.get("tags") or [])]))
    if not hay:
        return hint if hint in VERTICAL_HINTS else None
    if DROP_HINT.search(hay):
        return None

    matches = [v for v, pat in VERTICAL_HINTS.items() if pat.search(hay)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # e.g. "gym shirt" hits both Fitness and Fashion — prefer the site hint if it's
        # one of the matches, otherwise keep the first hit in vertical-priority order.
        if hint in matches:
            return hint
        return matches[0]

    # Nothing vertical-specific in the text itself. A bare "accessories"/"case"/"cover"
    # only makes sense read through the site's own vertical.
    if AMBIGUOUS_ACCESSORY.search(hay) and hint in VERTICAL_HINTS:
        return hint

    # No signal at all: drop rather than trust the hint. Multi-category grab-bag sites
    # (megashopnepal, tudoholic, imartnepal...) make hint-only fallback confidently wrong.
    return None


# Store categories are a mess ("STOCK MEN", "Baby Boy (0 - 1) Year", "Hazaar Bazaar").
# Bucket them once here so the site stays dumb. Order matters: first match wins.
BUCKETS = {
    "Fashion": [
        ("Footwear", r"shoe|sneaker|boot|sandal|heel|slipper|footwear|loafer|flip.?flop"),
        ("Bags",     r"\bbag|backpack|purse|wallet|clutch|luggage|tote"),
        ("Accessories", r"accessor|cap\b|hat\b|beanie|scarf|shawl|belt|glove|sock|jewel|watch|sunglass"),
        ("Kids",     r"kid|baby|child|boy|girl|infant|toddler"),
        ("Women",    r"women|ladies|female|dress|skirt|saree|sari|kurti|lehenga|blouse|legging"),
        ("Men",      r"\bmen\b|male|gents"),
    ],
    "Electronics": [
        ("Phones",   r"phone|smartphone|mobile"),
        ("Computers", r"laptop|desktop|computer|pc\b|tablet|ipad|keyboard|mouse\b|monitor|ssd|processor"),
        ("Audio",    r"earphone|earbud|headphone|speaker"),
        ("Cameras",  r"camera|dslr|drone"),
        ("Gaming",   r"gaming|console"),
        ("Home Appliances", r"refrigerator|microwave|air ?conditioner|washing machine|television|\btv\b|appliance"),
        ("Accessories", r"smartwatch|smart.?watch|fitness tracker|smartband|wearable|charger|power ?bank|cable\b|adapter|case\b|cover\b|strap\b|router|cctv"),
    ],
    "Beauty": [
        ("Skincare", r"skincare|skin care|serum|moisturi[sz]er|sunscreen|cleanser|toner|face wash|body lotion"),
        ("Makeup",   r"makeup|make-?up|cosmetic|lipstick|foundation|concealer|mascara|eyeliner|nail polish"),
        ("Haircare", r"haircare|hair care|shampoo|conditioner"),
        ("Fragrance", r"fragrance|perfume|attar|deodorant"),
        ("Grooming", r"grooming|razor|shaving"),
    ],
    "Fitness": [
        ("Supplements", r"protein|whey|supplement|creatine|bcaa|multivitamin"),
        ("Equipment",   r"dumbbell|barbell|treadmill|yoga mat|resistance band|kettlebell|shaker\b"),
        ("Wearables",   r"fitness tracker|smartband|smartwatch|smart.?watch"),
        ("Activewear",  r"activewear|gymwear|workout"),
    ],
}


def bucket(item, vertical):
    hay = " ".join(filter(None, [item.get("category"), item["title"], *(item.get("tags") or [])]))
    for name, pat in BUCKETS.get(vertical, []):
        if re.search(pat, hay, re.I):
            return name
    return "Other"


def shopify_meta(domain):
    """/meta.json states the store's currency AND country outright — no scraping the page
    and no guessing. 'Neu Nomads' and 'Sherpa Adventure Gear' both read as US/USD here,
    which is the only reliable way to tell them from a Kathmandu shop."""
    try:
        m = get_json(f"https://{domain}/meta.json", tries=2)
        return (m.get("currency") or "NPR"), (m.get("country") or "")
    except Exception:
        return "NPR", ""      # unknown; the NPR/NP filter downstream decides what to do


def from_shopify(domain):
    items = []
    cur, country = shopify_meta(domain)
    for page in range(1, MAX_PAGES + 1):
        try:
            data = get_json(f"https://{domain}/products.json?limit=250&page={page}")
        except Exception:
            break  # keep whatever pages already succeeded
        prods = data.get("products", [])
        if not prods:
            break
        for p in prods:
            # cheapest available variant represents the product
            avail = [v for v in p.get("variants", []) if v.get("available")] or p.get("variants", [])
            if not avail:
                continue
            v = min(avail, key=lambda v: money(v.get("price")) or 9e9)
            now, orig = money(v.get("price")), money(v.get("compare_at_price"))
            pct = deal(orig, now)
            if pct is None:
                continue
            imgs = p.get("images") or []
            items.append({
                "brand": domain, "title": clean(p.get("title")),
                "url": f"https://{domain}/products/{p.get('handle')}",
                "image": (imgs[0].get("src") if imgs else None),
                "price": now, "original_price": orig, "discount_pct": pct,
                "currency": cur, "country": country,
                "category": clean(p.get("product_type")) or None,
                "tags": [clean(t) for t in (p.get("tags") or [])][:8],
            })
    return items


def from_woo(domain):
    items = []
    for page in range(1, MAX_PAGES + 1):
        try:
            data = get_json(f"https://{domain}/wp-json/wc/store/products?per_page=100&page={page}")
        except Exception:
            break
        if not isinstance(data, list) or not data:
            break
        for p in data:
            pr = p.get("prices") or {}
            # Woo returns integer minor units, e.g. "349900" with currency_minor_unit 2
            scale = 10 ** (pr.get("currency_minor_unit") or 0)
            now = money(pr.get("sale_price") or pr.get("price"))
            orig = money(pr.get("regular_price"))
            now = now / scale if now else None
            orig = orig / scale if orig else None
            pct = deal(orig, now)
            if pct is None:
                continue
            imgs = p.get("images") or []
            cats = [clean(c.get("name")) for c in (p.get("categories") or [])]
            items.append({
                "brand": domain, "title": clean(p.get("name")),
                "url": p.get("permalink"),
                "image": (imgs[0].get("src") if imgs else None),
                "price": now, "original_price": orig, "discount_pct": pct,
                "currency": pr.get("currency_code") or "NPR",
                "category": cats[0] if cats else None,
                "tags": cats[:8],
            })
    return items


EXTRACTORS = {"shopify": from_shopify, "woocommerce-store-api": from_woo}


def scrape(site):
    fn = EXTRACTORS.get(site.get("platform"))
    if not fn:
        return site["domain"], [], "no extractor"
    try:
        return site["domain"], fn(site["domain"]), None
    except Exception as e:
        return site["domain"], [], f"{type(e).__name__}: {e}"


def demo():
    """One runnable check on the logic that actually matters: discount + classifier."""
    assert deal(1000, 800) == 20
    assert deal(2699, 1199) == 55            # matches the site's own "55% OFF" label
    assert deal(1000, 990) is None           # 1% — noise, not a deal
    assert deal(1000, 50) is None            # 95% — almost always a data error
    assert deal(760000, 68499) is None       # real row: store typo'd 76,000 as 760,000
    assert deal(1000, 140) is None           # 86% — past the ceiling
    assert deal(1000, 150) == 85             # exactly 85% still counts
    assert deal(None, 800) is None and deal(1000, None) is None
    assert deal(1000, 1000) is None and deal(800, 1000) is None
    assert money("1,299.00") == 1299 and money("0") is None and money("free") is None

    assert classify({"title": "Cotton Kurta", "category": "STOCK WOMEN", "tags": []}) == "Fashion"
    assert classify({"title": "Whey Protein 2kg", "category": "Supplements", "tags": []}) == "Fitness"
    assert classify({"title": "SPF 50 Sunscreen", "category": "Skincare", "tags": []}) == "Beauty"
    # phone case on an electronics site is Electronics, not Fashion (hint resolves the
    # generic "case" word which alone means nothing)
    assert classify({"title": "iPhone 13 Case", "category": "Accessories", "tags": []},
                     hint="Electronics") == "Electronics"
    # clothing shop that also lists a protein shaker: the product's own words win over the hint
    assert classify({"title": "Protein Shaker Bottle", "category": None, "tags": []},
                     hint="Fashion") == "Fitness"
    assert classify({"title": "3-Seater Sofa", "category": "Furniture", "tags": []}) is None
    assert classify({"title": "Rice Cooker 1.5L", "category": "Kitchen Appliance", "tags": []}) is None
    assert classify({"title": "Spiral Notebook", "category": "Stationery", "tags": []}) is None
    # no vertical text signal -> drop, even with a hint from a multi-category grab-bag site
    assert classify({"title": "High Pressure Washer Multipurpose Cleaning System",
                      "category": None, "tags": []}, hint="Fitness") is None
    assert classify({"title": "High-End Portable Jewelry Box Earrings Ring Organizer",
                      "category": None, "tags": []}, hint="Fashion") != "Beauty"

    assert bucket({"title": "Running Sneaker", "category": "STOCK MEN", "tags": []}, "Fashion") == "Footwear"
    assert bucket({"title": "Cotton Kurta", "category": "STOCK WOMEN", "tags": []}, "Fashion") == "Women"
    assert bucket({"title": "Plain Tee", "category": "STOCK MEN", "tags": []}, "Fashion") == "Men"
    assert bucket({"title": "Leather Tote Bag", "category": None, "tags": []}, "Fashion") == "Bags"
    assert bucket({"title": "iPhone 13", "category": None, "tags": []}, "Electronics") == "Phones"
    assert bucket({"title": "Whey Protein", "category": None, "tags": []}, "Fitness") == "Supplements"
    assert bucket({"title": "SPF 50 Sunscreen", "category": None, "tags": []}, "Beauty") == "Skincare"
    assert bucket({"title": "ZL54CJ Sports Smartwatch", "category": None, "tags": []}, "Electronics") == "Accessories"
    print("ok")


# ---- coverage.md ----------------------------------------------------------

def zero_reason(site, err, raw, npr_items, kept):
    """Why a domain contributed zero deals — the whole point of the coverage doc."""
    tier = site.get("tier")
    if tier == "dead":
        return "dead/unreachable"
    if tier in ("2", "3"):
        return f"no structured feed (tier {tier}, extractor not built)"
    if err:
        return f"fetch error: {err}"
    if not raw:
        return "feed OK but zero discounts right now"
    if not npr_items:
        countries = {i.get("country") for i in raw if i.get("country")}
        currencies = {i.get("currency", "NPR") for i in raw}
        if countries and countries != {"NP"} and countries != {""}:
            other = sorted(c for c in countries if c not in ("NP", ""))
            return f"not Nepal-based (country={other[0] if other else '?'})"
        if currencies != {"NPR"}:
            return "non-NPR currency"
        return "feed OK but zero discounts right now"
    if not kept:
        return "deals found but none in tracked verticals (dropped as other/unclassified)"
    return ""


def write_coverage(path, sites_by_domain, results, per_domain_stats, all_items):
    """Every domain we know about, one row each — success or failure, always specific."""
    rows = []
    for domain in sorted(sites_by_domain):
        site = sites_by_domain[domain]
        stats = per_domain_stats.get(domain, {})
        rows.append({
            "domain": domain,
            "vertical_hint": site.get("vertical_hint") or "-",
            "tier": site.get("tier", "?"),
            "platform": site.get("platform") or "-",
            "country_currency": stats.get("country_currency", "-"),
            "seen": stats.get("seen", 0),
            "kept": stats.get("kept", 0),
            "dropped_other_vertical": stats.get("dropped_other_vertical", 0),
            "reason": stats.get("reason") or "-",
        })

    by_vertical = {}
    for i in all_items:
        by_vertical[i["vertical"]] = by_vertical.get(i["vertical"], 0) + 1
    contributing = sorted({i["brand"] for i in all_items})

    zero_rows = [r for r in rows if r["kept"] == 0]
    zero_by_reason = {}
    for r in zero_rows:
        zero_by_reason.setdefault(r["reason"], []).append(r["domain"])

    lines = []
    lines.append("# SaleKhoj coverage report")
    lines.append("")
    lines.append(f"Generated {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
                 f"from a live run of `build.sh`. Regenerate, never hand-edit.")
    lines.append("")
    lines.append(f"- **{len(all_items)} deals** kept from **{len(contributing)}/{len(rows)}** "
                 f"contributing domains")
    for v in ("Fashion", "Electronics", "Beauty", "Fitness"):
        lines.append(f"  - {v}: {by_vertical.get(v, 0)}")
    lines.append(f"- **{len(zero_rows)} domains yielded zero** deals")
    lines.append("")
    lines.append("## Per-domain")
    lines.append("")
    lines.append("| domain | declared vertical | tier | platform | country/currency | "
                 "seen | kept | dropped-other-vertical | status |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r['domain']} | {r['vertical_hint']} | {r['tier']} | {r['platform']} | "
                     f"{r['country_currency']} | {r['seen']} | {r['kept']} | "
                     f"{r['dropped_other_vertical']} | {r['reason']} |")
    lines.append("")
    lines.append("## Zero-yield sites, grouped by reason")
    lines.append("")
    lines.append("Where the next engineering effort pays off.")
    lines.append("")
    for reason in sorted(zero_by_reason):
        domains = sorted(zero_by_reason[reason])
        lines.append(f"- **{reason}** ({len(domains)}): {', '.join(domains)}")
    lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        return demo()

    all_sites = json.load(open(sys.argv[1]))
    sites_by_domain = {s["domain"]: s for s in all_sites}
    tier1 = [s for s in all_sites if s.get("tier") == "1"]
    with cf.ThreadPoolExecutor(6) as ex:
        results = list(ex.map(scrape, tier1))

    # A store that prices in USD/INR/EUR is selling to customers abroad, not to a shopper in
    # Kathmandu — the deal isn't actionable here even when the brand is Nepali. Dropped rather
    # than shown. Their domains stay in all_sites.txt; flip this off to bring them back.
    NPR_ONLY = True

    all_items, report, per_domain_stats = [], [], {}
    for domain, items, err in results:
        raw = items
        npr_items = [i for i in raw
                     if i.get("currency", "NPR") == "NPR"
                     and i.get("country", "NP") in ("NP", "")] if NPR_ONLY else raw
        hint = sites_by_domain[domain].get("vertical_hint")
        keep = []
        for i in npr_items:
            v = classify(i, hint)
            if v is None:
                continue
            i["vertical"] = v
            keep.append(i)
        all_items += keep

        countries = sorted({i.get("country") or "-" for i in raw}) or ["-"]
        currencies = sorted({i.get("currency", "NPR") for i in raw}) or ["-"]
        per_domain_stats[domain] = {
            "country_currency": f"{'/'.join(countries)} / {'/'.join(currencies)}" if raw else "-",
            "seen": len(raw),
            "kept": len(keep),
            "dropped_other_vertical": len(npr_items) - len(keep),
        }
        per_domain_stats[domain]["reason"] = zero_reason(
            sites_by_domain[domain], err, raw, npr_items, keep)

        report.append(f"{domain:26} {len(keep):5} deals "
                      f"({len(items) - len(keep):4} dropped)  {err or ''}")
    for line in sorted(report):
        print(line, file=sys.stderr)

    for i in all_items:
        i["price_npr"] = round(i["price"] * FX_TO_NPR.get(i.get("currency", "NPR"), 1))
        i["bucket"] = bucket(i, i["vertical"])

    # non-tier-1 domains never went through scrape() at all; still need a coverage row
    for s in all_sites:
        if s["domain"] not in per_domain_stats:
            per_domain_stats[s["domain"]] = {
                "country_currency": "-", "seen": 0, "kept": 0, "dropped_other_vertical": 0,
                "reason": zero_reason(s, None, [], [], []),
            }

    all_items.sort(key=lambda i: -i["discount_pct"])
    brands = sorted({i["brand"] for i in all_items})
    print(f"\nTOTAL {len(all_items)} deals from {len(brands)}/{len(all_sites)} sites",
          file=sys.stderr)

    coverage_path = sys.argv[2] if len(sys.argv) > 2 else None
    if coverage_path:
        write_coverage(coverage_path, sites_by_domain, results, per_domain_stats, all_items)

    json.dump({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "brands": brands,
        "products": all_items,
    }, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
