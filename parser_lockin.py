"""
Lock-in Details Parser
PRODUCTION LOGIC - Replicated from F:\\python\\ScripUnlockDetails\\shared_parsing.py
Unified parser for both NSE and BSE lock-in TXT files
Extracts rows with share counts, dates, and lock-in status
"""

import re
from datetime import datetime, date
from dateutil import parser as dateutil_parser
from pathlib import Path
from typing import Optional

from models import LockinRow, LockinData, RowStatus, LockBucket
from lockin_parser_production_unified import parse_bse_text, parse_lockin_table


def parse_number(text: str) -> Optional[int]:
    """
    Parse number from text (handles Indian comma format)
    Examples: "1,23,45,678" → 12345678, "1234" → 1234
    """
    if not text:
        return None

    # Remove all non-digit characters except decimal point
    cleaned = re.sub(r'[^\d.]', '', text.strip())

    if not cleaned or cleaned == '.':
        return None

    try:
        # Convert to integer (ignore decimals for share counts)
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def parse_date_str(date_str: str) -> str:
    """
    Parse various date formats and return ISO format (YYYY-MM-DD).
    PRODUCTION LOGIC - Replicated from F:\\python\\ScripUnlockDetails\\shared_parsing.py

    Handles formats:
        - DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
        - DD/MM/YY, DD-MM-YY
        - DD-Mon-YYYY, DD-Mon-YY (e.g., 15-Jan-2025, 15-Jan-25)
        - DD/Mon/YYYY, DD/Mon/YY (e.g., 15/Jan/2025, 15/Jan/25)
        - DD Mon YYYY, DD Month YYYY (e.g., 15 Jan 2025, 15 January 2025)
        - Month DD,YYYY / Month DD, YYYY (e.g., January 15,2025  January 15, 2025)
        - Mon DD,YYYY / Mon DD, YYYY (e.g., Jan 15,2025  Jan 15, 2025)
        - DDth Month YYYY (e.g., 28th November 2025)
        - DD-MM-YYYY (Anchor) -> parenthetical text stripped before parsing
        - FREE, N/A, NA, NIL, or any string containing FREE/IPO (returns 'FREE')

    Args:
        date_str: Input date string

    Returns:
        ISO formatted date (YYYY-MM-DD) or 'FREE' for free shares or original if invalid
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

    # Try various date formats
    formats = [
        '%d/%m/%Y',      # 15/01/2025
        '%d-%m-%Y',      # 15-01-2025
        '%d.%m.%Y',      # 15.01.2025
        '%d/%m/%y',      # 15/01/25
        '%d-%m-%y',      # 15-01-25
        '%d-%b-%Y',      # 15-Jan-2025
        '%d-%b-%y',      # 15-Jan-25
        '%d/%b/%Y',      # 15/Jan/2025
        '%d/%b/%y',      # 15/Jan/25
        '%B %d,%Y',      # January 15,2025
        '%B %d, %Y',     # January 15, 2025
        '%b %d,%Y',      # Jan 15,2025
        '%b %d, %Y',     # Jan 15, 2025
        '%d %b %Y',      # 15 Jan 2025
        '%d %B %Y',      # 15 January 2025
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned_date.strip(), fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue

    # If no format matched, return original
    return date_str


def parse_date(date_str: str) -> Optional[date]:
    """
    Secondary date parser. Returns a datetime.date object (or None on failure).
    Handles a broad set of formats then falls back to dateutil for anything else.

    Handles formats:
        - YYYY-MM-DD  (ISO, e.g. 2025-01-15)
        - DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY
        - DD-Mon-YYYY, DD-Mon-YY (e.g., 15-Jan-2025, 15-Jan-25)
        - Month DD,YYYY / Month DD, YYYY (e.g., January 15,2025)
        - dateutil.parser fallback for any other format

    Special values:
        - FREE, N/A, NA, NIL, or strings containing FREE/IPO  -> returns None

    Args:
        date_str: Input date string

    Returns:
        datetime.date or None if parsing fails / special value
    """
    if not date_str:
        return None

    s = date_str.strip().upper()

    # Special values treated as non-dates
    if s in ['FREE', 'N/A', 'NA', 'NIL'] or 'FREE' in s or 'IPO' in s:
        return None

    # Pre-processing: remove parenthetical text and ordinal suffixes
    cleaned = re.sub(r'\s*\([^)]+\)\s*', ' ', date_str).strip()
    cleaned = re.sub(r'(\d{1,2})(?:st|nd|rd|th)\b', r'\1', cleaned).strip()

    formats = [
        '%Y-%m-%d',      # 2025-01-15
        '%d-%m-%Y',      # 15-01-2025
        '%d/%m/%Y',      # 15/01/2025
        '%d.%m.%Y',      # 15.01.2025
        '%d-%b-%Y',      # 15-Jan-2025
        '%d-%b-%y',      # 15-Jan-25
        '%B %d,%Y',      # January 15,2025
        '%B %d, %Y',     # January 15, 2025
    ]

    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    # Fallback: dateutil handles almost any human-readable date string
    try:
        return dateutil_parser.parse(cleaned, dayfirst=True).date()
    except Exception:
        return None


def is_free_date(d: str) -> bool:
    """
    Check if a date string indicates free shares.
    PRODUCTION LOGIC - Replicated from F:\\python\\ScripUnlockDetails\\shared_parsing.py
    """
    FREE_DATE_VALS = {"", "-", "--", "---", "_", "free", "n/a", "na", "nil"}

    d = d.strip().lower()
    if d in FREE_DATE_VALS:
        return True
    if "free" in d:
        return True
    if re.match(r'n\.?a\.?', d):
        return True
    return False


def is_locked_type(t: str) -> bool:
    """
    Check if security type indicates locked shares.
    PRODUCTION LOGIC - Replicated from F:\\python\\ScripUnlockDetails\\shared_parsing.py
    """
    return (
        "lock" in t or ",l" in t.replace(" ", "") or
        "& l" in t or "f,l" in t or
        "locked in" in t or "under lock" in t
    )


def classify_row_type(type_security: str, raw_lockin: str) -> str:
    """
    Classify a lock-in row as 'free', 'locked', or 'anchor'.
    PRODUCTION LOGIC - Replicated from F:\\python\\ScripUnlockDetails\\shared_parsing.py

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


def calculate_bucket(allotment_date: date, lockin_from: Optional[date], lockin_to: Optional[date]) -> LockBucket:
    """
    Calculate lock-in bucket based on duration

    Logic:
    - If no lock-in dates → FREE
    - Calculate days from allotment_date (or lockin_from if available) to lockin_to
    - Bucket: 3+YEARS (>1095 days), 2+YEARS (>730), 1+YEAR (>365), ANCHOR_90DAYS, ANCHOR_30DAYS
    """
    if not lockin_to:
        return LockBucket.FREE

    # Determine start date (use lockin_from if available, else allotment_date)
    start_date = lockin_from if lockin_from else allotment_date

    if not start_date:
        # Can't calculate without start date
        return LockBucket.FREE

    # Calculate days
    days = (lockin_to - start_date).days

    # Classify into buckets (using >= to include exact year boundaries)
    if days >= 1095:  # 3 years (1095 = 3*365)
        return LockBucket.YEARS_3_PLUS
    elif days >= 730:  # 2 years (730 = 2*365)
        return LockBucket.YEARS_2_PLUS
    elif days >= 360:  # 1 year (360 days tolerance for 365-day year)
        return LockBucket.YEARS_1_PLUS
    elif days >= 90:
        return LockBucket.ANCHOR_90_DAYS
    elif days >= 30:
        return LockBucket.ANCHOR_30_DAYS
    else:
        return LockBucket.FREE


def parse_lockin_row(line: str, allotment_date: Optional[date]) -> Optional[LockinRow]:
    """
    Parse a single row from lock-in TXT file
    PRODUCTION LOGIC - Replicated from F:\\python\\ScripUnlockDetails

    Pattern: shares | from | to | lock-in-date/Free
    Example: "5390328  1  5390328  08-Oct-2026"

    Returns LockinRow or None if line doesn't contain valid data
    """
    line = line.strip()

    # Skip empty lines and headers
    if not line or 'Distinctive' in line or 'Lock in' in line or 'Equity' in line or 'Total' in line:
        return None

    # PRODUCTION PATTERN: shares, from, to, lockin_info
    # Pattern: digits followed by spaces/tabs, then more digits (from), then digits (to), then date/Free
    match = re.match(r'(\d[\d,]*)\s+(\d[\d,]*)\s+(\d[\d,]*)\s+(.+)', line)

    if not match:
        return None

    # Extract matched groups
    shares_str = match.group(1).replace(',', '')
    from_str = match.group(2).replace(',', '')
    to_str = match.group(3).replace(',', '')
    lockin_str = match.group(4).strip()

    # Check if this is a total row (skip it)
    if 'Total' in lockin_str or 'total' in lockin_str.lower():
        return None

    try:
        shares = int(shares_str)
        from_num = int(from_str)
        to_num = int(to_str)
    except (ValueError, IndexError):
        return None

    # Extract and parse lock-in date
    lockin_from = None
    lockin_to = None
    status = RowStatus.FREE

    # First check if explicitly free
    if is_free_date(lockin_str):
        status = RowStatus.FREE
    else:
        # Try to extract date from lockin_str using multiple patterns
        date_str = None

        # Pattern 1: DD/MM/YYYY (like "03/03/2029")
        match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', lockin_str)
        if match:
            date_str = match.group(0)

        # Pattern 2: DD-MM-YYYY (like "03-03-2029")
        if not date_str:
            match = re.search(r'(\d{1,2})-(\d{1,2})-(\d{4})', lockin_str)
            if match:
                date_str = match.group(0)

        # Pattern 3: DD-Mon-YYYY (like "08-Oct-2026")
        if not date_str:
            match = re.search(r'(\d{1,2})-([A-Za-z]{3})-(\d{4})', lockin_str)
            if match:
                date_str = match.group(0)

        # Pattern 4: DD Mon YYYY (like "15 Jan 2025")
        if not date_str:
            match = re.search(r'(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})', lockin_str)
            if match:
                date_str = match.group(0)

        # If we found a date string, parse it
        if date_str:
            parsed = parse_date_str(date_str)
            if parsed and parsed != 'FREE':
                try:
                    lockin_to = datetime.strptime(parsed, '%Y-%m-%d').date()
                    status = RowStatus.LOCKED
                except:
                    status = RowStatus.FREE
            else:
                status = RowStatus.FREE
        else:
            # No date pattern found - treat as free
            status = RowStatus.FREE

    # Calculate bucket
    bucket = LockBucket.FREE
    if status == RowStatus.LOCKED and allotment_date and lockin_to:
        bucket = calculate_bucket(allotment_date, lockin_from, lockin_to)

    # Extract security type from original line (look for type indicators)
    security_type = None
    share_form = None

    # Look for common keywords in the FULL lockin_str (includes everything after shares/from/to)
    if 'equity' in lockin_str.lower():
        security_type = 'Equity'
    if 'demat' in lockin_str.lower():
        share_form = 'Demat'
    elif 'physical' in lockin_str.lower():
        share_form = 'Physical'

    return LockinRow(
        shares=shares,
        distinctive_from=from_num,
        distinctive_to=to_num,
        security_type=security_type,
        lockin_date_from=lockin_from,
        lockin_date_to=lockin_to,
        share_form=share_form,
        status=status,
        bucket=bucket,
    )


def extract_declared_total(text: str) -> Optional[int]:
    """
    Extract total shares from text.
    Look for pattern like "24070263  Total" or "Total  24070263"
    PRODUCTION LOGIC - Replicated from F:\\python\\ScripUnlockDetails
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


def parse_lockin_file(txt_path: Path, allotment_date: Optional[date] = None) -> LockinData:
    """
    Parse lock-in TXT file (unified for NSE and BSE)
    PRODUCTION LOGIC - Replicated from F:\\python\\ScripUnlockDetails

    Args:
        txt_path: Path to *_java.txt file
        allotment_date: Allotment date from sme_ipo_master (for bucket calculation)

    Returns:
        LockinData with all extracted rows and computed totals
    """
    if not txt_path.exists():
        raise FileNotFoundError(f"Lock-in TXT file not found: {txt_path}")

    # Read file
    with open(txt_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Detect exchange from file path
    path_str = str(txt_path).lower().replace('\\', '/')
    is_nse = '/nse/' in path_str
    is_bse = '/bse/' in path_str

    # For NSE files, use general parser directly (BSE parser extracts wrong dates for NSE format)
    # For BSE files, try BSE parser first, then fallback to general parser
    if is_nse:
        result = parse_lockin_table(text)
    else:
        result = parse_bse_text(text)

        # If BSE parser found no rows, try general parser
        if not result.get('rows'):
            result = parse_lockin_table(text)

    # Convert production parser results to LockinData model
    rows = []
    for row_dict in result.get('rows', []):
        # Convert string dates to date objects
        from_date = None
        to_date = None

        if row_dict.get('from_date'):
            from_date = parse_date(row_dict['from_date'])
        if row_dict.get('to_date') or row_dict.get('lockin_date'):
            date_str = row_dict.get('to_date') or row_dict.get('lockin_date')
            to_date = parse_date(date_str)

        # Determine row status
        # Check if lock-in has expired (to_date is in the past)
        from datetime import date as date_type
        today = date_type.today()

        if to_date and to_date < today:
            # Lock-in expired → FREE
            row_status = RowStatus.FREE
        else:
            # Use raw parser's classification
            is_free = row_dict.get('is_free', False)
            row_status = RowStatus.FREE if is_free else RowStatus.LOCKED

        # Calculate bucket
        bucket = calculate_bucket(allotment_date, from_date, to_date) if allotment_date else LockBucket.FREE

        # Create LockinRow
        lockin_row = LockinRow(
            shares=row_dict['shares'],
            distinctive_from=row_dict.get('from', 0),
            distinctive_to=row_dict.get('to', 0),
            security_type=row_dict.get('type_security', ''),
            share_form=row_dict.get('physical_demat', ''),
            lockin_date_from=from_date,
            lockin_date_to=to_date,
            status=row_status,
            bucket=bucket
        )
        rows.append(lockin_row)

    # Create LockinData
    lockin_data = LockinData(rows=rows)

    # Store declared_total from parsing result (if extracted from TOTAL line)
    lockin_data.declared_total = result.get('declared_total')

    # Compute totals
    lockin_data.compute_totals()

    return lockin_data


def main():
    """Test parser with sample file"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parser_lockin.py <path_to_java.txt> [allotment_date]")
        print("Example: python parser_lockin.py downloads/bse/pdf/lockin/txt/544324-CITICHEM-Annexure-I_java.txt 2024-01-15")
        sys.exit(1)

    txt_path = Path(sys.argv[1])

    allotment_date = None
    if len(sys.argv) >= 3:
        allotment_date = datetime.strptime(sys.argv[2], '%Y-%m-%d').date()

    print(f"Parsing: {txt_path}")
    print(f"Allotment Date: {allotment_date}")
    print("=" * 70)

    try:
        result = parse_lockin_file(txt_path, allotment_date)

        print(f"\nOK Extracted {len(result.rows)} rows")
        print(f"  Computed Total: {result.computed_total:,}")
        print(f"  Locked Total:   {result.locked_total:,}")
        print(f"  Free Total:     {result.free_total:,}")

        # Show first 5 rows
        print(f"\nFirst 5 rows:")
        for i, row in enumerate(result.rows[:5]):
            status_icon = "LOCKED" if row.is_locked() else "FREE"
            print(f"  {i+1}. {status_icon} {row.shares:,} shares | {row.bucket.value} | Dates: {row.lockin_date_from} -> {row.lockin_date_to}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
