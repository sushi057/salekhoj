#!/usr/bin/env bash
# Full refresh: re-probe every site, re-extract deals, drop the JSON next to the site.
set -euo pipefail
cd "$(dirname "$0")/scrapers"

python3 extract.py --check                              # logic self-check first
python3 fingerprint.py all_sites.txt > ../data/sites.json
python3 extract.py ../data/sites.json ../data/coverage.md > ../data/products.json
cp ../data/products.json ../site/data.json
echo "wrote site/data.json ($(wc -c < ../site/data.json) bytes)"
