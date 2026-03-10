#!/usr/bin/env python3
"""Trace lock-in strategy cascade for GTIL"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Patch parse_bse_text to show cascade
import lockin_parser_production_unified as parser

# Store original strategy functions
orig_s1 = parser.parse_bse_strategy1_line_by_line
orig_s2 = parser.parse_bse_strategy2_reverse_from_total
orig_s3 = parser.parse_bse_strategy3_range_calculation
orig_s4 = parser.parse_bse_strategy4_no_malformed_cleanup

def trace_s1(text):
    print("  [CASCADE] Trying Strategy 1: line_by_line")
    result = orig_s1(text)
    print(f"  [CASCADE] Strategy 1 result: rows={result.get('rows_count', 0)}, total={result.get('computed_total', 0):,}")
    return result

def trace_s2(text, known_total=None):
    print(f"  [CASCADE] Trying Strategy 2: total_validation (known_total={known_total:,} if known_total else 'None')")
    result = orig_s2(text, known_total)
    if result:
        print(f"  [CASCADE] Strategy 2 result: rows={result.get('rows_count', 0)}, total={result.get('computed_total', 0):,}")
    else:
        print(f"  [CASCADE] Strategy 2 returned None")
    return result

def trace_s3(text, known_total=None):
    print(f"  [CASCADE] Trying Strategy 3: range_calculation (known_total={known_total:,} if known_total else 'None')")
    result = orig_s3(text, known_total)
    if result:
        print(f"  [CASCADE] Strategy 3 result: rows={result.get('rows_count', 0)}, total={result.get('computed_total', 0):,}")
    else:
        print(f"  [CASCADE] Strategy 3 returned None")
    return result

def trace_s4(text, known_total=None):
    print(f"  [CASCADE] Trying Strategy 4: no_malformed_cleanup (known_total={known_total:,} if known_total else 'None')")
    result = orig_s4(text, known_total)
    if result:
        print(f"  [CASCADE] Strategy 4 result: rows={result.get('rows_count', 0)}, total={result.get('computed_total', 0):,}")
    else:
        print(f"  [CASCADE] Strategy 4 returned None")
    return result

# Patch
parser.parse_bse_strategy1_line_by_line = trace_s1
parser.parse_bse_strategy2_reverse_from_total = trace_s2
parser.parse_bse_strategy3_range_calculation = trace_s3
parser.parse_bse_strategy4_no_malformed_cleanup = trace_s4

# Now test
gtil_file = Path(r'F:\python\IPOLockInDetailsExtraction\downloads\bse\pdf\lockin\txt\finalized\544675-GTIL-Annexure-I_java.txt')

if not gtil_file.exists():
    print(f"File not found: {gtil_file}")
    sys.exit(1)

print("=" * 100)
print("TRACING LOCK-IN STRATEGY CASCADE FOR GTIL")
print("=" * 100)

with open(gtil_file, 'r', encoding='utf-8') as f:
    text = f.read()

known_total = 13575360

print(f"\nCalling parse_bse_text(text, known_total={known_total:,})")
print("-" * 100)

result = parser.parse_bse_text(text, known_total)

print("-" * 100)
print(f"\nFINAL RESULT:")
print(f"  Strategy used: {result.get('strategy', 'unknown')}")
print(f"  Rows: {result.get('rows_count', 0)}")
print(f"  Computed total: {result.get('computed_total', 0):,}")
print(f"  Declared total: {result.get('declared_total', 'N/A')}")
print(f"  Match: {result.get('total_match', False)}")
print("=" * 100)
