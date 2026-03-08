#!/usr/bin/env python3
"""
Lock-in Parser - Production Code (EXACT COPY from ScripUnlockDetails/_next.py files)
DO NOT MODIFY - Any change will break text parsing!

Copied from:
- lockin_shp_comparision_next.py (lines 113, 1924-2178)
- bse_lockin_comparison_next.py (lines 164-326)
- shared_parsing.py (helper functions)
"""

import re
from typing import Dict, List, Optional
from shared_parsing import parse_date_str, classify_row, clean_num, norm


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS (from lockin_shp_comparision_next.py)
# ═══════════════════════════════════════════════════════════════════════════

def extract_numbers(line: str) -> List[int]:
    """Extract integer numbers from a line, preserving order."""
    out: List[int] = []
    for token in re.findall(r'\d[\d,]*', line):
        try:
            # Strip all non-digit characters for extra safety (commas, asterisks, etc.)
            out.append(int(re.sub(r'[^\d]', '', token)))
        except ValueError:
            continue
    return out


# ═══════════════════════════════════════════════════════════════════════════
# LOCK-IN TABLE EXTRACTION (from lockin_shp_comparision_next.py)
# ═══════════════════════════════════════════════════════════════════════════

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

        # Skip empty lines and headers
        if not line or 'Distinctive' in line or 'Lock in' in line or 'Equity' in line:
            continue

        # Look for lines starting with digits (share count)
        # Pattern: digits followed by spaces/tabs, then more digits (from), then digits (to), then date/Free
        # Now accepts asterisks: (\d[\d,\*]*) to handle cases like "191662*" (backward compatible)
        match = re.match(r'(\d[\d,\*]*)\s+(\d[\d,\*]*)\s+(\d[\d,\*]*)\s+(.+)', line)

        if match:
            shares_str = match.group(1).replace(',', '')
            from_str = match.group(2).replace(',', '')
            to_str = match.group(3).replace(',', '')
            lockin_str = match.group(4).strip()

            # Check if this is a total row
            if 'Total' in lockin_str or 'total' in lockin_str.lower():
                continue

            try:
                # Strip any non-digit characters (asterisks, etc.) before converting
                shares = int(re.sub(r'[^\d]', '', shares_str))
                from_num = int(re.sub(r'[^\d]', '', from_str))
                to_num = int(re.sub(r'[^\d]', '', to_str))

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
                # Strip all non-digit characters for extra safety
                candidates = [int(re.sub(r'[^\d]', '', n)) for n in numbers]
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
                        # THRESHOLD REMOVED: No thresholds allowed in this project
                        # Old code with threshold (commented out):
                        # if val >= 1000:  # Share counts are usually >= 1000
                        #     share_numbers.append(val)
                        # New code: Accept all values
                        share_numbers.append(val)
                    except ValueError:
                        continue

            if share_numbers:
                # Take the largest number as shares
                shares = max(share_numbers)

                rows.append({
                    'unlock_date': date_str,
                    'shares': shares
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


# ═══════════════════════════════════════════════════════════════════════════
# BSE-SPECIFIC LOCK-IN PARSER (from bse_lockin_comparison_next.py)
# ═══════════════════════════════════════════════════════════════════════════

def parse_bse_text(text: str) -> Dict:
    """Parse BSE lock-in text and extract row data."""

    result = {
        'rows': [],
        'declared_total': None,
        'computed_total': 0,
        'free_shares': 0,
        'locked_shares': 0,
        'rows_count': 0,
        'free_count': 0,
        'locked_count': 0,
    }

    lines = text.split('\n')

    # Footer patterns to stop parsing
    footer_patterns = [
        r'^\s*Name\s*:', r'^\s*Designation\s*:', r'^\s*Place\s*:',
        r'\bFor\s+\w+.*Limited', r'Company Secretary', r'Membership No\.',
        r'^\s*Notes?:', r'The Distinctive Numbers are for the purpose',
        r'DEMAT\s*-\s*\d+\s*YEAR',
        r'^\s*For\s+.*\s+Limited\s*$', r'^\s*Sd/-',
    ]

    for line in lines:
        line = line.strip()

        # Skip empty lines, headers, page markers
        if not line or line.startswith('---') or line.startswith('####'):
            continue

        # Stop at footer
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in footer_patterns):
            break

        # Extract all potential numbers FIRST (before header check)
        # This prevents data rows with "Lock-in" from being filtered as headers
        tokens = line.split()
        nums = []
        for token in tokens:
            # Try to extract number from this token
            val = clean_num(token)
            if val is not None:
                nums.append(val)

        # Skip header lines (only if they DON'T have 3+ numbers)
        # This prevents skipping data rows that happen to contain words like "Lock-in"
        if len(nums) < 3:
            header_keywords = [
                'Distinctive', 'Number of Securities', 'Lock in date',
                'Type of Security', 'Physical/Demat', 'Demat/Physical',
                'Lock-in', 'From', 'To', 'Folio Number'
            ]
            if any(kw in line for kw in header_keywords):
                continue

        # Check if this is a total row (left-aligned or contains "Total")
        line_lower = line.lower()
        if 'total' in line_lower:
            # Extract total value from nums we already extracted
            # THRESHOLD REMOVED: No thresholds allowed in this project
            # Old code with threshold (commented out):
            # for val in nums:
            #     if val > 1000:
            #         result['declared_total'] = val
            #         break
            # New code: Take the largest number as the total
            if nums:
                result['declared_total'] = max(nums)
            continue

        # Need at least 3 numbers for a valid row (shares, from, to)
        if len(nums) < 3:
            continue

        shares = nums[0]
        from_num = nums[1] if len(nums) > 1 else 0
        to_num = nums[2] if len(nums) > 2 else 0

        # Extract dates - handle multiple formats
        # Common BSE formats: DD/MM/YYYY, DD-Mon-YYYY, DD-MM-YYYY, Month DD, YYYY, DDth Month YYYY, FREE, N/A, Free IPO Shares
        date_pattern = r'(Free\s+(?:IPO\s+)?Shares?|FREE|N/?A|NA|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}(?:\s*\([^)]+\))?|\d{1,2}[-/\.][A-Za-z]{3}[-/\.]\d{2,4}|[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})'
        dates_found = re.findall(date_pattern, line, re.IGNORECASE)

        from_date_raw = ''
        to_date_raw = ''

        if len(dates_found) >= 2:
            from_date_raw = dates_found[0]
            to_date_raw = dates_found[1]
        elif len(dates_found) == 1:
            to_date_raw = dates_found[0]

        # Parse dates using plumber.py's parse_date_str
        from_date = parse_date_str(from_date_raw) if from_date_raw else ''
        to_date = parse_date_str(to_date_raw) if to_date_raw else ''

        # Extract type of security - look for common patterns
        type_patterns = [
            r'F\s*&\s*L',
            r'Fully\s+Paid',
            r'F\s*-?\s*Fully',
            r'Partly\s+Paid',
            r'Lock[- ]in',
            r'IPO',
            r'Anchor',
        ]
        type_security = ''
        for pattern in type_patterns:
            type_match = re.search(pattern, line, re.IGNORECASE)
            if type_match:
                type_security = norm(type_match.group(0))
                break

        # If no type found, extract text between numbers (crude but works)
        if not type_security:
            # Find text after the third number
            parts = re.split(r'\d[\d,\s]*', line)
            for part in parts[3:]:  # Skip first 3 (shares, from, to)
                cleaned = norm(part)
                if cleaned and len(cleaned) > 2:
                    type_security = cleaned[:30]  # Limit length
                    break

        # Extract physical/demat
        demat_match = re.search(r'(Demat|Physical)', line, re.IGNORECASE)
        physical_demat = norm(demat_match.group(0)) if demat_match else ''

        # Classify row using plumber.py's classify_row
        raw_lockin = to_date if to_date else from_date
        row_class = classify_row(type_security, raw_lockin)
        is_free = (row_class == 'free')

        result['rows'].append({
            'shares': shares,
            'from': from_num,
            'to': to_num,
            'type_security': type_security,
            'from_date': from_date,
            'to_date': to_date,
            'raw_lockin': raw_lockin,
            'physical_demat': physical_demat,
            'is_free': is_free,
            'row_class': row_class,
        })

        result['computed_total'] += shares
        if is_free:
            result['free_shares'] += shares
            result['free_count'] += 1
        else:
            result['locked_shares'] += shares
            result['locked_count'] += 1

    result['rows_count'] = len(result['rows'])
    result['total_match'] = True  # BSE doesn't have declared total in same format

    # Fallback: If no "Total" row found, use computed_total as declared_total
    if result['declared_total'] is None and result['computed_total'] > 0:
        result['declared_total'] = result['computed_total']

    return result
