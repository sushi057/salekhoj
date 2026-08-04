"""Phase 0 steps 3-5: pull products from tier-1 and tier-2 sites, keep only real discounts.

Three extractors, no per-site code:
  shopify              -> /products.json          (variants[].compare_at_price)
  woocommerce-store-api-> /wp-json/wc/store/products (prices.regular_price vs sale_price)
  html (tier 2)        -> sitemap -> product pages (JSON-LD price + struck-out original)

A product is "on sale" only if we parsed BOTH an original and a lower current price
and the discount lands in [5%, 90%]. Anything else is dropped, never guessed.

Usage: python3 extract.py ../data/sites.json > ../data/products.json
"""
import json, re, sys, time, html, gzip, concurrent.futures as cf, urllib.request

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
    r"rice.?cooker|utensil|crockery|curtain|"
    r"wrench|screwdriver(?!.*(phone|mobile))|\bplier|spanner|hand tool|\bdrill\b", re.I)

# Each vertical's own-title/category signal. Checked in this order; first match wins
# UNLESS the site hint disagrees and the match is weak (see classify()).
VERTICAL_HINTS = {
    "Electronics": re.compile(
        r"phone|smartphone|mobile|laptop|desktop|computer|pc\b|tablet|ipad|earphone|"
        r"earbud|headphone|speaker|charger|power ?bank|camera|dslr|drone|console|"
        r"gaming|router|cctv|smartwatch|smart.?watch|gadget|adapter|cable\b|ssd|"
        r"processor|monitor|keyboard|mouse\b|projector|television|\btv\b|appliance|"
        r"refrigerator|microwave|air ?conditioner|washing machine|\bups\b", re.I),
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
        r"shirt|t-?shirt|\btops?\b|dress|skirt|pant|trouser|jean|short|jacket|coat|hoodie|"
        r"sweater|knit|merino|v-?neck|high-?neck|crew-?neck|turtleneck|blazer|"
        r"kurta|saree|sari|kurti|lehenga|suit(?!able)|blouse|legging|sock|shoe|"
        r"sneaker|boot|sandal|heel|slipper|footwear|bag|backpack|purse|wallet|belt|"
        r"\bcap\b|hat|beanie|scarf|shawl|glove|apparel|clothing|wear|outfit|umbrella|"
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
        ("Kids",     r"kid|baby|child|boy|girl|infant|toddler"),
        # Item-type buckets win over the gender fallback, so "Women Diamond Earrings"
        # files under Jewellery, not Women — same rule Footwear/Bags already followed.
        ("Jewellery", r"pendant|necklace|earring|bangle|mangalsutra|anklet|nosepin|nose.?pin|jhumka|bracelet|choker"),
        ("Eyewear",  r"eyeglass|spectacle|optical.?frame|goggle"),
        ("Accessories", r"accessor|cap\b|hat\b|beanie|scarf|shawl|belt|glove|sock|watch"),
        ("Women",    r"women|ladies|female|dress|skirt|saree|sari|kurti|lehenga|blouse|legging"),
        ("Men",      r"\bmen\b|male|gents"),
        ("Clothing", r"\bshirt\b|\btee\b|t-?shirt|blazer|jacket|coat|hoodie|sweater|sweatshirt|chino|trouser|pant|jean|\bshort\b|shacket|pajama|pyjama|vest|kurta|suit|jogger|windcheater"),
    ],
    "Electronics": [
        ("Phones",   r"phone|smartphone|mobile"),
        ("Computers", r"laptop|desktop|computer|pc\b|tablet|ipad|keyboard|mouse\b|monitor|ssd|processor"),
        ("Audio",    r"earphone|earbud|headphone|speaker"),
        ("Cameras",  r"camera|dslr|drone|binocular|monocular|telescope"),
        ("Gaming",   r"gaming|console"),
        ("Home Appliances", r"refrigerator|microwave|air ?conditioner|washing machine|television|\btv\b|appliance"),
        ("Accessories", r"smartwatch|smart.?watch|fitness tracker|smartband|wearable|charger|power ?bank|cable\b|adapter|case\b|cover\b|strap\b|router|cctv"),
    ],
    "Beauty": [
        ("Skincare", r"skincare|skin care|serum|moisturi[sz]er|sunscreen|cleanser|toner|face wash|body lotion"),
        ("Makeup",   r"makeup|make-?up|cosmetic|lipstick|foundation|concealer|mascara|eyeliner|eyeshadow|eyebrow|nail polish"),
        ("Haircare", r"haircare|hair care|shampoo|conditioner|hair.?mask|hair.?clay"),
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


# Installs with pretty permalinks off only answer the second form.
WOO_PATHS = ("https://{d}/wp-json/wc/store/products?per_page=100&page={p}",
             "https://{d}/?rest_route=/wc/store/products&per_page=100&page={p}")


def woo_feed(domain, page, path=None):
    for tmpl in ([path] if path else WOO_PATHS):
        try:
            data = get_json(tmpl.format(d=domain, p=page))
            if isinstance(data, list) and data:
                return data, tmpl
        except Exception:
            continue
    return None, path


def from_woo(domain):
    items, path = [], None
    for page in range(1, MAX_PAGES + 1):
        data, path = woo_feed(domain, page, path)
        if data is None:
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


# ---- tier 2: no feed, prices live in the product page's HTML -----------------
#
# One rule for every tier-2 store, no per-site selectors: the CURRENT price comes from
# the page's own structured markup (JSON-LD Product, or an itemprop/og price meta), and
# the ORIGINAL comes from whatever the template struck through (<del>/<s>/<strike>, or a
# class named old/was/regular/compare). Stores render "Rs 5,500" with a line through it
# precisely so a human reads it as the old price — that's the signal, and it survives
# template differences the way a CSS selector never does.
#
# The current price is deliberately NOT guessed from loose page text. An early version
# took the smallest price on the page and confidently returned a Rs 100 delivery fee and
# a EUR 44.72 foreign price as "current". Structured markup or nothing.

HTML_HDRS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip",
             "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
MAX_HTML_PAGES = 400     # ponytail: per-store page budget; raise if a big store gets truncated
HTML_WORKERS = 4         # concurrent page fetches per store — these are small shared hosts

# A price with an explicit Nepali currency marker. The marker is required: a bare number
# is how USD/EUR prices sneak in past the NPR gate.
NPR_PRICE = re.compile(r"(?:Rs\.?|NPR|रू|रु)\s*([\d,]+(?:\.\d+)?)|([\d,]{3,})\s*(?:Rs\.?|NPR|रू|रु)", re.I)
STRUCK = re.compile(r"<(del|s|strike)\b[^>]*>(.{0,400}?)</\1>", re.S | re.I)
OLD_CLASS = re.compile(
    r'<[^>]+class="[^"]*(?:price[-_]?old|old[-_]?price|was[-_]?price|regular[-_]?price|'
    r'compare[-_]?at|line-through|strike)[^"]*"[^>]*>(.{0,200}?)<', re.S | re.I)


def get_html(url, limit=1_200_000):
    req = urllib.request.Request(url, headers=HTML_HDRS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read(limit)
        if r.headers.get("Content-Encoding") == "gzip" or url.endswith(".gz"):
            body = gzip.decompress(body)
        return body.decode("utf-8", "replace")


def npr_amounts(fragment):
    out = []
    for m in NPR_PRICE.finditer(fragment):
        v = money((m.group(1) or m.group(2)).replace(",", ""))
        if v:
            out.append(v)
    return out


def sitemap_urls(domain, cap=6000):
    """Product URLs, straight from the store's own sitemap. Some sitemaps are
    double-escaped (&amp;amp;) — unescape twice or the URLs 404."""
    seen, out, queue = set(), [], [f"https://{domain}/sitemap.xml",
                                   f"https://{domain}/sitemap_index.xml"]
    while queue and len(out) < cap:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            body = get_html(u)
        except Exception:
            continue
        locs = [html.unescape(html.unescape(l))
                for l in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", body)]
        if "<sitemapindex" in body[:3000]:
            queue += [l for l in locs if l not in seen][:40]
        else:
            out += locs
    return out


NOT_PRODUCT = re.compile(
    r"/(blog|news|about|contact|faq|policy|terms|privacy|cart|checkout|account|login|"
    r"category|categories|collections?|brand|tag|author|page|search)(/|$)|"
    r"\.(jpg|jpeg|png|webp|pdf|xml)$", re.I)
LOOKS_PRODUCT = re.compile(r"/product|/products/|/p/|/shop/|/item", re.I)


def product_urls(domain):
    urls = [u for u in dict.fromkeys(sitemap_urls(domain)) if not NOT_PRODUCT.search(u)]
    narrowed = [u for u in urls if LOOKS_PRODUCT.search(u)]
    # Only trust the narrow "/product" pattern if it actually covers a meaningful chunk of
    # the sitemap. Stores with pretty-permalink URLs (choicemandu.com/baby-edge-safety-online)
    # have zero "/product" hits in real product URLs but a stray index.php?route=product link
    # or two — that used to make "narrowed" look non-empty and silently swallow the whole
    # real catalogue down to those few strays.
    use = narrowed if len(narrowed) >= max(10, len(urls) * 0.1) else urls
    return use[:MAX_HTML_PAGES]


def ld_product(page):
    """The deepest Product node in any JSON-LD block (some stores nest it under @graph)."""
    found = {}
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                            page, re.S | re.I):
        try:
            d = json.loads(block)
        except Exception:
            continue
        pool = list(d) if isinstance(d, list) else [d]
        if isinstance(d, dict):
            pool += [n for n in (d.get("@graph") or []) if isinstance(n, dict)]
        for node in pool:
            if isinstance(node, dict) and "Product" in str(node.get("@type")):
                found = node
    return found


def meta_content(page, *names):
    for n in names:
        m = re.search(r'<meta[^>]+(?:property|name|itemprop)=["\']%s["\'][^>]+content=["\']([^"\']*)'
                      % re.escape(n), page, re.I)
        if m:
            return html.unescape(m.group(1))
    return None


def window_near(page, now, radius=600):
    """Text around every place `now`'s value is printed on the page, joined together.
    Falls back to the whole page if the current price never appears as literal text
    (e.g. it's only in JSON-LD, injected client-side elsewhere) — better to search too
    wide than to search nowhere."""
    n = int(now) if now == int(now) else now
    needles = {str(n), f"{n:,}"}
    # (?<!\d) guards against "3,500" matching inside "23,500" — a rail item's price that
    # happens to end in this product's price is not the same number.
    spans = [m.start() for needle in needles
             for m in re.finditer(r"(?<![\d,])" + re.escape(needle) + r"(?!\d)", page)]
    if not spans:
        return page
    return "".join(page[max(0, p - radius):p + radius] for p in spans)


def parse_product_page(page, url):
    """-> item dict, or None if this page isn't a discounted NPR product."""
    ld = ld_product(page)
    offers = ld.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    now = money(str(offers.get("price") or offers.get("lowPrice") or "").replace(",", "")) \
        or money((meta_content(page, "product:price:amount", "og:price:amount", "price") or "").replace(",", ""))
    if not now:
        return None

    currency = (offers.get("priceCurrency")
                or meta_content(page, "product:price:currency", "og:price:currency") or "NPR").upper()
    if currency != "NPR":
        return None

    # Restrict the struck-price search to text near where the current price itself is
    # printed on the page. Without this, a "related products" / "recently viewed" rail
    # further down the same page contributes its own struck price, which then reads as
    # THIS product's original (e.g. khudra.com.np: a rail item's Rs 24,000 got picked up
    # as the original for a Rs 5,500 monitor). The real old-price markup for a product is
    # always right next to its own current price in the template.
    near = window_near(page, now)
    struck = [v for m in STRUCK.finditer(near) for v in npr_amounts(m.group(2))]
    struck += [v for m in OLD_CLASS.finditer(near) for v in npr_amounts(m.group(1))]
    # 20x ceiling: a struck number far above the price is a phone number or a spec, not
    # this product's old price.
    orig = next((s for s in struck if now < s < now * 20), None)
    pct = deal(orig, now)
    if pct is None:
        return None

    title = clean(ld.get("name")) or clean(meta_content(page, "og:title")) or ""
    if not title:
        return None
    cat = ld.get("category")
    if isinstance(cat, list):
        cat = cat[0] if cat else None
    return {
        "brand": None, "title": title, "url": url,
        "image": (ld.get("image")[0] if isinstance(ld.get("image"), list) and ld.get("image")
                  else ld.get("image")) or meta_content(page, "og:image"),
        "price": now, "original_price": orig, "discount_pct": pct,
        "currency": "NPR", "country": "NP",
        "category": clean(cat) if isinstance(cat, str) else None,
        "tags": [],
    }


def from_html(domain):
    urls = product_urls(domain)
    if not urls:
        return []

    def one(u):
        try:
            return parse_product_page(get_html(u), u)
        except Exception:
            return None

    with cf.ThreadPoolExecutor(HTML_WORKERS) as ex:
        items = [i for i in ex.map(one, urls) if i]

    # Some "stores" are JS apps that serve one identical prerendered page for every URL
    # (ekjor, evewomens, evanmens). Every product then parses as the same item and the
    # store looks like its whole catalogue is on sale. One title across many URLs is the
    # tell — drop the domain rather than publish the same product hundreds of times.
    if len(items) > 2 and len({i["title"] for i in items}) == 1:
        return []

    for i in items:
        i["brand"] = domain
    return items


EXTRACTORS = {"shopify": from_shopify, "woocommerce-store-api": from_woo}


def scrape(site):
    if site.get("tier") == "2":
        fn = from_html
    else:
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

    # real leaks: an "Accessories" tag/category alone must never hard-signal Fashion —
    # that's what AMBIGUOUS_ACCESSORY + hint is for, not a literal word in the regex.
    assert classify({"title": "Recci RCS-M01 Space Capsule Wireless Mouse – Bluetooth Wireless Mouse",
                      "category": "Wireless Mouse",
                      "tags": ["Gaming Mouse", "Mouse", "Wireless Mouse"]}, hint="Fashion") == "Electronics"
    assert classify({"title": "MIVI D4", "category": "AI-ENC Earbuds",
                      "tags": ["earbud", "earbuds", "audio accessories"]}, hint="Fashion") == "Electronics"
    # hand tools belong to none of the four verticals — drop, don't let a stray
    # "Accessories" tag file them under whatever the site's own (unreliable) hint is
    assert classify({"title": "Ingco Adjustable Wrench Industrial – HADW131068 (6″)",
                      "category": "Hand Tool Parts & Accessories",
                      "tags": ["Hand Tools", "Tools, DIY & Outdoor"]}, hint="Fitness") is None
    assert classify({"title": "Prolink 10KVA Rack/Tower Online UPS with LCD (PRO910-ERS)",
                      "category": "Prolink", "tags": ["Accessories", "UPS"]},
                     hint="Electronics") == "Electronics"
    # legitimate fashion must not get caught by the word-boundary fixes above
    assert classify({"title": "STOCK-European & American Retro Printed One-Piece Swimsuit for Women",
                      "category": "STOCK WOMEN", "tags": []}) == "Fashion"
    assert classify({"title": "Winter Thermal Warm Tank Tops Camis",
                      "category": None, "tags": []}) == "Fashion"

    assert bucket({"title": "Running Sneaker", "category": "STOCK MEN", "tags": []}, "Fashion") == "Footwear"
    assert bucket({"title": "Cotton Kurta", "category": "STOCK WOMEN", "tags": []}, "Fashion") == "Women"
    assert bucket({"title": "Plain Tee", "category": "STOCK MEN", "tags": []}, "Fashion") == "Men"
    assert bucket({"title": "Leather Tote Bag", "category": None, "tags": []}, "Fashion") == "Bags"
    # New buckets: Jewellery, Eyewear, Clothing
    assert bucket({"title": "Diamond Pendant – DPSP5780", "category": None, "tags": []}, "Fashion") == "Jewellery"
    assert bucket({"title": "Wedding Necklaces – DNK911", "category": None, "tags": []}, "Fashion") == "Jewellery"
    assert bucket({"title": "Limitless Noir Square Eyeglass", "category": None, "tags": []}, "Fashion") == "Eyewear"
    assert bucket({"title": "SETH DOUBLE BREASTED JACKET", "category": None, "tags": []}, "Fashion") == "Clothing"
    # Verify gendered items take precedence over item-type buckets
    assert bucket({"title": "Women Cotton Shirt", "category": "STOCK WOMEN", "tags": []}, "Fashion") == "Women"
    assert bucket({"title": "iPhone 13", "category": None, "tags": []}, "Electronics") == "Phones"
    assert bucket({"title": "Whey Protein", "category": None, "tags": []}, "Fitness") == "Supplements"
    assert bucket({"title": "SPF 50 Sunscreen", "category": None, "tags": []}, "Beauty") == "Skincare"
    # Beauty/Electronics improvements
    assert bucket({"title": "Dual-Head Eyeshadow Stick", "category": None, "tags": []}, "Beauty") == "Makeup"
    assert bucket({"title": "Keratin Hair Mask", "category": None, "tags": []}, "Beauty") == "Haircare"
    assert bucket({"title": "60x60 HD Binoculars", "category": None, "tags": []}, "Electronics") == "Cameras"
    assert bucket({"title": "ZL54CJ Sports Smartwatch", "category": None, "tags": []}, "Electronics") == "Accessories"

    # --- tier-2 HTML parsing. Fixtures are trimmed from the real store templates. ---
    def page(ld_price="29900", cur="NPR", body='<div class="price"><p><s>NPR 37,000</s></p><p>NPR 29,900</p></div>'):
        return ('<html><head><script type="application/ld+json">' + json.dumps({
            "@context": "https://schema.org", "@type": "Product", "name": "AirPods 4",
            "image": ["https://x/a.png"],
            "offers": {"@type": "Offer", "price": ld_price, "priceCurrency": cur},
        }) + "</script></head><body>" + body + "</body></html>")

    got = parse_product_page(page(), "https://evostore.com.np/AirPods4")
    assert got and got["price"] == 29900 and got["original_price"] == 37000
    assert got["discount_pct"] == 19 and got["title"] == "AirPods 4"
    # WooCommerce's own markup: <del> old, <ins> new
    woo = parse_product_page(page("1199", body="<del><bdi>Rs 2,699</bdi></del><ins><bdi>Rs 1,199</bdi></ins>"), "u")
    assert woo and woo["discount_pct"] == 55
    # class-named old price with no strike tag
    cls = parse_product_page(page("1500", body='<span class="price-old">Rs. 3,000</span>'), "u")
    assert cls and cls["original_price"] == 3000
    # no struck price anywhere -> not a deal, never inferred from a "SALE" badge
    assert parse_product_page(page(body='<div class="price">NPR 29,900</div><b>SALE!</b>'), "u") is None
    # foreign-currency store (caretobeauty.com prices in EUR) -> dropped at the gate
    assert parse_product_page(page("44.72", cur="EUR", body="<del>EUR 60.00</del>"), "u") is None
    # a struck number that isn't a price (phone number, spec) must not become the original
    assert parse_product_page(page(body="<s>9801234567</s><div>NPR 29,900</div>"), "u") is None
    # bare numbers with no currency marker are never prices
    assert npr_amounts("<del>37,000</del>") == [] and npr_amounts("Rs 37,000") == [37000]
    # struck price below the current price is not an original (relist/upsell rail)
    assert parse_product_page(page(body="<s>NPR 1,000</s><div>NPR 29,900</div>"), "u") is None
    # no structured price at all -> None, rather than guessing from page text
    assert parse_product_page("<html><body>Rs 2,000 <s>Rs 4,000</s></body></html>", "u") is None
    print("ok")


# ---- coverage.md ----------------------------------------------------------

def zero_reason(site, err, raw, npr_items, kept):
    """Why a domain contributed zero deals — the whole point of the coverage doc."""
    tier = site.get("tier")
    if tier == "dead":
        return "dead/unreachable"
    if tier == "3":
        return "JS-rendered or blocking (tier 3, extractor not built)"
    if err:
        return f"fetch error: {err}"
    if not raw and tier == "2":
        return "no sitemap, or no page carried both a structured price and a struck original"
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
    # Tier 2 is far slower than tier 1 (hundreds of page fetches per store vs. one feed),
    # so start those first — otherwise the whole run waits on the last one to begin.
    scrapeable = sorted((s for s in all_sites if s.get("tier") in ("1", "2")),
                        key=lambda s: s.get("tier") != "2")
    with cf.ThreadPoolExecutor(6) as ex:
        results = list(ex.map(scrape, scrapeable))

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
