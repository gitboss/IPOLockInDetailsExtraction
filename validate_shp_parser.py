#!/usr/bin/env python3
"""
Validate SHP Parser on all _java.txt files in specified folders.

Usage:
    python validate_shp_parser.py
"""

import os
import sys
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, r"F:\python\ScripUnlockDetails")

from shp_parser_unified import parse_shp_text, validate_shp_result, find_total_line, extract_numbers


def get_total_from_text(text: str) -> int:
    """Extract total shares from text for use as hint."""
    total_line = find_total_line(text)
    if total_line:
        nums = extract_numbers(total_line)
        if nums:
            # The total is usually the largest number
            return max(nums)
    return None


def validate_folder(folder_path: str, exchange: str):
    """Validate all _java.txt files in a folder."""
    folder = Path(folder_path)
    
    if not folder.exists():
        print(f"  [SKIP] Folder not found: {folder}")
        return 0, 0, 0
    
    files = list(folder.glob("*_java.txt"))
    
    if not files:
        print(f"  [SKIP] No _java.txt files found in {folder}")
        return 0, 0, 0
    
    print(f"  Found {len(files)} files")
    
    success = 0
    failed = 0
    no_data = 0
    
    for f in files:
        try:
            text = f.read_text(encoding='utf-8', errors='ignore')
            
            if not text.strip():
                print(f"    [EMPTY] {f.name}")
                no_data += 1
                continue
            
            # First, get the total from SHP text to use as hint
            annexure_total = get_total_from_text(text)
            
            # Parse with the hint
            result = parse_shp_text(text, annexure_total=annexure_total)
            
            # Check if we got valid data
            has_promoter = result.get('promoter_shares') is not None and result.get('promoter_shares', 0) > 0
            has_public = result.get('public_shares') is not None and result.get('public_shares', 0) > 0
            has_total = result.get('total_shares') is not None and result.get('total_shares', 0) > 0
            
            if has_promoter and has_public and has_total:
                # Validate the result
                is_valid, reasons = validate_shp_result(result)
                
                # Check if math adds up
                p = result.get('promoter_shares', 0)
                u = result.get('public_shares', 0)
                o = result.get('other_shares', 0)
                t = result.get('total_shares', 0)
                
                math_ok = (p + u + o) == t
                
                if is_valid and math_ok:
                    print(f"    [OK] {f.name}: P={p:,}, U={u:,}, O={o:,}, T={t:,} (strategy: {result['strategy_used']})")
                    success += 1
                else:
                    # Still count as success if we got the data
                    print(f"    [PARTIAL] {f.name}: P={p:,}, U={u:,}, T={t:,}, math_ok={math_ok}, valid={is_valid}, reasons={reasons}")
                    success += 1
            else:
                print(f"    [NO DATA] {f.name}: promoter={has_promoter}, public={has_public}, total={has_total}")
                no_data += 1
                
        except Exception as e:
            print(f"    [ERROR] {f.name}: {str(e)[:50]}")
            failed += 1
    
    return success, failed, no_data


def main():
    print("=" * 60)
    print("SHP Parser Validation Script")
    print("=" * 60)
    
    # NSE folder
    nse_folder = r"F:\python\IPOLockInDetailsExtraction\downloads\nse\pdf\shp\txt"
    # BSE folder (check both possible paths)
    bse_folder = r"F:\python\IPOLockInDetailsExtraction\downloads\bse\pdf\shp\txt"
    
    print(f"\n[1] NSE SHP Files")
    print("-" * 40)
    nse_ok, nse_err, nse_empty = validate_folder(nse_folder, "NSE")
    
    print(f"\n[2] BSE SHP Files")
    print("-" * 40)
    bse_ok, bse_err, bse_empty = validate_folder(bse_folder, "BSE")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_ok = nse_ok + bse_ok
    total_err = nse_err + bse_err
    total_empty = nse_empty + bse_empty
    total_files = total_ok + total_err + total_empty
    
    print(f"Total files processed: {total_files}")
    print(f"  Success: {total_ok}")
    print(f"  Errors:  {total_err}")
    print(f"  Empty:   {total_empty}")
    
    if total_files > 0:
        success_rate = (total_ok / total_files) * 100
        print(f"\nSuccess rate: {success_rate:.1f}%")


if __name__ == "__main__":
    main()
