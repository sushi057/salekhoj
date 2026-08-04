"""Append today's prices to the history archive.

The analysis is easy; the archive is not. Nobody can go back and collect
Nepali retail prices for a day that already passed, so this runs every build
and never rewrites what it already wrote.

One gzipped JSONL per day in data/history/. The product URL is the join key
that makes "this price dropped" and "median discount by month" answerable
later — if it ever changes, the archive splits in two and half of it stops
matching. Don't change it.

Usage: python3 archive.py ../data/products.json ../data/history
"""
import json, gzip, sys, os, datetime

FIELDS = ("url", "brand", "price", "original_price", "discount_pct",
          "vertical", "bucket", "currency")


def rows(products, day):
    for p in products:
        r = {k: p.get(k) for k in FIELDS}
        r["day"] = day
        yield r


def write(products, outdir, day=None):
    """Write one day's snapshot. Returns (path, count, wrote) — wrote is False
    if the day is already archived, since a rebuild must not double-count."""
    day = day or datetime.date.today().isoformat()
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{day}.jsonl.gz")
    if os.path.exists(path):
        return path, 0, False
    # Write to a temp file and rename, so an interrupted build can't leave a
    # half-written day that then looks complete to the next run.
    tmp = path + ".tmp"
    n = 0
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in rows(products, day):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    os.replace(tmp, path)
    return path, n, True


def demo():
    import tempfile
    p = [{"url": "https://x.np/a", "brand": "x.np", "price": 399,
          "original_price": 2799, "discount_pct": 85, "vertical": "Fashion",
          "bucket": "Women", "currency": "NPR", "title": "dropped field"}]
    with tempfile.TemporaryDirectory() as d:
        path, n, wrote = write(p, d, "2026-08-04")
        assert wrote and n == 1, (wrote, n)
        r = json.loads(gzip.open(path, "rt").read().strip())
        assert r["url"] == "https://x.np/a" and r["day"] == "2026-08-04", r
        assert r["discount_pct"] == 85 and "title" not in r, r
        # a second run on the same day must not append or overwrite
        _, n2, wrote2 = write(p, d, "2026-08-04")
        assert not wrote2 and n2 == 0, (wrote2, n2)
        assert len(gzip.open(path, "rt").read().strip().split("\n")) == 1
    print("ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        demo()
    else:
        src, outdir = sys.argv[1], sys.argv[2]
        products = json.load(open(src))["products"]
        path, n, wrote = write(products, outdir)
        print(f"archived {n} rows -> {path}" if wrote
              else f"{path} already exists, left alone")
