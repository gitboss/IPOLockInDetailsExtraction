#!/usr/bin/env python3
# Version: 1.0
"""
Shared parsing functions for BSE and NSE lock-in data processing.
These functions are used by both plumber.py and bse_lockin_comparison.py.
"""

import re
from datetime import datetime
from typing import Optional


def clean_num(val) -> Optional[int]:
    """
    Clean and convert a value to integer, handling commas, spaces, and special chars.

    Args:
        val: Input value (string or number)

    Returns:
        Integer value or None if conversion fails

    Examples:
        clean_num("1,23,456") -> 123456
        clean_num("1 234") -> 1234
        clean_num("1234.00") -> 1234
        clean_num("88000*") -> 88000
    """
    if val is None:
        return None
    s = re.sub(r'[^\d.]', '', str(val)).strip()  # Keep only digits and decimal point
    s = re.sub(r'\.0+$', '', s)
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None


def norm(s: str) -> str:
    """
    Normalize whitespace in a string.

    Args:
        s: Input string

    Returns:
        String with normalized whitespace (single spaces, stripped)
    """
    if not s:
        return ''
    return ' '.join(s.split())


def parse_date_str(date_str: str) -> str:
    """
    Parse various date formats and return ISO format (YYYY-MM-DD).

    Handles formats:
        - DD/MM/YYYY, DD-MM-YYYY
        - DD-Mon-YYYY (e.g., 15-Jan-2025)
        - Month DD, YYYY (e.g., January 15, 2025)
        - DDth Month YYYY (e.g., 28th November 2025)
        - DD-MM-YYYY (Anchor) (e.g., 15-12-2025 (Anchor))
        - FREE, N/A, NA, Free IPO Shares (returns as-is)

    Args:
        date_str: Input date string

    Returns:
        ISO formatted date (YYYY-MM-DD) or original string if special/invalid
    """
    if not date_str:
        return ''

    s = date_str.strip().upper()

    # Handle special values (including "Free IPO Shares", "Free Shares", etc.)
    if s in ['FREE', 'N/A', 'NA', 'NIL'] or 'FREE' in s or 'IPO' in s:
        return 'FREE'

    # Remove text in parentheses like "(Anchor)" before parsing
    # "15-12-2025 (Anchor)" -> "15-12-2025"
    cleaned_date = re.sub(r'\s*\([^)]+\)\s*', ' ', date_str).strip()

    # Remove ordinal suffixes (1st, 2nd, 3rd, 4th-31st) for parsing
    # Match patterns like "28th November 2025" -> "28 November 2025"
    cleaned_date = re.sub(r'(\d{1,2})(?:st|nd|rd|th)\b', r'\1', cleaned_date)

    # Preserve ambiguous numeric dates (e.g., 12/11/2028) for contextual parsing later.
    # Unambiguous numeric dates (e.g., 11/28/2025) are still parsed below.
    amb = re.match(r'^\s*(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{2,4})\s*$', cleaned_date)
    if amb:
        first = int(amb.group(1))
        second = int(amb.group(2))
        if first <= 12 and second <= 12:
            return cleaned_date.strip()

    # Try various date formats
    formats = [
        '%d/%m/%Y',      # 15/01/2025
        '%d-%m-%Y',      # 15-01-2025
        '%d.%m.%Y',      # 15.01.2025
        '%d/%m/%y',      # 15/01/25
        '%d-%m-%y',      # 15-01-25
        '%d-%b-%Y',      # 15-Jan-2025
        '%d-%b-%y',      # 15-Jan-25
        '%d %b %Y',      # 15 Jan 2025
        '%d/%b/%Y',      # 15/Jan/2025
        '%d %B %Y',      # 28 November 2025 (after removing "th")
        '%d %b %Y',      # 28 Nov 2025 (after removing "th")
        '%B %d, %Y',     # January 15, 2025
        '%B %d %Y',      # January 15 2025 (no comma)
        '%b %d, %Y',     # Jan 15, 2025
        '%b %d %Y',      # Jan 15 2025 (no comma)
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned_date.strip(), fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue

    # If no format matched, return original
    return date_str


# Classification constants and helpers (from plumber.py - well tested)
FREE_DATE_VALS = {"", "-", "--", "---", "_", "free", "n/a", "na", "nil"}

def is_free_date(d):
    """Check if a date string indicates free shares."""
    d = d.strip().lower()
    if d in FREE_DATE_VALS:
        return True
    if "free" in d:
        return True
    if "ipo" in d and "shares" in d:  # "IPO Shares" indicates free shares
        return True
    if re.match(r'n\.?a\.?', d):
        return True
    return False

def is_locked_type(t):
    """Check if security type indicates locked shares."""
    return (
        "lock" in t or ",l" in t.replace(" ", "") or
        "& l" in t or "f,l" in t or
        "locked in" in t or "under lock" in t
    )

def classify_row(type_security: str, raw_lockin: str) -> str:
    """
    Classify a lock-in row as 'free', 'locked', or 'anchor'.

    This uses the well-tested logic from plumber.py.

    Args:
        type_security: Security type description
        raw_lockin: Lock-in date or status

    Returns:
        'free', 'locked', or 'anchor'
    """
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


def extract_dates_from_line(line: str):
    """
    Extract lock-in dates from a line of text.
    Shared by ALL BSE parsing strategies.

    Handles formats:
    - DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    - DD-Mon-YYYY (e.g., 09-Dec-25)
    - Month DD, YYYY
    - DDth Month YYYY
    - Free IPO Shares, IPO Shares, FREE, N/A

    Args:
        line: Text line to extract dates from

    Returns:
        Dict with 'from_date_raw', 'to_date_raw', 'from_date', 'to_date'
    """
    # Comprehensive date pattern (same for ALL strategies)
    date_pattern = r'(Free\s+(?:IPO\s+)?Shares?|IPO\s+Shares?|FREE|N/?A|N\.?A\.?|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4}|\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}(?:\s*\([^)]+\))?|\d{1,2}[-/\.][A-Za-z]{3}[-/\.]\d{2,4}|[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})'
    dates_found = re.findall(date_pattern, line, re.IGNORECASE)

    from_date_raw = ''
    to_date_raw = ''

    if len(dates_found) >= 2:
        from_date_raw = dates_found[0]
        to_date_raw = dates_found[1]
    elif len(dates_found) == 1:
        to_date_raw = dates_found[0]

    # Parse dates using parse_date_str
    from_date = parse_date_str(from_date_raw) if from_date_raw else ''
    to_date = parse_date_str(to_date_raw) if to_date_raw else ''

    return {
        'from_date_raw': from_date_raw,
        'to_date_raw': to_date_raw,
        'from_date': from_date,
        'to_date': to_date,
    }


# ============================================================================
# Database Verification (Shared by BSE and NSE comparison files)
# ============================================================================

def verify_against_database(exchange, identifier, java_results, java_shp_results, db_connection_func):
    """
    Shared verification function for both BSE and NSE.

    Args:
        exchange: 'BSE' or 'NSE'
        identifier: exchange_code (for BSE) or symbol (for NSE)
        java_results: Parsed lock-in results dict
        java_shp_results: Parsed SHP results dict
        db_connection_func: Function that returns database connection

    Returns:
        Tuple: (can_finalize: bool, verification_details: dict)
    """
    try:
        # Import here to avoid circular dependency
        import mysql.connector

        conn = db_connection_func()
        if conn is None:
            return (None, {'error': 'Database connection failed (check console for details)'})

        cur = conn.cursor(dictionary=True)

        # Build query based on exchange
        if exchange == 'BSE':
            where_clause = "exchange='BSE' AND exchange_code=%s"
            sql_query = f"SELECT * FROM sme_ipo_lockin_details WHERE exchange='BSE' AND exchange_code='{identifier}' LIMIT 1"
        else:  # NSE
            where_clause = "exchange='NSE' AND symbol=%s"
            sql_query = f"SELECT * FROM sme_ipo_lockin_details WHERE exchange='NSE' AND symbol='{identifier}' LIMIT 1"

        # Get main record with all auto-lock criteria fields
        cur.execute(f"""
            SELECT id, computed_total, declared_total, shp_locked_total,
                   promoter_shares, public_shares, other_shares, total_shares,
                   locked_forever, finalized, finalized_at,
                   total_match, shp_match, gemini_lockin_match, gemini_shp_match, gemini_split_match, status
            FROM sme_ipo_lockin_details
            WHERE {where_clause}
            LIMIT 1
        """, (identifier,))

        db_main = cur.fetchone()
        if not db_main:
            cur.close()
            conn.close()
            return (False, {'error': 'Symbol not found in database', 'sql_query': sql_query})

        # Compare main fields
        mismatches = []

        # Lock-in totals
        if db_main['computed_total'] != java_results.get('computed_total'):
            mismatches.append(f"computed_total: DB={db_main['computed_total']}, Parsed={java_results.get('computed_total')}")

        if db_main['declared_total'] != java_results.get('declared_total'):
            mismatches.append(f"declared_total: DB={db_main['declared_total']}, Parsed={java_results.get('declared_total')}")

        # SHP fields
        if java_shp_results:
            if db_main['promoter_shares'] != java_shp_results.get('promoter_shares'):
                mismatches.append(f"promoter_shares: DB={db_main['promoter_shares']}, Parsed={java_shp_results.get('promoter_shares')}")

            if db_main['public_shares'] != java_shp_results.get('public_shares'):
                mismatches.append(f"public_shares: DB={db_main['public_shares']}, Parsed={java_shp_results.get('public_shares')}")

            # Normalize None to 0 for comparison (NULL in DB = 0 in parsed data)
            db_other = db_main['other_shares'] or 0
            parsed_other = java_shp_results.get('other_shares') or 0
            if db_other != parsed_other:
                mismatches.append(f"other_shares: DB={db_main['other_shares']}, Parsed={java_shp_results.get('other_shares', 0)}")

            if db_main['total_shares'] != java_shp_results.get('total_shares'):
                mismatches.append(f"total_shares: DB={db_main['total_shares']}, Parsed={java_shp_results.get('total_shares')}")

            if db_main['shp_locked_total'] != java_shp_results.get('shp_locked_total'):
                mismatches.append(f"shp_locked_total: DB={db_main['shp_locked_total']}, Parsed={java_shp_results.get('shp_locked_total')}")

        # Get rows
        cur.execute("""
            SELECT shares, lock_from, lock_upto, days_locked, lock_bucket, type_raw, row_class
            FROM sme_ipo_lockin_rows
            WHERE scrip_id=%s
            ORDER BY id
        """, (db_main['id'],))

        db_rows = cur.fetchall()
        parsed_rows = java_results.get('rows', [])

        if len(db_rows) != len(parsed_rows):
            mismatches.append(f"Row count: DB={len(db_rows)}, Parsed={len(parsed_rows)}")

        cur.close()
        conn.close()

        # Check locked_forever = 1
        can_finalize = (db_main['locked_forever'] == 1) and (len(mismatches) == 0)

        return (can_finalize, {
            'mismatches': mismatches,
            'locked_forever': db_main['locked_forever'],
            'finalized': db_main['finalized'],
            'finalized_at': db_main['finalized_at'],
            'id': db_main['id'],
            'sql_query': sql_query,
            # Auto-lock criteria (for debug display)
            'status': db_main.get('status'),
            'total_match': db_main.get('total_match'),
            'shp_match': db_main.get('shp_match'),
            'gemini_lockin_match': db_main.get('gemini_lockin_match'),
            'gemini_shp_match': db_main.get('gemini_shp_match'),
            'gemini_split_match': db_main.get('gemini_split_match')
        })

    except Exception as e:
        return (None, {'error': str(e), 'sql_query': 'Exception occurred before query'})
