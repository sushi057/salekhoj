#!/usr/bin/env python3
"""Refuse to publish a collapsed build.

Nepali hosting is slow and flaky: a site that times out contributes zero that day
(maayus.com went 718 deals -> "dead" between two runs). Unattended, that eventually
publishes a site with a third of its deals missing and no one notices. This compares a
fresh build against the last one we accepted and fails loudly instead.

Usage:
    gate.py <new-data.json> <last-good.json> [--force] [--update]

Exit 0 = safe to publish. Exit 1 = collapsed, or the file is not a usable build.
--update rewrites last-good.json from the new build (only after a pass).
"""
import json
import os
import sys

DEAL_FLOOR = 0.70     # fail under 70% of last-good deal count
DOMAIN_FLOOR = 0.80   # fail under 80% of last-good contributing domains


def stats(path):
    """Parse a built data.json and return the two numbers we gate on."""
    with open(path) as fh:
        data = json.load(fh)
    products = data.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("no products array — build produced nothing usable")
    if not isinstance(data.get("brands"), list):
        raise ValueError("no brands array — build is malformed")
    # Contributing domains, not the tracked-store count: a store with zero live deals
    # today is normal, a third of them going quiet at once is not.
    return {
        "deals": len(products),
        "domains": len({p["brand"] for p in products}),
        "generated_at": data.get("generated_at"),
    }


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    force = "--force" in argv
    update = "--update" in argv
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    new_path, good_path = args

    try:
        new = stats(new_path)
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as err:
        print(f"FAIL  {new_path}: {err}")
        return 1

    print(f"new build: {new['deals']} deals from {new['domains']} domains")

    # First ever run, or the baseline was lost: nothing to compare against.
    if not os.path.exists(good_path):
        print(f"no baseline at {good_path} — accepting this build as the first one")
        if update:
            write_baseline(good_path, new)
        return 0

    with open(good_path) as fh:
        good = json.load(fh)
    print(f"last good: {good['deals']} deals from {good['domains']} domains "
          f"({good.get('generated_at')})")

    deal_ratio = new["deals"] / max(good["deals"], 1)
    domain_ratio = new["domains"] / max(good["domains"], 1)
    print(f"ratio: deals {deal_ratio:.0%}, domains {domain_ratio:.0%}")

    failures = []
    if deal_ratio < DEAL_FLOOR:
        failures.append(f"deals fell to {deal_ratio:.0%} of last good "
                        f"(floor {DEAL_FLOOR:.0%})")
    if domain_ratio < DOMAIN_FLOOR:
        failures.append(f"contributing domains fell to {domain_ratio:.0%} of last good "
                        f"(floor {DOMAIN_FLOOR:.0%})")

    if failures and not force:
        for f in failures:
            print(f"FAIL  {f}")
        print("Refusing to publish. The live site keeps the previous data.")
        print("If this drop is real, re-run the workflow with force=true.")
        return 1
    if failures:
        for f in failures:
            print(f"WARN  {f} — overridden by --force")

    print("PASS  build accepted")
    if update:
        write_baseline(good_path, new)
    return 0


def write_baseline(path, new):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(new, fh, indent=2)
        fh.write("\n")
    print(f"wrote baseline {path}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
