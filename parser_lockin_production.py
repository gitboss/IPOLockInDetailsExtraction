"""
Lock-in Parser - Production Code Replicated
Exact replication from F:\python\ScripUnlockDetails\lockin_shp_comparision.py
"""

import re
from typing import List, Dict, Optional
from pathlib import Path


def extract_numbers_helper(line: str) -> List[int]:
    """Extract integer numbers from a line, preserving order."""
    out: List[int] = []
    for token in re.findall(r'\d[\d,]*', line):
        try:
            out.append(int(token.replace(",", "")))
        except ValueError:
            continue
    return out


def extract_table_rows(text: str) -> List[Dict]:
    """
    Extract lock-in table rows from text.

    Format:
    No. of Equity Shares | From | To | Lock in upto
    5390328              | 1    | 5390328 | 08-Oct-2026
    """
    rows = []

    # Find lines that look like data rows (start with digits)
    # Pattern: number, whitespace, number (from), whitespace, number (to), whitespace, date or "Free"

    lines = text.splitlines()

    for i, line in enumerate(lines):
        line = line.strip()

        # Remove spaces within numbers (e.g., "1 234567" → "1234567")
        # Uses lookahead to avoid consuming next digit, handles commas too
        # TEMPORARILY COMMENTED OUT TO DEBUG
        # line = re.sub(r'(\d)\s+(?=[\d,])', r'\1', line)

        # Skip empty lines and headers
        if not line or 'Distinctive' in line or 'Lock in' in line or 'Equity' in line:
            continue

        # Look for lines starting with digits (share count)
        # Pattern: digits followed by spaces/tabs, then more digits (from), then digits (to), then date/Free
        # Now accepts decimals: (\d[\d,.]*) to handle "303091.00"
        match = re.match(r'(\d[\d,.]*)\s+(\d[\d,.]*)\s+(\d[\d,.]*)\s+(.+)', line)

        if match:
            shares_str = match.group(1).replace(',', '')
            from_str = match.group(2).replace(',', '')
            to_str = match.group(3).replace(',', '')
            lockin_str = match.group(4).strip()

            # Check if this is a total row
            if 'Total' in lockin_str or 'total' in lockin_str.lower():
                continue

            try:
                shares = int(shares_str)
                from_num = int(from_str)
                to_num = int(to_str)

                # Parse lock-in date
                lockin_date = None
                is_free = False

                if 'Free' in lockin_str or 'free' in lockin_str.lower():
                    is_free = True
                else:
                    # Try to parse date (formats like "08-Oct-2026" or "07-Nov-2025")
                    date_match = re.search(r'(\d{1,2})-([A-Za-z]{3})-(\d{4})', lockin_str)
                    if date_match:
                        lockin_date = lockin_str

                rows.append({
                    'shares': shares,
                    'from': from_num,
                    'to': to_num,
                    'lockin_date': lockin_date,
                    'is_free': is_free,
                    'raw_lockin': lockin_str
                })

            except (ValueError, IndexError) as e:
                # Skip malformed rows
                continue

    return rows


def extract_total_from_text(text: str) -> Optional[int]:
    """
    Extract total shares from text.
    Look for pattern like "24070263  Total" or "Total  24070263"
    """
    # Look for "Total" line with a number
    for line in text.splitlines():
        if 'Total' in line or 'total' in line.lower():
            # Extract all numbers from this line
            numbers = re.findall(r'\d[\d,]*', line)
            if numbers:
                # Take the largest number (likely the total)
                candidates = [int(n.replace(',', '')) for n in numbers]
                return max(candidates)

    return None


def extract_annexure_ii_unlock_schedule(text: str) -> List[Dict]:
    """
    Extract Annexure II - unlock schedule table.
    Format: "Details of Equity Shares eligible to be traded"
    Columns: Date | No. of Shares
    """
    rows = []
    in_annexure_ii = False

    lines = text.splitlines()

    for i, line in enumerate(lines):
        # Normalize line for detection (collapse spaces)
        line_normalized = re.sub(r'\s+', ' ', line.strip()).lower()

        # Detect Annexure II section (flexible spacing)
        if 'annexure' in line_normalized and ('ii' in line_normalized or '2' in line_normalized):
            in_annexure_ii = True
            continue

        # Alternative detection: look for "eligible" or "traded" or "unlock"
        if any(keyword in line_normalized for keyword in ['eligible', 'traded', 'unlock', 'schedule']):
            in_annexure_ii = True
            continue

        # Stop at Annexure I (if we see it after II)
        if in_annexure_ii and 'annexure' in line_normalized and ('i' in line_normalized or '1' in line_normalized):
            # Only stop if it's clearly Annexure I, not II
            if 'ii' not in line_normalized and '2' not in line_normalized:
                break

        if not in_annexure_ii:
            continue

        # Look for date + share count pattern
        # Dates like "08-Oct-2026" or "07-Nov-2025"
        date_match = re.search(r'(\d{1,2}-[A-Za-z]{3}-\d{4})', line)
        if date_match:
            date_str = date_match.group(1)

            # Extract ALL numbers from the same line (shares)
            numbers = re.findall(r'\d[\d,]*', line)

            # Filter to get just the share count (usually the larger number)
            # Remove date components first
            date_numbers = set(re.findall(r'\d+', date_str))
            share_numbers = []

            for num_str in numbers:
                num_clean = num_str.replace(',', '')
                # Skip if this is part of the date
                if num_clean not in date_numbers:
                    try:
                        val = int(num_clean)
                        share_numbers.append(val)
                    except ValueError:
                        continue

            if share_numbers:
                rows.append({
                    'date': date_str,
                    'shares': max(share_numbers)  # Take the largest (most likely the share count)
                })

    return rows


def classify_lockin_bucket(lockin_date: str, is_free: bool, listing_date: Optional[str] = None) -> str:
    """
    Classify lock-in into buckets:
    - free
    - anchor_30 (30 days from listing)
    - anchor_90 (90 days from listing)
    - 1_year
    - 2_year
    - 3_year
    """
    if is_free:
        return 'free'

    if not lockin_date:
        return 'unknown'

    # If we have listing date, we can calculate anchor periods
    # For now, just classify by date patterns or year offsets

    # Parse the lock-in date
    try:
        # Format: "08-Oct-2026"
        date_match = re.match(r'(\d{1,2})-([A-Za-z]{3})-(\d{4})', lockin_date)
        if not date_match:
            return 'unknown'

        # For proper classification, we'd need the listing date
        # For now, just return the raw date categorization
        # This will be improved later with actual listing date logic

        return 'locked'  # Generic locked category for now

    except Exception:
        return 'unknown'


def parse_lockin_table(text: str, listing_date: Optional[str] = None) -> Dict:
    """
    Parse Annexure I lock-in table from text.

    Returns:
        Dict with:
        - rows: List of parsed table rows
        - declared_total: Total from "Total" row
        - computed_total: Sum of all share counts
        - total_match: Whether declared and computed totals match
    """
    # Extract table rows
    rows = extract_table_rows(text)

    # Extract declared total
    declared_total = extract_total_from_text(text)

    # Compute total from rows
    computed_total = sum(row['shares'] for row in rows) if rows else None

    # Check if totals match
    total_match = (
        declared_total is not None and
        computed_total is not None and
        declared_total == computed_total
    )

    # Classify each row into lock-in buckets
    for row in rows:
        row['row_class'] = classify_lockin_bucket(
            row.get('lockin_date'),
            row.get('is_free', False),
            listing_date
        )

    # Extract Annexure II (unlock schedule)
    annexure_ii_rows = extract_annexure_ii_unlock_schedule(text)

    # Calculate auto_unlocked percentage
    free_shares = sum(r['shares'] for r in rows if r.get('is_free'))
    auto_unlocked_pct = (free_shares / computed_total * 100) if computed_total and computed_total > 0 else 0

    return {
        'rows': rows,
        'declared_total': declared_total,
        'computed_total': computed_total,
        'total_match': total_match,
        'rows_count': len(rows),
        'free_count': sum(1 for r in rows if r.get('is_free')),
        'locked_count': sum(1 for r in rows if not r.get('is_free')),
        'free_shares': free_shares,
        'auto_unlocked_pct': round(auto_unlocked_pct, 2),
        'annexure_ii': annexure_ii_rows,
    }


def main():
    """Test lock-in parser with sample file"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parser_lockin_production.py <path_to_lockin_java.txt>")
        print("Example: python parser_lockin_production.py downloads/bse/pdf/lockin/txt/544324-CITICHEM-Annexure-I_java.txt")
        sys.exit(1)

    txt_path = Path(sys.argv[1])

    print(f"Parsing Lock-in: {txt_path}")
    print("=" * 70)

    # Read file
    with open(txt_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Parse
    result = parse_lockin_table(text)

    print(f"\nLock-in Data Extracted:")
    print(f"  Rows Found:      {result['rows_count']}")
    print(f"  Free Rows:       {result['free_count']}")
    print(f"  Locked Rows:     {result['locked_count']}")
    print(f"  Declared Total:  {result['declared_total']:,}" if result['declared_total'] else "  Declared Total:  None")
    print(f"  Computed Total:  {result['computed_total']:,}" if result['computed_total'] else "  Computed Total:  None")
    print(f"  Free Shares:     {result['free_shares']:,}")
    print(f"  Auto Unlocked:   {result['auto_unlocked_pct']:.1f}%")
    print(f"  Total Match:     {'YES' if result['total_match'] else 'NO'}")

    # Show first 5 rows
    print(f"\nFirst 5 rows:")
    for i, row in enumerate(result['rows'][:5]):
        status = "FREE" if row['is_free'] else "LOCKED"
        date_str = row.get('lockin_date', 'N/A')
        print(f"  {i+1}. {status:6} {row['shares']:>12,} shares | {date_str}")

    # Show Annexure II
    if result['annexure_ii']:
        print(f"\nAnnexure II Unlock Schedule ({len(result['annexure_ii'])} rows):")
        for row in result['annexure_ii'][:5]:
            print(f"  {row['date']}: {row['shares']:,} shares")


if __name__ == "__main__":
    main()
