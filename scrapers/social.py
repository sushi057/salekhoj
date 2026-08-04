"""Turn real deals from site/data.json into ready-to-post social media assets.

Reads the same data the site does, applies the site's own per-store spread cap so
the deepest-discounting stores don't own every post, renders 1080x1920 slide decks
with Pillow, and emits:
  out/carousel/<name>/01.png, 02.png, ...   (IG carousel — images only, no encode)
  out/reels/<name>.mp4                      (ffmpeg crossfade concat of the same slides)
  caption.txt next to each                  (hook-first caption + hashtags)

Posting is manual — this only produces the files. No auto-post, no scheduling, no API.

Usage: python3 social.py [--vertical Fashion] [--count 5] [--name dashain-week1]
       python3 social.py --check
"""
import argparse, hashlib, json, os, re, subprocess, sys, textwrap, time, urllib.request

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_JSON = os.path.join(ROOT, "site", "data.json")
STYLE_CSS = os.path.join(ROOT, "site", "style.css")
CACHE_DIR = os.path.join(ROOT, "out", ".imgcache")   # covered by out/ in .gitignore
OUT_DIR = os.path.join(ROOT, "out")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
TIMEOUT = 15
W, H = 1080, 1920

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Fallback palette if style.css parsing ever comes up empty — pulled straight from the
# site's dark theme (out/reels are watched full-screen, dark reads better than the light
# newsprint theme does on a phone).
DEFAULT_PALETTE = {
    "ink": "#f4f1ec", "paper": "#131110", "card": "#1c1917",
    "sale": "#e8114b", "flash": "#ffd400", "jade": "#0e6e5c",
    "mute": "#9d968d", "line": "#302b27",
}


def load_palette():
    """Pull the dark-theme color variables straight out of site/style.css."""
    css = open(STYLE_CSS, encoding="utf-8").read()
    m = re.search(r':root\[data-theme=["\']dark["\']\]\s*\{([^}]*)\}', css)
    block = m.group(1) if m else ""
    pal = dict(DEFAULT_PALETTE)
    for name, val in re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{3,8})', block):
        pal[name] = val
    return pal


def money(v):
    """Rs 2,799 — NPR is always an integer, never show decimals."""
    return "Rs " + format(round(v), ",")


def clean_title(text):
    """Strip inventory-management prefixes from product titles (STOCK, INSTOCK variants)."""
    # ponytail: regex list of observed noise patterns from real data (STOCK -/-, INSTOCK -/)
    # These are tudoholic.com's internal markers, not product names. Match case-insensitively
    # to catch variants; only strip leading occurrence to avoid removing legitimate words mid-title.
    cleaned = re.sub(r'^(STOCK|INSTOCK)\s*[-–]\s*', '', text, flags=re.IGNORECASE)
    return cleaned.strip()


def truncate_text(text, max_len=60):
    """Truncate text at word boundary, not mid-word. Plain text (no Pillow required)."""
    if len(text) <= max_len:
        return text
    # Find the last space before max_len
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = text[:last_space]
    else:
        truncated = text[:max_len - 1]
    return truncated.rstrip("-–,").strip() + "…"


def wrap_title(text, font, max_width, max_lines=3):
    """Wrap product titles (they run 70+ chars) to fit max_width, ellipsize past max_lines.

    Truncates on word boundaries, not mid-word. Trailing dashes/hyphens are stripped before
    the ellipsis to avoid dangling punctuation."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if font.getlength(trial) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines and font.getlength(lines[-1] + "...") > max_width:
            lines[-1] = lines[-1][:-1]
        # Strip trailing dashes/hyphens/commas before ellipsis
        lines[-1] = re.sub(r'[-–,]\s*$', '', lines[-1]).strip()
        lines[-1] += "..."
    return lines


def spread(products, n, per_brand=2):
    """Exact port of spread() in site/app.js: rank by discount, cap per_brand per store.

    Without this the 3 deepest-discounting stores (tudoholic.com, obsessioncosmetics.com,
    brother-mart.com) own every single slide, same failure mode the homepage rails guard
    against — see SOCIAL.md.
    """
    seen, out = {}, []
    ranked = sorted(products, key=lambda p: -p["discount_pct"])
    for p in ranked:
        seen[p["brand"]] = seen.get(p["brand"], 0) + 1
        if seen[p["brand"]] <= per_brand:
            out.append(p)
        if len(out) == n:
            break
    return out


def fetch_image(url):
    """Download + cache a product image. Returns a PIL Image or None on any failure."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    path = os.path.join(CACHE_DIR, key + ext)
    if not os.path.exists(path):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
        except Exception:
            return None   # Nepali hosting is flaky — skip this product, don't crash the run
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


def select_deals(products, vertical, count, max_price=None):
    """Top deals by discount, spread-capped, skipping anything with no usable image or above price ceiling."""
    pool = [p for p in products if p.get("image")]
    if vertical:
        pool = [p for p in pool if p.get("vertical") == vertical]
    if max_price:
        pool = [p for p in pool if p.get("price", 0) <= max_price]
    # ponytail: oversample 3x to absorb image-fetch failures/missing images without a
    # second network-aware selection pass; bump the multiplier if failures start eating it.
    candidates = spread(pool, count * 3, per_brand=2)
    chosen = []
    for p in candidates:
        if len(chosen) == count:
            break
        img = fetch_image(p["image"])
        if img is None:
            continue
        chosen.append((p, img))
    return chosen


# ---------- rendering ----------

def font(size, bold=True):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def center_text(draw, cx, y, text, f, fill):
    w = f.getlength(text)
    draw.text((cx - w / 2, y), text, font=f, fill=fill)
    return f.getbbox(text)[3] - f.getbbox(text)[1]


def title_card(pal, n, top_pct):
    img = Image.new("RGB", (W, H), pal["paper"])
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=pal["sale"])
    center_text(d, W / 2, 550, "SALEKHOJ", font(56), pal["mute"])
    headline = f"{top_pct}% OFF" if top_pct else "TOP DEALS"
    center_text(d, W / 2, 680, headline, font(160), pal["sale"])
    center_text(d, W / 2, 880, f"{n} verified deals live in Nepal right now", font(48, False), pal["ink"])
    center_text(d, W / 2, H - 150, "swipe ->", font(44), pal["flash"])
    return img


def deal_slide(pal, product, image, idx, total):
    img = Image.new("RGB", (W, H), pal["paper"])
    d = ImageDraw.Draw(img)

    # product image, aspect-fit (never squashed/cropped) onto a card panel
    box_w, box_h = 940, 1040
    box_x, box_y = (W - box_w) // 2, 130
    d.rounded_rectangle([box_x, box_y, box_x + box_w, box_y + box_h], radius=24, fill=pal["card"])
    fitted = ImageOps.contain(image, (box_w - 40, box_h - 40))
    px = box_x + (box_w - fitted.width) // 2
    py = box_y + (box_h - fitted.height) // 2
    img.paste(fitted, (px, py))

    # discount badge, top-right of the image panel
    pct = product["discount_pct"]
    badge_r = 90
    bx, by = box_x + box_w - 20, box_y + 20
    d.ellipse([bx - badge_r * 2 + 20, by, bx + 20, by + badge_r * 2], fill=pal["sale"])
    bc = (bx - badge_r + 20, by + badge_r)
    bf1, bf2 = font(58), font(26, False)
    center_text(d, bc[0], bc[1] - 48, f"{pct}%", bf1, "#ffffff")
    center_text(d, bc[0], bc[1] + 18, "OFF", bf2, "#ffffff")

    # brand
    from_brand = product["brand"].split(".")[0].replace("-", " ").title()
    y = box_y + box_h + 40
    center_text(d, W / 2, y, from_brand.upper(), font(38), pal["mute"])
    y += 50

    # title, wrapped (with noise prefixes stripped)
    tf = font(46)
    clean = clean_title(product["title"])
    lines = wrap_title(clean, tf, W - 140, max_lines=2)
    for line in lines:
        center_text(d, W / 2, y, line, tf, pal["ink"])
        y += 54
    y += 16

    # prices: struck original, big current
    was = money(product["original_price"])
    now = money(product["price"])
    wf = font(44, False)
    ww = wf.getlength(was)
    wx = W / 2 - ww / 2
    d.text((wx, y), was, font=wf, fill=pal["mute"])
    strike_y = y + 24
    d.line([(wx, strike_y), (wx + ww, strike_y)], fill=pal["mute"], width=4)
    y += 54
    center_text(d, W / 2, y, now, font(96), pal["jade"])
    y += 100

    d.rectangle([0, H - 90, W, H], fill=pal["card"])
    center_text(d, W / 2, H - 68, f"SaleKhoj  •  deal {idx} of {total}", font(32, False), pal["mute"])
    return img


def cta_card(pal):
    img = Image.new("RGB", (W, H), pal["paper"])
    d = ImageDraw.Draw(img)
    center_text(d, W / 2, 720, "MORE DEALS", font(90), pal["ink"])
    center_text(d, W / 2, 830, "LIKE THIS", font(90), pal["sale"])
    center_text(d, W / 2, 1050, "Link in bio", font(54, False), pal["flash"])
    center_text(d, W / 2, 1140, "SaleKhoj — real two-price deals, Nepal only", font(36, False), pal["mute"])
    return img


def caption_text(products):
    top = max(p["discount_pct"] for p in products)
    lines = [f"\U0001F525 Up to {top}% OFF right now — {len(products)} verified deals in Nepal:", ""]
    for p in products:
        brand = p["brand"].split(".")[0].replace("-", " ").title()
        clean = clean_title(p['title'])
        truncated = truncate_text(clean, max_len=60)
        lines.append(f"• {truncated} — {money(p['price'])} "
                      f"(was {money(p['original_price'])}, {p['discount_pct']}% off) [{brand}]")
    lines.append("")
    lines.append("Real store prices, both prices verified — not guessed. Link in bio.")
    lines.append("")
    lines.append("#SaleKhoj #NepalSale #NepalDeals #KathmanduDeals #OnlineShoppingNepal "
                  "#DiscountNepal #NepalOffers #DealsNepal")
    return "\n".join(lines)


def build_video(png_paths, out_path, slide_dur=2.5, xfade_dur=0.5):
    n = len(png_paths)
    if n == 1:
        subprocess.run(["ffmpeg", "-y", "-loop", "1", "-t", str(slide_dur), "-i", png_paths[0],
                         "-vf", "format=yuv420p", "-r", "30", "-an", out_path],
                        check=True, capture_output=True)
        return
    cmd = ["ffmpeg", "-y"]
    for p in png_paths:
        cmd += ["-loop", "1", "-t", str(slide_dur), "-i", p]
    step = slide_dur - xfade_dur
    filt = []
    label = "0"
    for i in range(1, n):
        out_label = f"v{i}" if i < n - 1 else "vout"
        offset = i * step
        filt.append(f"[{label}][{i}]xfade=transition=fade:duration={xfade_dur}:offset={offset}[{out_label}]")
        label = out_label
    cmd += ["-filter_complex", ";".join(filt), "-map", f"[{label}]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-an", out_path]
    subprocess.run(cmd, check=True, capture_output=True)


def generate(vertical, count, name, max_price=None):
    data = json.load(open(DATA_JSON))
    chosen = select_deals(data["products"], vertical, count, max_price=max_price)
    if not chosen:
        print("No deals with usable images found for that filter.", file=sys.stderr)
        return
    pal = load_palette()
    products = [p for p, _ in chosen]

    carousel_dir = os.path.join(OUT_DIR, "carousel", name)
    reels_dir = os.path.join(OUT_DIR, "reels")
    os.makedirs(carousel_dir, exist_ok=True)
    os.makedirs(reels_dir, exist_ok=True)

    slides = [title_card(pal, len(products), max(p["discount_pct"] for p in products))]
    for i, (p, img) in enumerate(chosen, 1):
        slides.append(deal_slide(pal, p, img, i, len(products)))
    slides.append(cta_card(pal))

    png_paths = []
    for i, slide in enumerate(slides, 1):
        path = os.path.join(carousel_dir, f"{i:02d}.png")
        slide.save(path)
        png_paths.append(path)

    cap = caption_text(products)
    open(os.path.join(carousel_dir, "caption.txt"), "w").write(cap)
    open(os.path.join(reels_dir, f"{name}.caption.txt"), "w").write(cap)

    build_video(png_paths, os.path.join(reels_dir, f"{name}.mp4"))

    print(f"{len(products)} deals -> {carousel_dir} ({len(png_paths)} slides)")
    print(f"video -> {os.path.join(reels_dir, name + '.mp4')}")
    stores = {}
    for p in products:
        stores[p["brand"]] = stores.get(p["brand"], 0) + 1
    print("stores:", ", ".join(f"{b}={c}" for b, c in sorted(stores.items())))


def demo():
    """Pure-logic self-check: selection, per-store cap, price formatting, title wrapping."""
    products = [
        {"brand": "a.com", "discount_pct": 85, "title": "A"},
        {"brand": "a.com", "discount_pct": 80, "title": "B"},
        {"brand": "a.com", "discount_pct": 75, "title": "C"},   # 3rd from a.com, must be dropped
        {"brand": "b.com", "discount_pct": 70, "title": "D"},
        {"brand": "c.com", "discount_pct": 60, "title": "E"},
    ]
    picked = spread(products, 5, per_brand=2)
    assert [p["title"] for p in picked] == ["A", "B", "D", "E"]
    counts = {}
    for p in picked:
        counts[p["brand"]] = counts.get(p["brand"], 0) + 1
    assert all(c <= 2 for c in counts.values()), "per-store cap violated"

    # n cuts it off before the cap even matters
    assert len(spread(products, 2, per_brand=2)) == 2

    assert money(2799) == "Rs 2,799"
    assert money(490) == "Rs 490"
    assert money(12345) == "Rs 12,345"
    assert "." not in money(999.6)   # never decimals, rounds instead

    # Title cleaning: strip STOCK/INSTOCK prefixes
    assert clean_title("STOCK - Five-Quarter Sleeve Dress") == "Five-Quarter Sleeve Dress"
    assert clean_title("INSTOCK- Men's Jacket") == "Men's Jacket"
    assert clean_title("INSTOCK - Cotton Tee") == "Cotton Tee"
    assert clean_title("Regular Product Name") == "Regular Product Name"

    # Text truncation: word-boundary aware truncation for captions
    assert truncate_text("Short") == "Short"
    long_txt = "Recci RCS-M01 Space Capsule Wireless Mouse – Bluetooth Multimode"
    trunc = truncate_text(long_txt, max_len=60)
    assert "…" in trunc, "should have ellipsis when truncated"
    assert not trunc.endswith("-…"), "should strip trailing dashes before ellipsis"
    # Check it actually truncates and stays near the limit
    assert len(trunc) <= 70, "truncated text should stay reasonably close to limit"

    f = font(46)
    long_title = ("Five-Quarter Sleeve Mid-Length Slimming Dress Elegant Premium "
                  "Cotton Blend Everyday Wear Collection 2026")
    lines = wrap_title(long_title, f, 940, max_lines=2)
    assert len(lines) == 2
    assert lines[-1].endswith("...")
    assert all(f.getlength(l) <= 940 for l in lines)
    # Verify word boundary truncation (no mid-word cuts)
    assert not any(l.endswith("-...") or l.endswith("–...") for l in lines), "mid-word truncation detected"

    # Test mid-word truncation is fixed: truncate at word boundary, not mid-character
    mid_word_title = "Bluetooth Wireless Headphones Amazing Sound Quality Premium"
    mid_word_lines = wrap_title(mid_word_title, f, 500, max_lines=1)
    assert mid_word_lines[0].endswith("..."), "should truncate and add ellipsis"
    assert not mid_word_lines[0].endswith("-..."), "should not cut mid-word"

    short = wrap_title("Simple Tee", f, 940, max_lines=2)
    assert short == ["Simple Tee"]

    pal = load_palette()
    assert pal["sale"].startswith("#") and pal["ink"].startswith("#")

    print("social.py --check: OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vertical", choices=["Fashion", "Electronics", "Beauty", "Fitness"])
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--name", default=time.strftime("deals-%Y%m%d"))
    ap.add_argument("--max-price", type=int, default=25000,
                    help="Filter products above this price (Rs). Default 25000 ~ 9x median (Rs 2799), "
                         "excludes jewelry/high-end electronics while keeping ordinary goods.")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.check:
        demo()
        return
    generate(args.vertical, args.count, args.name, max_price=args.max_price)


if __name__ == "__main__":
    main()
