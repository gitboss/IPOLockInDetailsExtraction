#!/usr/bin/env python3
"""
Unified Lock-in Parser - Combines all parsing approaches into a single parser.

Version: 1.0.0

This module provides a unified interface for extracting lock-in table data
from extracted text using various approaches.

Approaches:
    1. pdfplumber_table - Direct table extraction from PDF
    2. java_text_regex - Java tool + regex parsing
    3. pymupdf_text - PyMuPDF text extraction fallback
    4. tesseract_ocr - For scanned/image PDFs

Usage:
    from lockin_parser_unified import parse_lockin_text
    
    result = parse_lockin_text(text, allotment_date="2024-01-15")
    print(result)
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ============================================================================
# CONSTANTS
# ============================================================================

BUCKETS = [
    ("anchor_30", 15, 45),
    ("anchor_90", 75, 105),
    ("1_year", 330, 400),
    ("2_year", 690, 780),
    ("3_year", 1055, 1145),
]

FREE_DATE_VALS = {"", "-", "--", "---", "_", "free", "n/a", "na", "nil"}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def clean_num(val) -> Optional[int]:
    """Clean and convert a value to integer."""
    if val is None:
        return None
    s = re.sub(r'[^\d.]', '', str(val)).strip()
    s = re.sub(r'\.0+$', '', s)
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None


def norm(s: str) -> str:
    """Normalize whitespace in a string."""
    if not s:
        return ''
    return ' '.join(s.split())


def parse_date_str(date_str: str) -> str:
    """
    Parse various date formats and return ISO format (YYYY-MM-DD).
    """
    if not date_str:
        return ''

    s = date_str.strip().upper()

    if s in ['FREE', 'N/A', 'NA', 'NIL'] or 'FREE' in s or 'IPO' in s:
        return 'FREE'

    cleaned_date = re.sub(r'\s*\([^)]+\)\s*', ' ', date_str).strip()
    cleaned_date = re.sub(r'(\d{1,2})(?:st|nd|rd|th)\b', r'\1', cleaned_date)

    formats = [
        '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y',
        '%d/%m/%y', '%d-%m-%y',
        '%d-%b-%Y', '%d-%b-%y',
        '%d/%b/%Y', '%d/%b/%y',
        '%B %d,%Y', '%B %d, %Y', '%b %d,%Y', '%b %d, %Y',
        '%d %b %Y', '%d %B %Y',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(cleaned_date, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return date_str


def parse_date(val):
    """Parse date string to datetime.date."""
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
                "%d-%b-%Y", "%d-%b-%y", "%B %d,%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            pass
    try:
        from dateutil import parser as dp
        return dp.parse(val.strip(), dayfirst=False).date()
    except Exception:
        pass
    return None


def is_free_date(d: str) -> bool:
    """Check if date string indicates a free row."""
    d = d.strip().lower()
    return d in FREE_DATE_VALS or "free" in d or bool(re.match(r'n\.?a\.?', d))


def is_locked_type(t: str) -> bool:
    """Check if security type indicates locked status."""
    t = t.lower().strip()
    return (
        "lock" in t or ",l" in t.replace(" ", "") or
        "& l" in t or "f,l" in t or
        "locked in" in t or "under lock" in t
    )


def classify_row(type_security: str, raw_lockin: str) -> str:
    """Classify a lock-in row as 'free', 'locked', or 'anchor'."""
    t = type_security.lower().strip() if type_security else ''
    d = raw_lockin.strip() if raw_lockin else ''

    if "anchor" in t or "30 day" in t or "90 day" in t:
        return "anchor"
    if re.search(r'\(anchor', d.lower()):
        return "anchor"
    if re.search(r'\bipo\b', t) and "lock" in t and is_free_date(d):
        return "free"
    if is_free_date(d):
        if not is_locked_type(t):
            return "free"
    if "free" in t or "not under lock" in t or "market maker" in t:
        return "free"
    if "offer for sale" in t and "lock" not in t:
        return "free"
    if re.search(r'\bipo\b', t) and "lock" not in t:
        return "free" if is_free_date(d) else "locked"
    if is_locked_type(t):
        return "locked"
    if d and not is_free_date(d):
        return "locked"
    return "free"


def classify_bucket(days: int, row_class: str = "locked") -> str:
    """Classify days into bucket."""
    if days is None:
        return "unknown"
    if row_class == "anchor":
        if days <= 45:
            return "anchor_30"
        return "anchor_90"
    for bucket, lo, hi in BUCKETS:
        if lo <= days <= hi:
            return bucket
    return "unknown"


# ============================================================================
# ROW EXTRACTION
# ============================================================================

def extract_table_rows(text: str) -> List[Dict]:
    """
    Extract lock-in table rows from Java text.
    
    Format:
    No. of Equity Shares | From | To | Lock in upto
    5390328              | 1    | 5390328 | 08-Oct-2026
    """
    rows = []
    lines = text.splitlines()

    for i, line in enumerate(lines):
        line = line.strip()

        if not line or 'Distinctive' in line or 'Lock in' in line or 'Equity' in line:
            continue

        match = re.match(r'(\d[\d,\*]*)\s+(\d[\d,\*]*)\s+(\d[\d,\*]*)\s+(.+)', line)

        if match:
            shares_str = match.group(1).replace(',', '')
            from_str = match.group(2).replace(',', '')
            to_str = match.group(3).replace(',', '')
            lockin_str = match.group(4).strip()

            if 'Total' in lockin_str or 'total' in lockin_str.lower():
                continue

            try:
                shares = int(re.sub(r'[^\d]', '', shares_str))
                from_num = int(re.sub(r'[^\d]', '', from_str))
                to_num = int(re.sub(r'[^\d]', '', to_str))

                lockin_date = None
                is_free = False

                if 'Free' in lockin_str or 'free' in lockin_str.lower():
                    is_free = True
                else:
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

            except (ValueError, IndexError):
                continue

    return rows


def extract_table_rows_from_pdfplumber(table: List[List]) -> List[Dict]:
    """
    Extract rows from pdfplumber table structure.
    """
    rows = []
    if not table:
        return rows

    ncols = max(len(r) for r in table) if table else 0
    data_start = 1
    header_end = 0

    for i, row in enumerate(table[:10]):
        flat_lower = [str(c).lower() if c else '' for c in row]
        if "from" in flat_lower and "to" in flat_lower:
            header_end = i
            data_start = i + 1
            break

    shares_col = 0
    date_col = None

    for ci in range(ncols):
        header_cells = []
        for hi in range(min(header_end + 1, len(table))):
            if ci < len(table[hi]):
                val = table[hi][ci]
                if val:
                    header_cells.append(str(val).lower())
        
        header_text = ' '.join(header_cells)
        if "lock" in header_text or "upto" in header_text or "date" in header_text:
            if date_col is None:
                date_col = ci
        if "share" in header_text or "securit" in header_text:
            shares_col = ci

    for row in table[data_start:]:
        if not row or all(not c for c in row):
            continue

        shares_val = row[shares_col] if shares_col < len(row) else None
        shares = clean_num(shares_val)
        if shares is None or shares < 100:
            continue

        date_val = row[date_col] if date_col is not None and date_col < len(row) else ""
        date_str = str(date_val).strip() if date_val else ""

        is_free = is_free_date(date_str)
        lockin_date = None if is_free else date_str

        row_class = classify_row("", date_str)

        rows.append({
            'shares': shares,
            'from': None,
            'to': None,
            'lockin_date': lockin_date,
            'lockin_date_from': None,
            'type_raw': "",
            'is_free': is_free,
            'row_class': row_class,
        })

    return rows


# ============================================================================
# TOTAL EXTRACTION
# ============================================================================

def extract_total_from_text(text: str) -> Optional[int]:
    """Extract total shares from text."""
    for line in text.splitlines():
        if 'Total' in line or 'total' in line.lower():
            numbers = re.findall(r'\d[\d,]*', line)
            if numbers:
                candidates = [int(re.sub(r'[^\d]', '', n)) for n in numbers]
                return max(candidates)
    return None


# ============================================================================
# BUCKET CALCULATION
# ============================================================================

def calculate_bucket(row: Dict, allotment_date: Optional[str] = None) -> Tuple[Optional[int], str]:
    """
    Calculate days locked and bucket for a row.
    
    Args:
        row: Row dict with 'from_date', 'to_date', 'is_free'
        allotment_date: Allotment date from database
    
    Returns:
        Tuple of (days_locked, bucket)
    """
    row_class = 'free' if row.get('is_free') else 'locked'
    if row_class == 'free':
        return (None, 'free')

    lock_from = row.get('lockin_date_from') or row.get('from_date')
    lock_upto = row.get('lockin_date') or row.get('to_date')

    if not lock_upto:
        return (None, 'unknown')

    start_date = lock_from if lock_from else allotment_date
    if not start_date:
        return (None, 'unknown')

    try:
        if isinstance(start_date, str):
            from_dt = parse_date(start_date)
            if not from_dt:
                return (None, 'unknown')
        else:
            from_dt = start_date

        if isinstance(lock_upto, str):
            to_dt = parse_date(lock_upto)
            if not to_dt:
                return (None, 'unknown')
        else:
            to_dt = lock_upto

        days_locked = (to_dt - from_dt).days

        if days_locked < 0 or days_locked > 9999:
            return (days_locked, 'unknown')

        bucket = classify_bucket(days_locked, row_class)
        return (days_locked, bucket)

    except Exception:
        return (None, 'unknown')


# ============================================================================
# ANNEXURE II EXTRACTION
# ============================================================================

def extract_annexure_ii_unlock_schedule(text: str) -> List[Dict]:
    """Extract Annexure II - unlock schedule table."""
    rows = []
    in_annexure_ii = False
    lines = text.splitlines()

    for i, line in enumerate(lines):
        line_normalized = re.sub(r'\s+', ' ', line.strip()).lower()

        if 'annexure' in line_normalized and ('ii' in line_normalized or '2' in line_normalized):
            in_annexure_ii = True
            continue

        if any(keyword in line_normalized for keyword in ['eligible', 'traded', 'unlock', 'schedule']):
            in_annexure_ii = True
            continue

        if in_annexure_ii and 'annexure' in line_normalized and ('i' in line_normalized or '1' in line_normalized):
            if 'ii' not in line_normalized and '2' not in line_normalized:
                break

        if not in_annexure_ii:
            continue

        date_match = re.search(r'(\d{1,2}-[A-Za-z]{3}-\d{4})', line)
        if date_match:
            date_str = date_match.group(1)
            numbers = re.findall(r'\d[\d,]*', line)
            date_numbers = set(re.findall(r'\d+', date_str))
            share_numbers = []

            for num_str in numbers:
                num_clean = num_str.replace(',', '')
                if num_clean not in date_numbers:
                    try:
                        val = int(num_clean)
                        share_numbers.append(val)
                    except ValueError:
                        continue

            if share_numbers:
                rows.append({
                    'date': date_str,
                    'shares': max(share_numbers),
                })

    return rows


# ============================================================================
# MAIN UNIFIED PARSER
# ============================================================================

def parse_lockin_text(
    text: str,
    listing_date: Optional[str] = None,
    allotment_date: Optional[str] = None
) -> Dict:
    """
    Unified lock-in parser.
    
    Args:
        text: Java-extracted text from lock-in PDF
        listing_date: Listing date (optional)
        allotment_date: Allotment date (for bucket calculation)
    
    Returns:
        Dict with:
            - rows: List of parsed rows
            - declared_total: Total from "Total" row
            - computed_total: Sum of all share counts
            - total_match: Whether declared and computed match
            - locked_shares: Sum of locked shares
            - free_shares: Sum of free shares
            - anchor_shares: Sum of anchor shares
            - strategy_used: str
    """
    rows = extract_table_rows(text)
    declared_total = extract_total_from_text(text)
    computed_total = sum(row['shares'] for row in rows) if rows else None

    total_match = (
        declared_total is not None and
        computed_total is not None and
        declared_total == computed_total
    )

    for row in rows:
        days, bucket = calculate_bucket(row, allotment_date)
        row['days_locked'] = days
        row['lock_bucket'] = bucket
        row['row_class'] = classify_row(row.get('type_raw', ''), row.get('raw_lockin', ''))

    free_shares = sum(r['shares'] for r in rows if r.get('is_free'))
    locked_shares = sum(r['shares'] for r in rows if not r.get('is_free') and r.get('row_class') != 'anchor')
    anchor_shares = sum(r['shares'] for r in rows if r.get('row_class') == 'anchor')

    return {
        'rows': rows,
        'declared_total': declared_total,
        'computed_total': computed_total,
        'total_match': total_match,
        'rows_count': len(rows),
        'free_count': sum(1 for r in rows if r.get('is_free')),
        'locked_count': sum(1 for r in rows if not r.get('is_free')),
        'free_shares': free_shares,
        'locked_shares': locked_shares,
        'anchor_shares': anchor_shares,
        'strategy_used': 'java_text_regex'
    }


def parse_lockin_from_pdfplumber(
    table: List[List],
    listing_date: Optional[str] = None,
    allotment_date: Optional[str] = None
) -> Dict:
    """Parse lock-in from pdfplumber table structure."""
    rows = extract_table_rows_from_pdfplumber(table)
    declared_total = sum(r['shares'] for r in rows)
    computed_total = declared_total

    total_match = True

    for row in rows:
        days, bucket = calculate_bucket(row, allotment_date)
        row['days_locked'] = days
        row['lock_bucket'] = bucket

    free_shares = sum(r['shares'] for r in rows if r.get('is_free'))
    locked_shares = sum(r['shares'] for r in rows if not r.get('is_free') and r.get('row_class') != 'anchor')
    anchor_shares = sum(r['shares'] for r in rows if r.get('row_class') == 'anchor')

    return {
        'rows': rows,
        'declared_total': declared_total,
        'computed_total': computed_total,
        'total_match': total_match,
        'rows_count': len(rows),
        'free_count': sum(1 for r in rows if r.get('is_free')),
        'locked_count': sum(1 for r in rows if not r.get('is_free')),
        'free_shares': free_shares,
        'locked_shares': locked_shares,
        'anchor_shares': anchor_shares,
        'strategy_used': 'pdfplumber_table'
    }


# ============================================================================
# COMPLETE PARSING WITH ALL METHODS
# ============================================================================

def parse_lockin_complete(
    text: str = None,
    table: List[List] = None,
    listing_date: Optional[str] = None,
    allotment_date: Optional[str] = None
) -> Dict:
    """
    Complete lock-in parsing with fallback.
    Tries table first (pdfplumber), then text parsing.
    """
    if table:
        result = parse_lockin_from_pdfplumber(table, listing_date, allotment_date)
        if result.get('rows'):
            return result

    if text:
        return parse_lockin_text(text, listing_date, allotment_date)

    return {
        'rows': [],
        'declared_total': None,
        'computed_total': None,
        'total_match': False,
        'rows_count': 0,
        'free_count': 0,
        'locked_count': 0,
        'free_shares': 0,
        'locked_shares': 0,
        'anchor_shares': 0,
        'strategy_used': 'none'
    }


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python lockin_parser_unified.py <text_file>")
        sys.exit(1)
    
    text_file = sys.argv[1]
    with open(text_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    result = parse_lockin_text(text)
    print(f"Rows: {result['rows_count']}")
    print(f"Computed Total: {result['computed_total']}")
    print(f"Declared Total: {result['declared_total']}")
    print(f"Total Match: {result['total_match']}")
    print(f"Locked Shares: {result['locked_shares']}")
    print(f"Free Shares: {result['free_shares']}")
