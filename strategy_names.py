#!/usr/bin/env python3
"""
Strategy Names and Sequence - Direct from Code
"""

print("=" * 80)
print("LOCK-IN PARSER STRATEGIES (BSE)")
print("=" * 80)
print("""
Sequence in parse_bse_text() - lockin_parser_production_unified.py:

1. parse_bse_strategy2_reverse_from_total()
   → Strategy name: 'reverse_from_total' or 'total_validation'
   → Works backwards from TOTAL line
   → Uses known_total from database

2. parse_bse_strategy1_line_by_line()
   → Strategy name: 'line_by_line'
   → Original BSE parser, line-by-line extraction
   → Has malformed number cleanup (can break some formats)

3. parse_bse_strategy4_no_malformed_cleanup()  [NEW 2026-03-09]
   → Strategy name: 'no_malformed_cleanup'
   → Same as Strategy 1 but WITHOUT malformed cleanup
   → Better for formats like Goel Construction, Astonea

4. parse_bse_strategy3_range_calculation()  [NEW 2026-03-09]
   → Strategy name: 'range_calculation'
   → For 2-number format (From, To only - no shares column)
   → Calculates shares as: to - from + 1
   → Example: GBLOGISTIC format

Fallback: General parser (parse_lockin_table)
""")

print("\n" + "=" * 80)
print("SHP PARSER STRATEGIES")
print("=" * 80)
print("""
Sequence in extract_shp_values_from_text_java() - shp_parser_production_unified.py:

1. extract_using_spatial_columns()
   → Strategy name: 'spatial_columns'
   → Detects columns from whitespace gaps
   → Uses pattern matching for Promoter/Public/Other keywords

2. extract_using_fixed_positions()
   → Strategy name: 'fixed_positions'
   → Uses fixed character position ranges
   → Tries multiple column layouts

3. extract_shp_using_position_from_total()
   → Strategy name: 'position_based'
   → Finds Total row, works backwards by position
   → Uses hints from lock-in data

4. extract_shp_values_from_text()  (Sequential)
   → Strategy name: 'sequential'
   → Pattern-based fallback
   → Always returns (even if partial)

5. extract_shp_using_boundary_detection()  [Uses dual-hint]
   → Strategy name: 'boundary_detection'
   → Scans UP from Total until boundary
   → Uses both DB total and computed total hints

6. extract_shp_with_column_count_validation()
   → Strategy name: 'column_count_validation'
   → Filters by column count, validates by math

7. extract_shp_using_simple_position()
   → Strategy name: 'simple_position'
   → Pure position-based (final fallback)
   → Requires hints
""")

print("\n" + "=" * 80)
print("CURRENT USAGE (from database)")
print("=" * 80)

import db
import json
from collections import Counter

sql = """
    SELECT validation_results
    FROM ipo_processing_log
    WHERE validation_results IS NOT NULL
"""

results = db.execute_query(sql, fetch="all")

lockin = Counter()
shp = Counter()
total = 0

for rec in results:
    vr = json.loads(rec['validation_results'])
    strategies = vr.get('_strategies', {})
    if strategies.get('lockin_strategy'):
        lockin[strategies['lockin_strategy']] += 1
    if strategies.get('shp_strategy'):
        shp[strategies['shp_strategy']] += 1
    total += 1

print(f"\nTotal records: {total}\n")

print("Lock-in strategies used:")
for name, count in lockin.most_common():
    print(f"  {count:4d} × {name}")

print(f"\nSHP strategies used:")
for name, count in shp.most_common():
    print(f"  {count:4d} × {name}")

print("\n" + "=" * 80)
