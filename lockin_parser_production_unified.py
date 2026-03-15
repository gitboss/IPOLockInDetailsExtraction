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
from shared_parsing import parse_date_str, classify_row, clean_num, norm, extract_dates_from_line


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

    # Hotfix: remove known NSE circular toll-free token that can be misread as row data.
    text = text.replace("1800 266 0058", " ")

    # Find lines that look like data rows (start with digits)
    # Pattern: number, whitespace, number (from), whitespace, number (to), whitespace, date or "Free"

    lines = text.splitlines()

    for i, line in enumerate(lines):
        line = line.strip()

        # Skip empty lines and headers
        if not line or 'Distinctive' in line or 'Lock in' in line or 'Equity' in line:
            continue

        # Look for lines starting with digits (share count)
        # Pattern: digits followed by spaces/tabs, then more digits (from), then digits (to), then optional date/Free
        # Now accepts asterisks and decimals: (\d[\d,.\*]*) to handle "191662*" and "303091.00"
        # 4th field is optional - if missing, treated as free shares
        match = re.match(r'(\d[\d,.\*]*)\s+(\d[\d,.\*]*)\s+(\d[\d,.\*]*)\s*(.*)', line)

        if match:
            shares_str = match.group(1).replace(',', '')
            from_str = match.group(2).replace(',', '')
            to_str = match.group(3).replace(',', '')
            lockin_str = match.group(4).strip() if match.group(4) else ''

            # Check if this is a total row
            if lockin_str and ('Total' in lockin_str or 'total' in lockin_str.lower()):
                continue

            try:
                # Strip any non-digit characters (asterisks, etc.) before converting
                shares = int(re.sub(r'[^\d]', '', shares_str))
                from_num = int(re.sub(r'[^\d]', '', from_str))
                to_num = int(re.sub(r'[^\d]', '', to_str))

                # Parse lock-in date
                lockin_date = None
                is_free = False

                # If no date field or contains "Free", treat as free shares
                if not lockin_str or 'Free' in lockin_str or 'free' in lockin_str.lower():
                    is_free = True
                else:
                    # Try to parse date - multiple formats:
                    # Text month: "19-Dec-26", "08-Oct-2026"
                    # Numeric month: "17-03-2026", "16-01-2026"
                    date_match = re.search(r'(\d{1,2})-([A-Za-z]{3})-(\d{2,4})', lockin_str)
                    if not date_match:
                        # Try numeric month format with common separators (backward-compatible extension)
                        date_match = re.search(r'\d{1,2}[-/\.]\d{1,2}[-/\.]\d{4}', lockin_str)
                    if date_match:
                        # Keep only the date token (not surrounding type/form text)
                        lockin_date = date_match.group(0)

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
    - free (no lock_to date)
    - anchor_30 (0-45 days)
    - anchor_90 (45-105 days)
    - 1_year_minus (105-365 days)
    - 1_year_plus (365-730 days)
    - 2_year_plus (730-1095 days)
    - 3_year_plus (1095+ days)
    """
    if is_free:
        return 'free'

    if not lockin_date:
        return 'free'

    # Parse the lock-in date and classify
    try:
        # Format: "08-Oct-2026" or "08/10/2026" or "08.10.2026"
        date_match = re.match(r'(\d{1,2})[-/\.]([A-Za-z]{3})[-/\.](\d{4})', lockin_date)
        if not date_match:
            # Try numeric month format
            date_match = re.match(r'(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{4})', lockin_date)
        
        if not date_match:
            return 'free'

        # For now, return generic locked - proper bucket needs allotment/listing date
        return 'locked'

    except Exception:
        return 'free'


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

def parse_bse_strategy2_reverse_from_total(text: str, known_total: Optional[int] = None) -> Optional[Dict]:
    """
    Strategy 2: Total Validation (Reverse from Bottom)

    Two modes:
    1. WITH known_total (from DB): Math-based validation - most robust
    2. WITHOUT known_total: Find TOTAL line in text, validate against it

    Algorithm:
    - Start from BOTTOM (or TOTAL line), go UP collecting rows
    - Keep running sum of shares
    - Stop when running_sum == target_total
    - Validate distinctive number math: shares == (to - from + 1)
    - Double confirmation: last row's to_num == target_total

    NO HARD-CODED FOOTER KEYWORDS - uses math only

    Args:
        text: Raw BSE lock-in text
        known_total: Known total from database (optional)

    Returns:
        Parsed result dict, or None if strategy fails
    """
    lines = text.split('\n')
    rows = []
    running_sum = 0
    target_total = known_total
    # Minimal header keywords - avoid words that appear in footers
    header_keywords = ['Number of Securities', 'Type of Security']

    # ALWAYS find TOTAL line in text (even if known_total provided)
    # This tells us where to START parsing from (avoid footer junk)
    start_idx = None
    found_total = None
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx].strip()
        if not line or line.startswith('---') or line.startswith('####'):
            continue

        # Look for standalone large number (TOTAL)
        nums = extract_numbers(line)
        if len(nums) == 1 and nums[0] > 1000000:
            found_total = nums[0]
            start_idx = idx - 1
            break

        # Or line with "total" keyword
        if 'total' in line.lower():
            nums = extract_numbers(line)
            if nums:
                found_total = max(nums)
                start_idx = idx - 1
                break

    if start_idx is None:
        return None  # No TOTAL found

    # Use known_total if provided, otherwise use found_total
    if not target_total:
        target_total = found_total

    # Go UP from start position
    for idx in range(start_idx, -1, -1):
        line = lines[idx].strip()

        # Skip empties and markers
        if not line or line.startswith('---') or line.startswith('####'):
            continue

        # Remove spaces within malformed numbers (same as Strategy 1)
        # Pattern 0: "4 47  " → "447  " (exactly 1 space + 1-2 digits + 2+ spaces/end) - ICODEX case
        # Pattern 1: "9 7,84,937" → "97,84,937" (exactly 1 space before digits+comma)
        # Pattern 2: "3 ,03,091" → "3,03,091" (exactly 1 space before comma)
        # Pattern 3: "1 9.00" → "19.00" (exactly 1 space before digits+decimal)
        # Pattern 4: "7 .00" → "7.00" (exactly 1 space before decimal)
        line = re.sub(r'(\d) (\d{1,2})(?=\s{2,}|$)', r'\1\2', line)  # digit + 1 space + 1-2 digits + 2+ spaces/end
        line = re.sub(r'(\d) (\d{1,2},)', r'\1\2', line)   # digit + 1 space + 1-2 digits + comma
        line = re.sub(r'(\d) (,)', r'\1\2', line)           # digit + 1 space + comma
        line = re.sub(r'(\d) (\d{1,2}\.)', r'\1\2', line)  # digit + 1 space + 1-2 digits + decimal
        line = re.sub(r'(\d) (\.)', r'\1\2', line)          # digit + 1 space + decimal

        # Extract numbers
        nums = extract_numbers(line)

        # Stop at headers (only if line has < 3 numbers, otherwise it's a data row)
        if len(nums) < 3 and any(kw in line for kw in header_keywords):
            break

        # Stop at company name / title lines
        if 'Limited' in line and len(nums) == 0:
            break

        # Need at least 3 numbers for a valid row (shares, from, to)
        if len(nums) < 3:
            continue

        # Extract shares, from, to
        shares = nums[0]
        from_num = nums[1]
        to_num = nums[2]

        # Validate distinctive number math
        if from_num > 0 and to_num > 0:
            expected_shares = to_num - from_num + 1
            if shares != expected_shares:
                # Malformed row - skip it
                continue

        # Check if adding this row would exceed target total
        new_sum = running_sum + shares

        if new_sum > target_total:
            break  # Stop - we've collected all data rows

        # Extract dates using shared function (same as Strategy 1)
        date_info = extract_dates_from_line(line)
        from_date = date_info['from_date']
        to_date = date_info['to_date']

        # Use to_date as primary lockin_date (same as Strategy 1)
        raw_lockin = to_date if to_date else from_date
        row_class = classify_row('', raw_lockin)
        is_free = (row_class == 'free')

        rows.append({
            'shares': shares,
            'from': from_num,
            'to': to_num,
            'from_date': from_date,
            'to_date': to_date,
            'is_free': is_free,
            'raw_lockin': raw_lockin,
            'row_class': row_class,
        })

        running_sum = new_sum

        # Stop if we've reached exact total
        if running_sum == target_total:
            if to_num == target_total:  # Double confirmation
                break

    # Reverse to get top-to-bottom order
    rows.reverse()

    if not rows:
        return None

    # Validate: computed total should match target
    computed_total = sum(r['shares'] for r in rows)
    if computed_total != target_total:
        return None  # Mismatch

    return {
        'rows': rows,
        'declared_total': target_total,
        'computed_total': computed_total,
        'total_match': True,
        'rows_count': len(rows),
        'free_count': sum(1 for r in rows if r.get('is_free')),
        'locked_count': sum(1 for r in rows if not r.get('is_free')),
        'free_shares': sum(r['shares'] for r in rows if r.get('is_free')),
        'locked_shares': sum(r['shares'] for r in rows if not r.get('is_free')),
        'strategy': 'total_validation' if known_total else 'reverse_from_total',
    }


# ============================================================================
# [RANGE-CALC 2026-03-09] Strategy 3: Distinctive Number Range Calculation
# ============================================================================
# Purpose: Handle format where only From/To are given (no shares column)
# Format:  From | To | Type | Date
#          1    | 1640000 | F&L | 29/01/2028
# Shares calculated as: to - from + 1
# Rollback: Remove this entire strategy block and its call in parse_bse_text()
# ============================================================================

def parse_bse_strategy3_range_calculation(text: str, known_total: Optional[int] = None) -> Optional[Dict]:
    """
    [RANGE-CALC 2026-03-09] Strategy 3: Calculate shares from distinctive number range
    
    Handles format where shares column is missing:
    - Only 2 numbers per line (From, To) - dates extracted separately
    - Shares calculated as: to - from + 1
    
    [RANGE-CALC 2026-03-09] Same date extraction as Strategy 1
    
    Args:
        text: Raw BSE lock-in text
        known_total: Known total from database (optional, for validation)
    
    Returns:
        Parsed result dict, or None if strategy fails
        
    [RANGE-CALC 2026-03-09] Rollback: Safe to remove entire function
    """
    lines = text.split('\n')
    rows = []
    header_keywords = ['Distinctive', 'Number of Securities', 'Type of Security', 'From', 'To']
    
    # Footer patterns to stop parsing
    footer_patterns = [
        r'^\s*Name\s*:', r'^\s*Designation\s*:', r'^\s*Place\s*:',
        r'\bFor\s+\w+.*Limited', r'Company Secretary', r'Membership No\.',
        r'^\s*Notes?:', r'The Distinctive Numbers are for the purpose',
        r'DEMAT\s*-\s*\d+\s*YEAR', r'^\s*For\s+.*\s+Limited\s*$', r'^\s*Sd/-',
    ]
    
    for line in lines:
        line = line.strip()
        
        # Skip empty lines and markers
        if not line or line.startswith('---') or line.startswith('####'):
            continue
        
        # Stop at footer
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in footer_patterns):
            break
        
        # [RANGE-CALC 2026-03-09] Same number extraction as Strategy 1
        # Extract numbers using split() and clean_num() (same as Strategy 1)
        # Filter out date-like numbers during token extraction
        tokens = line.split()
        nums = []
        for token in tokens:
            val = clean_num(token)
            if val is not None:
                # [RANGE-CALC 2026-03-09] Filter out date-like numbers
                # Dates like 29/01/2028 become 29012028 (8 digits) - skip these
                # Dates like 01/01/2025 become 1012025 (7 digits) - skip these
                # Valid share counts are typically 5-7 digits but NOT date patterns
                token_clean = token.replace('/', '').replace('-', '').replace('.', '')
                if len(token_clean) >= 7 and any(sep in token for sep in ['/', '-', '.']):
                    continue  # Skip date-like tokens
                nums.append(val)
        
        # [RANGE-CALC 2026-03-09] Look for lines with exactly 2 numbers (From, To)
        # Skip lines with 3+ numbers (handled by other strategies)
        if len(nums) != 2:
            # Also skip header lines
            if len(nums) < 2 and any(kw in line for kw in header_keywords):
                continue
            continue
        
        from_num = nums[0]
        to_num = nums[1]
        
        # Validate: from should be less than to
        if from_num >= to_num:
            continue
        
        # [RANGE-CALC 2026-03-09] Calculate shares from range
        shares = to_num - from_num + 1
        
        # [RANGE-CALC 2026-03-09] Same date extraction as Strategy 1
        date_pattern = r'(Free\s+(?:IPO\s+)?Shares?|FREE|N/?A|NA|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}(?:\s*\([^)]+\))?|\d{1,2}[-/\.][A-Za-z]{3}[-/\.]\d{2,4}|[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})'
        dates_found = re.findall(date_pattern, line, re.IGNORECASE)
        
        lockin_date = None
        from_date_raw = ''
        to_date_raw = ''
        
        if len(dates_found) >= 2:
            from_date_raw = dates_found[0]
            to_date_raw = dates_found[1]
            lockin_date = to_date_raw  # Use to_date as lockin_date
        elif len(dates_found) == 1:
            to_date_raw = dates_found[0]
            lockin_date = to_date_raw
        
        # Check for "Free" keywords
        if not lockin_date or 'free' in line.lower() or 'n/a' in line.lower():
            is_free = True
        else:
            is_free = False
        
        # Extract type of security
        type_patterns = [
            r'F\s*&\s*L', r'Fully\s+Paid', r'F\s*-?\s*Fully',
            r'Partly\s+Paid', r'Lock[- ]in', r'IPO', r'Anchor',
        ]
        type_security = ''
        for pattern in type_patterns:
            type_match = re.search(pattern, line, re.IGNORECASE)
            if type_match:
                type_security = norm(type_match.group(0))
                break
        
        # Classify row
        raw_lockin = lockin_date if lockin_date else ''
        row_class = classify_row(type_security, raw_lockin)
        is_free = (row_class == 'free')
        
        rows.append({
            'shares': shares,
            'from': from_num,
            'to': to_num,
            'type_security': type_security,
            'lockin_date': lockin_date,
            'from_date': from_date_raw if from_date_raw else None,
            'to_date': to_date_raw if to_date_raw else None,
            'is_free': is_free,
            'raw_lockin': raw_lockin,
            'row_class': row_class,
        })
    
    if not rows:
        return None  # [RANGE-CALC 2026-03-09] No rows found
    
    # Compute total from rows
    computed_total = sum(r['shares'] for r in rows)
    
    # [RANGE-CALC 2026-03-09] Validate against known_total if provided
    if known_total and computed_total != known_total:
        # Allow small tolerance for rounding
        if abs(computed_total - known_total) > 100:
            return None  # Mismatch too large
    
    # Find declared total from "Total" line
    declared_total = None
    for line in lines:
        if 'total' in line.lower():
            nums = extract_numbers(line)
            if nums:
                declared_total = max(nums)
                break
    
    return {
        'rows': rows,
        'declared_total': declared_total,
        'computed_total': computed_total,
        'total_match': (declared_total is None or computed_total == declared_total),
        'rows_count': len(rows),
        'free_count': sum(1 for r in rows if r.get('is_free')),
        'locked_count': sum(1 for r in rows if not r.get('is_free')),
        'free_shares': sum(r['shares'] for r in rows if r.get('is_free')),
        'locked_shares': sum(r['shares'] for r in rows if not r.get('is_free')),
        'strategy': 'range_calculation',  # [RANGE-CALC 2026-03-09]
    }


# ============================================================================
# [ASTONEA-FIX 2026-03-09] Strategy 4: 3-Number Format (No Malformed Cleanup)
# ============================================================================
# Purpose: Handle files with 3 numbers (shares, from, to) but WITHOUT aggressive
#          malformed number cleanup that merges adjacent columns.
# Use case: Astonea-like formats where columns are close together
# Format:   Shares From To Type FromDate ToDate Demat
#           21,30,000 1 21,30,000 L 23.05.2025 03.06.2028 Demat
# Rollback: Remove this entire strategy block and its call in parse_bse_text()
# ============================================================================

def parse_bse_strategy4_no_malformed_cleanup(text: str, known_total: Optional[int] = None) -> Optional[Dict]:
    """
    [ASTONEA-FIX 2026-03-09] Strategy 4: 3-number format without malformed cleanup
    
    Same as Strategy 1 but WITHOUT the aggressive malformed number cleanup regexes
    that merge adjacent columns (e.g., "1 21,30,000" → "121,30,000").
    
    Args:
        text: Raw BSE lock-in text
        known_total: Known total from database (optional, for validation)
    
    Returns:
        Parsed result dict, or None if strategy fails
        
    [ASTONEA-FIX 2026-03-09] Rollback: Safe to remove entire function
    """
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
    
    # Footer patterns (same as Strategy 1)
    footer_patterns = [
        r'^\s*Name\s*:', r'^\s*Designation\s*:', r'^\s*Place\s*:',
        r'\bFor\s+\w+.*Limited', r'Company Secretary', r'Membership No\.',
        r'^\s*Notes?:', r'The Distinctive Numbers are for the purpose',
        r'DEMAT\s*-\s*\d+\s*YEAR',
        r'^\s*For\s+.*\s+Limited\s*$', r'^\s*Sd/-',
    ]
    
    header_keywords = [
        'Distinctive', 'Number of Securities', 'Lock in date',
        'Type of Security', 'Physical/Demat', 'Demat/Physical',
        'Lock-in', 'From', 'To', 'Folio Number'
    ]
    
    for line in lines:
        line = line.strip()
        
        # Skip empty lines and markers
        if not line or line.startswith('---') or line.startswith('####'):
            continue
        
        # Stop at footer
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in footer_patterns):
            break
        
        # [ASTONEA-FIX 2026-03-09] NO malformed number cleanup!
        # Strategy 1 has: line = re.sub(r'(\d) (\d{1,2},)', r'\1\2', line)
        # We skip this - it merges adjacent columns like "1 21,30,000" → "121,30,000"
        
        # Extract numbers using split() and clean_num()
        tokens = line.split()
        nums = []
        for token in tokens:
            val = clean_num(token)
            if val is not None:
                nums.append(val)
        
        # Skip header lines (only if they DON'T have 3+ numbers)
        if len(nums) < 3:
            if any(kw in line for kw in header_keywords):
                continue
            continue
        
        # Check if this is a total row
        line_lower = line.lower()
        if 'total' in line_lower:
            if nums:
                result['declared_total'] = max(nums)
            continue
        
        # Need at least 3 numbers for a valid row (shares, from, to)
        if len(nums) < 3:
            continue
        
        shares = nums[0]
        from_num = nums[1]
        to_num = nums[2]
        
        # Validate distinctive number math
        if from_num > 0 and to_num > 0:
            expected_shares = to_num - from_num + 1
            if shares != expected_shares:
                # Skip malformed rows
                continue
        
        # [ASTONEA-FIX 2026-03-09] Same date extraction as Strategy 1
        # Supports DD.MM.YYYY, DD/MM/YYYY, DD-Mon-YYYY, etc.
        date_pattern = r'(Free\s+(?:IPO\s+)?Shares?|FREE|N/?A|NA|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}(?:\s*\([^)]+\))?|\d{1,2}[-/\.][A-Za-z]{3}[-/\.]\d{2,4}|[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})'
        dates_found = re.findall(date_pattern, line, re.IGNORECASE)
        
        from_date_raw = ''
        to_date_raw = ''
        
        if len(dates_found) >= 2:
            from_date_raw = dates_found[0]
            to_date_raw = dates_found[1]
        elif len(dates_found) == 1:
            to_date_raw = dates_found[0]
        
        # Parse dates using shared_parsing.py's parse_date_str
        from_date = parse_date_str(from_date_raw) if from_date_raw else ''
        to_date = parse_date_str(to_date_raw) if to_date_raw else ''
        
        # Extract type of security
        type_patterns = [
            r'F\s*&\s*L', r'Fully\s+Paid', r'F\s*-?\s*Fully',
            r'Partly\s+Paid', r'Lock[- ]in', r'IPO', r'Anchor',
        ]
        type_security = ''
        for pattern in type_patterns:
            type_match = re.search(pattern, line, re.IGNORECASE)
            if type_match:
                type_security = norm(type_match.group(0))
                break
        
        # If no type found, extract text between numbers
        if not type_security:
            parts = re.split(r'\d[\d,\s]*', line)
            for part in parts[3:]:
                cleaned = norm(part)
                if cleaned and len(cleaned) > 2:
                    type_security = cleaned[:30]
                    break
        
        # Extract physical/demat
        demat_match = re.search(r'(Demat|Physical)', line, re.IGNORECASE)
        physical_demat = norm(demat_match.group(0)) if demat_match else ''
        
        # Classify row
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
    result['total_match'] = True
    
    # Fallback: If no "Total" row found, use computed_total as declared_total
    if result['declared_total'] is None and result['computed_total'] > 0:
        result['declared_total'] = result['computed_total']
    
    # [ASTONEA-FIX 2026-03-09] Validate against known_total if provided
    if known_total and result['computed_total'] > 0:
        if abs(result['computed_total'] - known_total) > 100:
            return None  # Mismatch too large
    
    result['strategy'] = 'no_malformed_cleanup'  # [ASTONEA-FIX 2026-03-09]
    return result


def parse_bse_strategy1_line_by_line(text: str) -> Dict:
    """
    Strategy 1: Line-by-line parsing (original BSE parser)

    Processes each line sequentially extracting numbers and dates.
    Works for well-formatted tables with clear column boundaries.
    """
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

        # Remove spaces within malformed numbers (BSE files have spaces in unexpected places)
        # CRITICAL: Only match EXACTLY 1 space within SAME number, NOT column boundaries
        # Pattern 1: "9 7,84,937" → "97,84,937" (exactly 1 space before digits+comma)
        # Pattern 2: "3 ,03,091" → "3,03,091" (exactly 1 space before comma)
        # Pattern 3: "1 9.00" → "19.00" (exactly 1 space before digits+decimal)
        # Pattern 4: "7 .00" → "7.00" (exactly 1 space before decimal)
        # Pattern 5: "4 47  " → "447  " ONLY if preceded by comma OR at line start (ICODEX case)
        line = re.sub(r'(\d) (\d{1,2},)', r'\1\2', line)   # digit + 1 space + 1-2 digits + comma
        line = re.sub(r'(\d) (,)', r'\1\2', line)           # digit + 1 space + comma
        line = re.sub(r'(\d) (\d{1,2}\.)', r'\1\2', line)  # digit + 1 space + 1-2 digits + decimal
        line = re.sub(r'(\d) (\.)', r'\1\2', line)          # digit + 1 space + decimal
        # Pattern 5: Only merge "digit space digit" if preceded by comma (within number) OR at start of non-whitespace (first number)
        # This prevents merging "27,15,072 1" but allows "4 47" or ",0 7"
        line = re.sub(r'(,\d{1,2}) (\d{1,2})(?=\s{2,}|$)', r'\1\2', line)  # After comma: ",07 2  " → ",072  "
        line = re.sub(r'(^\s*\d{1}) (\d{1,2})(?=\s{2,}|$)', r'\1\2', line)  # Line start single digit: "4 47  " → "447  "

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

        # Validate distinctive number math (reject malformed rows like addresses)
        if from_num > 0 and to_num > 0:
            expected_shares = to_num - from_num + 1
            if shares != expected_shares:
                # Skip malformed rows (e.g., address lines parsed as data)
                continue

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

    result['strategy'] = 'line_by_line'
    return result


def parse_bse_strategy5_sum_first_soft_labels(
    text: str,
    known_total: Optional[int] = None,
    declared_total_hint: Optional[int] = None,
    computed_total_hint: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 5: Sum-first matching with soft distinctive-range validation (FINAL FALLBACK).

    Rules:
    1) Keep rows based on shares/date/lock-in signals; do NOT hard-drop on range mismatch.
    2) Treat distinctive from/to as labels + quality signal (`range_valid`) only.
    3) If any total hints are provided, require exact share-sum match to one hint.
    """
    lines = text.split('\n')
    candidates: List[Dict] = []
    page_numbers: set[int] = set()

    footer_patterns = [
        r'^\s*Name\s*:', r'^\s*Designation\s*:', r'^\s*Place\s*:',
        r'\bFor\s+\w+.*Limited', r'Company Secretary', r'Membership No\.',
        r'^\s*Notes?:', r'The Distinctive Numbers are for the purpose',
        r'DEMAT\s*-\s*\d+\s*YEAR', r'^\s*For\s+.*\s+Limited\s*$', r'^\s*Sd/-',
    ]
    header_keywords = [
        'Distinctive', 'Number of Securities', 'Lock in date',
        'Type of Security', 'Physical/Demat', 'Demat/Physical',
        'Lock-in', 'From', 'To', 'Folio Number'
    ]
    type_patterns = [
        r'F\s*&\s*L', r'Fully\s+Paid', r'F\s*-?\s*Fully',
        r'Partly\s+Paid', r'Lock[- ]in', r'IPO', r'Anchor',
    ]

    declared_total_from_text: Optional[int] = None

    for raw_line in lines:
        line = raw_line.strip()

        if not line or line.startswith('---') or line.startswith('####'):
            continue

        if any(re.search(pattern, line, re.IGNORECASE) for pattern in footer_patterns):
            break

        tokens = line.split()
        nums: List[int] = []
        for token in tokens:
            val = clean_num(token)
            if val is not None:
                nums.append(val)
                page_numbers.add(val)

        if 'total' in line.lower():
            if nums:
                declared_total_from_text = max(nums)
            continue

        if len(nums) < 3:
            if any(kw in line for kw in header_keywords):
                continue
            continue

        shares = nums[0]
        from_num = nums[1]
        to_num = nums[2]
        if shares <= 0:
            continue

        date_info = extract_dates_from_line(line)
        from_date = date_info.get('from_date', '')
        to_date = date_info.get('to_date', '')
        raw_lockin = to_date if to_date else from_date
        has_lockin_signal = bool(raw_lockin) or bool(re.search(r'(Demat|Physical)', line, re.IGNORECASE)) or ('free' in line.lower()) or ('n/a' in line.lower())
        if not has_lockin_signal:
            continue

        type_security = ''
        for pattern in type_patterns:
            type_match = re.search(pattern, line, re.IGNORECASE)
            if type_match:
                type_security = norm(type_match.group(0))
                break

        if not type_security:
            parts = re.split(r'\d[\d,\s]*', line)
            for part in parts[3:]:
                cleaned = norm(part)
                if cleaned and len(cleaned) > 2:
                    type_security = cleaned[:30]
                    break

        demat_match = re.search(r'(Demat|Physical)', line, re.IGNORECASE)
        physical_demat = norm(demat_match.group(0)) if demat_match else ''

        row_class = classify_row(type_security, raw_lockin)
        is_free = (row_class == 'free')

        range_expected = None
        range_valid = None
        range_diff = None
        if from_num > 0 and to_num > 0:
            range_expected = to_num - from_num + 1
            range_diff = shares - range_expected
            range_valid = (range_diff == 0)

        candidates.append({
            'shares': shares,
            'from': from_num,
            'to': to_num,
            'type_security': type_security,
            'from_date': from_date,
            'to_date': to_date,
            'lockin_date': to_date if to_date else from_date,
            'raw_lockin': raw_lockin,
            'physical_demat': physical_demat,
            'is_free': is_free,
            'row_class': row_class,
            'range_expected': range_expected,
            'range_valid': range_valid,
            'range_diff': range_diff,
        })

    if not candidates:
        return None

    # Only enforce external hints if they are actually present on the lock-in page.
    hint_totals: List[int] = []
    for hint in [known_total, declared_total_hint, computed_total_hint]:
        if hint and hint > 0 and hint in page_numbers and hint not in hint_totals:
            hint_totals.append(hint)
    if declared_total_from_text and declared_total_from_text > 0 and declared_total_from_text not in hint_totals:
        hint_totals.append(declared_total_from_text)

    selected_rows: Optional[List[Dict]] = None
    matched_target: Optional[int] = None

    all_rows_total = sum(r['shares'] for r in candidates)
    for target in hint_totals:
        if all_rows_total == target:
            selected_rows = candidates
            matched_target = target
            break

    if selected_rows is None:
        for target in hint_totals:
            running_sum = 0
            temp_rows: List[Dict] = []
            for row in reversed(candidates):
                row_shares = row['shares']
                if running_sum + row_shares > target:
                    continue
                temp_rows.append(row)
                running_sum += row_shares
                if running_sum == target:
                    selected_rows = list(reversed(temp_rows))
                    matched_target = target
                    break
            if selected_rows is not None:
                break

    if selected_rows is None:
        for target in hint_totals:
            found = False
            for i in range(len(candidates)):
                running_sum = 0
                for j in range(i, len(candidates)):
                    running_sum += candidates[j]['shares']
                    if running_sum == target:
                        selected_rows = candidates[i:j + 1]
                        matched_target = target
                        found = True
                        break
                    if running_sum > target:
                        break
                if found:
                    break
            if found:
                break

    if hint_totals and selected_rows is None:
        return None

    if selected_rows is None:
        selected_rows = candidates

    computed_total = sum(r['shares'] for r in selected_rows)
    declared_total = declared_total_from_text or declared_total_hint or known_total
    if declared_total is None:
        declared_total = computed_total

    return {
        'rows': selected_rows,
        'declared_total': declared_total,
        'computed_total': computed_total,
        'total_match': (matched_target is not None) if hint_totals else (declared_total == computed_total),
        'rows_count': len(selected_rows),
        'free_count': sum(1 for r in selected_rows if r.get('is_free')),
        'locked_count': sum(1 for r in selected_rows if not r.get('is_free')),
        'free_shares': sum(r['shares'] for r in selected_rows if r.get('is_free')),
        'locked_shares': sum(r['shares'] for r in selected_rows if not r.get('is_free')),
        'target_hint_used': matched_target,
        'candidate_rows_count': len(candidates),
        'range_mismatch_count': sum(1 for r in selected_rows if r.get('range_valid') is False),
        'strategy': 'sum_first_soft_labels',
    }


def parse_bse_strategy6_two_dates(
    text: str,
    known_total: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 6: Two-date row parser (FINAL BSE fallback).

    Purpose:
    - Handle rows that explicitly contain BOTH lock-in from and lock-in upto dates.
    - Keep free rows (FREE/IPO Shares) in the same pass.
    - Prefer text TOTAL consistency over DB hint if DB hint is stale.
    """
    lines = text.split('\n')
    rows = []

    footer_patterns = [
        r'^\s*Name\s*:', r'^\s*Designation\s*:', r'^\s*Place\s*:',
        r'\bFor\s+\w+.*Limited', r'Company Secretary', r'Membership No\.',
        r'^\s*Notes?:', r'The Distinctive Numbers are for the purpose',
        r'DEMAT\s*-\s*\d+\s*YEAR', r'^\s*For\s+.*\s+Limited\s*$', r'^\s*Sd/-',
    ]
    header_keywords = [
        'Distinctive', 'Number of Securities', 'Lock in date',
        'Type of Security', 'Physical/Demat', 'Demat/Physical',
        'Lock-in', 'From', 'To', 'Folio Number'
    ]

    declared_total_from_text = None
    saw_two_date_locked_row = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith('---') or line.startswith('####'):
            continue
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in footer_patterns):
            break

        tokens = line.split()
        nums: List[int] = []
        for token in tokens:
            val = clean_num(token)
            if val is not None:
                nums.append(val)

        if 'total' in line.lower():
            if nums:
                declared_total_from_text = max(nums)
            continue

        if len(nums) < 3:
            if any(kw in line for kw in header_keywords):
                continue
            continue

        shares = nums[0]
        from_num = nums[1]
        to_num = nums[2]
        if shares <= 0:
            continue

        # Distinctive math sanity check (same as other BSE strategies).
        if from_num > 0 and to_num > 0:
            expected_shares = to_num - from_num + 1
            if shares != expected_shares:
                continue

        date_info = extract_dates_from_line(line)
        from_date = date_info['from_date']
        to_date = date_info['to_date']
        raw_lockin = to_date if to_date else from_date

        # Track if this strategy is actually handling two-date locked rows.
        if from_date and to_date and to_date != 'FREE':
            saw_two_date_locked_row = True

        # Extract light metadata when present (same spirit as Strategy 1).
        type_patterns = [
            r'F\s*&\s*L', r'Fully\s+Paid', r'F\s*-?\s*Fully',
            r'Partly\s+Paid', r'Lock[- ]in', r'IPO', r'Anchor',
        ]
        type_security = ''
        for pattern in type_patterns:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                type_security = norm(m.group(0))
                break

        demat_match = re.search(r'(Demat|Physical)', line, re.IGNORECASE)
        physical_demat = norm(demat_match.group(0)) if demat_match else ''

        row_class = classify_row(type_security, raw_lockin)
        is_free = (row_class == 'free')

        rows.append({
            'shares': shares,
            'from': from_num,
            'to': to_num,
            'type_security': type_security,
            'from_date': from_date,
            'to_date': to_date,
            'lockin_date': to_date if to_date else from_date,
            'raw_lockin': raw_lockin,
            'physical_demat': physical_demat,
            'is_free': is_free,
            'row_class': row_class,
        })

    if not rows or not saw_two_date_locked_row:
        return None

    computed_total = sum(r['shares'] for r in rows)

    # Backward-compatible acceptance:
    # prefer exact TOTAL row from text; fallback to known_total if text total absent.
    if declared_total_from_text is not None:
        if computed_total != declared_total_from_text:
            return None
        total_match = True
        declared_total = declared_total_from_text
    elif known_total is not None:
        if computed_total != known_total:
            return None
        total_match = True
        declared_total = known_total
    else:
        declared_total = computed_total
        total_match = True

    return {
        'rows': rows,
        'declared_total': declared_total,
        'computed_total': computed_total,
        'total_match': total_match,
        'rows_count': len(rows),
        'free_count': sum(1 for r in rows if r.get('is_free')),
        'locked_count': sum(1 for r in rows if not r.get('is_free')),
        'free_shares': sum(r['shares'] for r in rows if r.get('is_free')),
        'locked_shares': sum(r['shares'] for r in rows if not r.get('is_free')),
        'strategy': 'two_dates_fallback',
    }


def parse_bse_text(
    text: str,
    known_total: Optional[int] = None,
    declared_total_hint: Optional[int] = None,
    computed_total_hint: Optional[int] = None
) -> Dict:
    """
    Parse BSE lock-in text using CASCADE of strategies

    Strategies (in order):
    1. Strategy 2: Total Validation (uses known_total if provided, or finds TOTAL in text)
    2. Strategy 1: Line-by-line (original parser, fallback)
    3. Strategy 4: 3-number format without malformed cleanup [ASTONEA-FIX 2026-03-09]
    4. Strategy 3: Distinctive Number Range Calculation [RANGE-CALC 2026-03-09]
    5. Strategy 5: Sum-first with soft distinctive labels (FINAL FALLBACK)
    6. Strategy 6: Two-date fallback (final rescue for explicit from+upto rows)

    Args:
        text: Raw BSE lock-in text
        known_total: Known total from database (optional, makes Strategy 2 more robust)
        declared_total_hint: Additional declared-total hint (optional)
        computed_total_hint: Additional computed-total hint (optional)

    Returns:
        Dict with rows, totals, and 'strategy' field indicating which worked
    """
    # Anchor totals only if they exist on the lock-in page.
    page_numbers: set[int] = set()
    for raw_line in text.split('\n'):
        for n in extract_numbers(raw_line):
            page_numbers.add(n)

    anchored_hints: List[int] = []
    for hint in [known_total, declared_total_hint, computed_total_hint]:
        if hint and hint > 0 and hint in page_numbers and hint not in anchored_hints:
            anchored_hints.append(hint)

    def _is_strategy_result_acceptable(result: Optional[Dict]) -> bool:
        if result is None or len(result.get('rows', [])) == 0:
            return False

        # Backward compatibility: if no anchored hint exists on page, accept first non-empty strategy.
        if not anchored_hints:
            return True

        computed_total = result.get('computed_total')
        if computed_total is None:
            computed_total = sum((r.get('shares') or 0) for r in result.get('rows', []))
        return computed_total in anchored_hints

    # Try Strategy 2 first (works with or without known_total)
    result = parse_bse_strategy2_reverse_from_total(text, known_total)
    if _is_strategy_result_acceptable(result):
        return result

    # Try Strategy 1 (line-by-line)
    result = parse_bse_strategy1_line_by_line(text)
    if _is_strategy_result_acceptable(result):
        return result

    # [ASTONEA-FIX 2026-03-09] Try Strategy 4 (3-number format, no malformed cleanup)
    result = parse_bse_strategy4_no_malformed_cleanup(text, known_total)
    if _is_strategy_result_acceptable(result):
        return result

    # [RANGE-CALC 2026-03-09] Try Strategy 3 (range calculation - 2 numbers only)
    result = parse_bse_strategy3_range_calculation(text, known_total)
    if _is_strategy_result_acceptable(result):
        return result

    # Strategy 5: Sum-first soft labels (final fallback)
    result = parse_bse_strategy5_sum_first_soft_labels(
        text=text,
        known_total=known_total,
        declared_total_hint=declared_total_hint,
        computed_total_hint=computed_total_hint,
    )
    if _is_strategy_result_acceptable(result):
        return result

    # Strategy 6: Two-date fallback (last resort for rows with explicit from+upto dates)
    # Intentionally validated against text TOTAL to remain robust when DB hint is stale.
    result = parse_bse_strategy6_two_dates(text, known_total=known_total)
    if result and result.get('rows'):
        return result

    # All strategies failed
    return {
        'rows': [],
        'declared_total': None,
        'computed_total': 0,
        'total_match': False,
        'rows_count': 0,
        'free_count': 0,
        'locked_count': 0,
        'free_shares': 0,
        'locked_shares': 0,
        'strategy': 'all_failed',
    }
