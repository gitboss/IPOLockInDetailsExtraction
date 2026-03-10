#!/usr/bin/env python3
"""Strategy usage statistics"""

import db
import json
from collections import Counter

sql = """
    SELECT unique_symbol, validation_results, processed_at
    FROM ipo_processing_log
    WHERE validation_results IS NOT NULL
    ORDER BY processed_at DESC
"""

results = db.execute_query(sql, fetch="all")

lockin_strategies = Counter()
shp_strategies = Counter()
total = 0

print("=" * 80)
print("STRATEGY USAGE STATISTICS")
print("=" * 80)

for rec in results:
    if rec['validation_results']:
        vr = json.loads(rec['validation_results'])
        strategies = vr.get('_strategies', {})
        
        if strategies.get('lockin_strategy'):
            lockin_strategies[strategies['lockin_strategy']] += 1
        if strategies.get('shp_strategy'):
            shp_strategies[strategies['shp_strategy']] += 1
        
        total += 1

print(f"\nTotal Records Analyzed: {total}\n")

print("LOCK-IN PARSER STRATEGIES:")
print("-" * 50)
for strategy, count in lockin_strategies.most_common():
    pct = (count / total * 100) if total > 0 else 0
    print(f"  {strategy:30s} {count:5d} ({pct:5.1f}%)")

print(f"\nSHP PARSER STRATEGIES:")
print("-" * 50)
for strategy, count in shp_strategies.most_common():
    pct = (count / total * 100) if total > 0 else 0
    print(f"  {strategy:30s} {count:5d} ({pct:5.1f}%)")

print("\n" + "=" * 80)
