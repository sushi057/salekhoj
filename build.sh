#!/usr/bin/env bash
# Full refresh: re-probe every site, re-extract deals, drop the JSON next to the site.
set -euo pipefail
cd "$(dirname "$0")/scrapers"

python3 extract.py --check                              # logic self-check first
python3 fingerprint.py all_sites.txt > ../data/sites.json
python3 extract.py ../data/sites.json ../data/coverage.md > ../data/products.json

# Allowlist keeps site/data.json to the fields app.js actually reads (verified via grep);
# data/products.json keeps every field for future extract.py classification.
python3 -c "
import json
FIELDS = ('brand', 'title', 'url', 'image', 'price', 'original_price',
          'discount_pct', 'currency', 'price_npr', 'vertical', 'bucket')
d = json.load(open('../data/products.json'))
d['products'] = [{k: p[k] for k in FIELDS} for p in d['products']]
json.dump(d, open('../site/data.json', 'w'))
"
echo "wrote site/data.json ($(wc -c < ../site/data.json) bytes)"
