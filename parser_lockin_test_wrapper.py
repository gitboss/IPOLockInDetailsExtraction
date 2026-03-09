#!/usr/bin/env python3
"""
Lock-in Parser Test Wrapper
Used by parser_tester.php to test parsing with full output stats
"""

import sys
from pathlib import Path
from parser_lockin import parse_lockin_file


def main():
    if len(sys.argv) < 2:
        print("Usage: python parser_lockin_test_wrapper.py <path_to_java.txt> [allotment_date]")
        sys.exit(1)

    txt_path = Path(sys.argv[1])
    allotment_date = None
    
    if len(sys.argv) >= 3:
        from datetime import datetime
        try:
            allotment_date = datetime.strptime(sys.argv[2], '%Y-%m-%d').date()
        except:
            pass

    try:
        result = parse_lockin_file(txt_path, allotment_date)

        # Calculate stats
        locked_rows = [r for r in result.rows if r.is_locked()]
        free_rows = [r for r in result.rows if not r.is_locked()]
        
        print(f"\nOK Extracted {len(result.rows)} rows")
        print(f"  Rows Found:      {len(result.rows)}")
        print(f"  Locked Rows:     {len(locked_rows)}")
        print(f"  Free Rows:       {len(free_rows)}")
        print(f"  Computed Total:  {result.computed_total:,}" if result.computed_total else "  Computed Total:  None")
        print(f"  Locked Total:    {result.locked_total:,}")
        print(f"  Free Total:      {result.free_total:,}")

        # Show ALL rows for tester
        print(f"\nAll {len(result.rows)} rows:")
        for i, row in enumerate(result.rows):
            status_icon = "LOCKED" if row.is_locked() else "FREE"
            dates_str = f"{row.lockin_date_from} -> {row.lockin_date_to}" if row.lockin_date_from and row.lockin_date_to else "-"
            print(f"  {i+1}. {status_icon} {row.shares:,} shares | {row.bucket.value} | {dates_str}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
