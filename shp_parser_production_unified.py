#!/usr/bin/env python3
"""
SHP Parser - Production Code (EXACT COPY from lockin_shp_comparision_next.py)
DO NOT MODIFY - Any change will break SHP parsing!

Copied from: lockin_shp_comparision_next.py (lines 113-1920)
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from shared_parsing import parse_date_str, classify_row, clean_num, norm

# SHP pattern definitions
SHP_PATTERNS_A = [
    "totalshareholdingofpromoters",
    "totalshareholdingofpromoter",
    "totalshareholding",
    "(a)promoter&promotergroup",
    "(a)promotergroup",
]
SHP_PATTERNS_B = [
    "totalpublicshareholding",
    "totalpublic",
    "(b)public",
]
SHP_PATTERNS_C = [
    "totalnonpromoter",
    "(c)nonpromoternonpublic",
    "(c)nonpromoternonepublic",
    "(c)nonpublic",
    "(c)nonpromoter",
]

def normalize_pattern_text(text: str) -> str:
    return text.lower().replace(" ", "").replace("-", "")

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





# Database configuration (optional - only used if .env file exists)
# DISABLED: Not needed for pure text parsing
# ENV_PATH, DB_AVAILABLE = init_db_runtime(__file__)
# print(f"[DEBUG] ENV_PATH = {ENV_PATH}")
# print(f"[DEBUG] ENV_PATH.exists() = {ENV_PATH.exists()}")
# print(f"[DEBUG] DB_AVAILABLE = {DB_AVAILABLE}")
ENV_PATH = None
DB_AVAILABLE = False

def get_db_connection():
    """Get database connection using credentials from .env file. Returns None if not available."""
    return shared_get_db_connection(ENV_PATH, DB_AVAILABLE)

def get_db_ipo_data(bse_code: str = None, nse_symbol: str = None) -> Optional[Dict]:
    """
    Query IPO data from sme_ipo_master table.
    Returns dict with post_issue_shares and allotment_date, or None if not found.
    """
    return shared_get_db_ipo_data(get_db_connection, bse_code=bse_code, nse_symbol=nse_symbol)


def calculate_bucket_for_row(row: Dict, allotment_date) -> Tuple[Optional[int], str]:
    """
    Calculate bucket for a row using the same logic as insert_unlock.py.

    Args:
        row: Row dict with 'from_date', 'to_date', 'is_free'
        allotment_date: Allotment date from database (datetime.date or None)

    Returns:
        Tuple of (days_locked, bucket) where:
        - days_locked is None for free/unknown rows
        - bucket is one of: 'anchor_30', 'anchor_90', '1_year', '2_year', '3_year', 'free', 'unknown'
    """
    from datetime import datetime
    from shared_parsing import parse_date_str

    # Handle free rows
    row_class = 'free' if row.get('is_free') else 'locked'
    if row_class == 'free':
        return (None, 'free')

    # Extract dates from row
    lock_from = row.get('from_date')
    lock_upto = row.get('to_date')

    # Missing to_date means we can't calculate bucket
    if not lock_upto:
        return (None, 'unknown')

    # Determine start date (lock_from or allotment_date fallback)
    start_date = lock_from if lock_from else allotment_date
    if not start_date:
        return (None, 'unknown')

    # Parse dates (handle both string and date objects)
    try:
        if isinstance(start_date, str):
            from_dt = parse_date_str(start_date)
            if not from_dt:
                return (None, 'unknown')
            # Convert to date object if it's a datetime string
            if isinstance(from_dt, str):
                from_dt = datetime.strptime(from_dt, '%Y-%m-%d').date()
            elif isinstance(from_dt, datetime):
                from_dt = from_dt.date()
        else:
            from_dt = start_date

        if isinstance(lock_upto, str):
            to_dt = parse_date_str(lock_upto)
            if not to_dt:
                return (None, 'unknown')
            # Convert to date object if it's a datetime string
            if isinstance(to_dt, str):
                to_dt = datetime.strptime(to_dt, '%Y-%m-%d').date()
            elif isinstance(to_dt, datetime):
                to_dt = to_dt.date()
        else:
            to_dt = lock_upto

        # Calculate days difference
        days_locked = (to_dt - from_dt).days

        # Sanity check
        if days_locked < 0 or days_locked > 9999:
            return (days_locked, 'unknown')

        # Classify using insert_unlock.py's classify_bucket
        bucket = classify_bucket(days_locked, row_class)
        return (days_locked, bucket)

    except Exception:
        return (None, 'unknown')


def verify_java_against_database(base_name, nse_symbol, java_results, java_shp_results):
    """
    Verify parsed java results against database records.
    Returns: (is_perfect_match, mismatch_details dict)

    Checks sme_ipo_lockin_details and sme_ipo_lockin_rows tables.
    """
    if not DB_AVAILABLE:
        return (None, {'error': 'Database not available'})

    if not nse_symbol:
        return (None, {'error': 'No NSE symbol'})

    # Use shared verification function
    from shared_parsing import verify_against_database
    return verify_against_database('NSE', nse_symbol, java_results, java_shp_results, get_db_connection)


def _derive_stem_from_pdf_file(pdf_file: Optional[str], symbol: Optional[str]) -> str:
    if pdf_file:
        return Path(pdf_file).stem
    return symbol or ""


def _to_iso_or_none(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _to_int_or_none(value):
    """Best-effort int conversion for distinctive-number fields."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if cleaned.isdigit():
            return int(cleaned)
        return None
    # For date/datetime/other non-numeric values, distinctives are unavailable.
    return None


def fetch_finalized_nse_results_from_db(existing_stems: set) -> List[Tuple]:
    """
    Build report tuples for finalized NSE symbols directly from DB.
    This avoids rescanning finalized PDFs/text while keeping rollback-visible rows.
    """
    if not DB_AVAILABLE:
        return []

    conn = get_db_connection()
    if not conn:
        return []

    out: List[Tuple] = []
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT id AS scrip_id, symbol, unique_symbol, pdf_file,
                   computed_total, declared_total, shp_locked_total,
                   promoter_shares, public_shares, other_shares, total_shares,
                   total_match, shp_match, status, locked_forever,
                   finalized, finalized_at
            FROM sme_ipo_lockin_details
            WHERE exchange = 'NSE' AND finalized = 1
            ORDER BY symbol
            """
        )
        finalized_rows = cur.fetchall()

        for rec in finalized_rows:
            stem = _derive_stem_from_pdf_file(rec.get('pdf_file'), rec.get('symbol'))
            if not stem or stem in existing_stems:
                continue

            cur.execute(
                """
                SELECT shares, lock_from, lock_upto, days_locked, lock_bucket, type_raw, row_class
                FROM sme_ipo_lockin_rows
                WHERE scrip_id = %s
                ORDER BY id
                """,
                (rec['scrip_id'],),
            )
            db_rows = cur.fetchall()

            parsed_rows: List[Dict] = []
            free_shares = 0
            for r in db_rows:
                is_free = (str(r.get('row_class') or '').lower() == 'free')
                shares = int(r.get('shares') or 0)
                lock_from_raw = r.get('lock_from')
                lock_upto_raw = r.get('lock_upto')
                lock_from_iso = _to_iso_or_none(lock_from_raw) if hasattr(lock_from_raw, 'isoformat') else None
                lock_upto_iso = _to_iso_or_none(lock_upto_raw) if hasattr(lock_upto_raw, 'isoformat') else None
                if is_free:
                    free_shares += shares
                parsed_rows.append(
                    {
                        'shares': shares,
                        'from': _to_int_or_none(lock_from_raw),
                        'to': _to_int_or_none(lock_upto_raw),
                        'from_date': lock_from_iso,
                        'to_date': lock_upto_iso,
                        'lockin_date': lock_upto_iso,
                        'is_free': is_free,
                        'raw_lockin': 'Free' if is_free else (lock_upto_iso or r.get('type_raw') or ''),
                        'row_class': r.get('row_class') or ('free' if is_free else 'locked'),
                        'days_locked': r.get('days_locked'),
                        'lock_bucket': r.get('lock_bucket'),
                        'type_raw': r.get('type_raw'),
                    }
                )

            computed_total = rec.get('computed_total') or 0
            total_match = rec.get('total_match')
            method_res = {
                'rows': parsed_rows,
                'declared_total': rec.get('declared_total'),
                'computed_total': rec.get('computed_total'),
                'total_match': bool(total_match) if total_match is not None else None,
                'rows_count': len(parsed_rows),
                'free_count': sum(1 for rr in parsed_rows if rr.get('is_free')),
                'locked_count': sum(1 for rr in parsed_rows if not rr.get('is_free')),
                'free_shares': free_shares,
                'auto_unlocked_pct': round((free_shares / computed_total * 100), 2) if computed_total > 0 else 0,
                'annexure_ii': [],
                'locked_shares': max(computed_total - free_shares, 0),
            }

            shp_common = {
                'promoter_shares': rec.get('promoter_shares'),
                'public_shares': rec.get('public_shares'),
                'other_shares': rec.get('other_shares'),
                'total_shares': rec.get('total_shares'),
                'shp_locked_total': rec.get('shp_locked_total'),
                'sum_valid': None,
                'matched_patterns': {},
                'strategy_results': {},
            }

            results = {
                'pdfplumber': copy.deepcopy(method_res),
                'java': copy.deepcopy(method_res),
                'valid_methods': ['java*'] if parsed_rows else [],
                'best_method': 'java' if parsed_rows else None,
                'can_finalize': False,
                'verification': {
                    'id': rec.get('scrip_id'),
                    'status': rec.get('status'),
                    'locked_forever': rec.get('locked_forever'),
                    'total_match': rec.get('total_match'),
                    'shp_match': rec.get('shp_match'),
                    'mismatches': [],
                    'error': None,
                    'sql_query': 'DB finalized snapshot',
                    'finalized': rec.get('finalized'),
                    'finalized_at': _to_iso_or_none(rec.get('finalized_at')),
                },
                'allotment_date': None,
                'nse_symbol': rec.get('symbol'),
            }
            ipo_data = get_db_ipo_data(nse_symbol=rec.get('symbol'))
            if ipo_data:
                results['allotment_date'] = ipo_data.get('allotment_date')

            shp_results = {'pdfplumber': copy.deepcopy(shp_common), 'java': copy.deepcopy(shp_common)}
            pattern_results = {
                'pdfplumber': {'found_count': 0, 'total_count': len(JAVA_PATTERNS), 'core_matched': 0, 'core_total': len(JAVA_CORE_GROUPS), 'core_all_matched': False},
                'java': {'found_count': 0, 'total_count': len(JAVA_PATTERNS), 'core_matched': 0, 'core_total': len(JAVA_CORE_GROUPS), 'core_all_matched': False},
            }
            shp_sources = {'pdfplumber': None, 'java': None}

            out.append((stem, results, shp_results, pattern_results, shp_sources))

        cur.close()
        return out
    finally:
        conn.close()


def detect_total_row_columns(line: str, total_hint: Optional[int] = None) -> Tuple[List[int], Optional[int], Optional[int], Optional[int]]:
    """
    Detect column indexes from Total row.
    Returns:
      nums, share_col_idx, locked_col_idx, total_value

    Rule:
      - share column is detected from exact total_hint match if available,
        otherwise pick the largest number (shares are largest, investor count is small).
      - locked column is first number after share column where
        0 < value < total_value.
    """
    nums = extract_numbers(line)
    if not nums:
        return [], None, None, None

    share_col_idx: Optional[int] = None
    total_value: Optional[int] = None

    if total_hint is not None:
        for i, n in enumerate(nums):
            if n == total_hint:
                share_col_idx = i
                total_value = n
                break

    # No threshold-based detection - just pick the largest number (likely shares)
    # Investor count, %, and other small numbers will naturally be excluded
    if share_col_idx is None:
        if nums:
            # Pick largest number (most likely to be share count)
            share_col_idx, total_value = max(enumerate(nums), key=lambda x: x[1])

    if share_col_idx is None:
        return nums, None, None, None

    locked_col_idx: Optional[int] = None
    if total_value is not None:
        # Ignore percentage/ratio fields like 100 or 8153 (for 81.53%)
        candidates: List[Tuple[int, int]] = []
        for i in range(share_col_idx + 1, len(nums)):
            v = nums[i]
            if 1000 <= v < total_value:
                candidates.append((i, v))

        if candidates:
            # Prefer realistic locked-share band: 50%..100% of total
            in_band = [(i, v) for i, v in candidates if 0.5 <= (v / total_value) <= 1.0]
            chosen = max(in_band, key=lambda x: x[1]) if in_band else max(candidates, key=lambda x: x[1])
            locked_col_idx = chosen[0]

    return nums, share_col_idx, locked_col_idx, total_value


def pick_value_from_column(line: str, col_idx: Optional[int], total_hint: Optional[int] = None) -> Optional[int]:
    """
    Strict column extraction.
    No derivation from max/min across row.
    """
    if col_idx is None:
        return None
    nums = extract_numbers(line)
    if col_idx >= len(nums):
        return None
    v = nums[col_idx]
    if total_hint is not None and v > total_hint:
        return None
    return v


def find_line_by_patterns(text: str, patterns: List[str]) -> str:
    """Find first line that matches any normalized pattern."""
    for line in text.splitlines():
        nline = normalize_pattern_text(line)
        for p in patterns:
            if p in nline:
                return line.strip()
    return ""


def find_line_and_pattern(text: str, patterns: List[str]) -> Tuple[str, Optional[str]]:
    """Find first line that matches any pattern and return (line, matched_pattern)."""
    for line in text.splitlines():
        nline = normalize_pattern_text(line)
        for p in patterns:
            if p in nline:
                return line.strip(), p
    return "", None


def find_total_line(text: str) -> str:
    """
    Find grand total row for Table I.
    Excludes descriptive rows like 'Total Shareholding of Promoters/Public'.
    """
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if not re.match(r'^total\b', low):
            continue
        if "shareholding of promoters" in low or "public shareholding" in low:
            continue
        if len(extract_numbers(s)) >= 2:
            return s
    return ""


def extract_shp_values_from_text(text: str, annexure_total: Optional[int] = None) -> Dict:
    """
    Extract promoter/public/other/total/locked from SHP extracted text.
    This is Strategy 4 (fallback) - returns result even if partial.
    """
    promoter_line = find_line_by_patterns(text, SHP_PATTERNS_A)
    public_line = find_line_by_patterns(text, SHP_PATTERNS_B)
    other_line = find_line_by_patterns(text, SHP_PATTERNS_C)
    total_line = find_total_line(text)

    share_col_idx = None
    locked_col_idx = None
    total = annexure_total
    locked = None

    if total_line:
        total_nums, share_col_idx, locked_col_idx, detected_total = detect_total_row_columns(total_line, annexure_total)
        if detected_total is not None:
            total = detected_total
        if locked_col_idx is not None and locked_col_idx < len(total_nums):
            locked = total_nums[locked_col_idx]

    promoter = pick_value_from_column(promoter_line, share_col_idx, total) if promoter_line else None
    public = pick_value_from_column(public_line, share_col_idx, total) if public_line else None
    other = pick_value_from_column(other_line, share_col_idx, total) if other_line else None

    # Check which values were found
    promoter_found = promoter is not None
    public_found = public is not None
    other_found = other is not None
    all_values_found = promoter_found and public_found and other_found

    # Validate maths if all values found
    # CRITICAL: Must check against BOTH annexure_total AND total_shares
    # This catches column misalignment from formula references like "(A)(1)+(A)(2)"
    maths_verified = False
    if all_values_found and annexure_total is not None:
        calculated_sum = promoter + public + other
        maths_verified = (calculated_sum == annexure_total)

        # Also verify against total_shares extracted from Total row
        # If they don't match, column indices are misaligned
        if maths_verified and total is not None:
            if calculated_sum != total:
                print(f"  <span class='validation-fail' style='color: #d9534f;'>[STRATEGY 4] Column mismatch: sum={calculated_sum:,} != total_shares={total:,}</span>")
                maths_verified = False

    result = {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": total,
        "shp_locked_total": locked,
        "source_lines": {
            "promoter": promoter_line,
            "public": public_line,
            "other": other_line,
            "total": total_line,
        },
        # Individual found flags
        "promoter_found": promoter_found,
        "public_found": public_found,
        "other_found": other_found,
        "locked_found": locked is not None,
        # Combined validation flags
        "all_values_found": all_values_found,
        "maths_verified": maths_verified,
    }

    if annexure_total is not None and promoter is not None and public is not None:
        calculated_sum = promoter + public + (other or 0)
        result["sum_valid"] = (calculated_sum == annexure_total)
        result["calculated_sum"] = calculated_sum
    else:
        result["sum_valid"] = None
        result["calculated_sum"] = None

    return result


def detect_columns_from_whitespace(line: str) -> Optional[List[Tuple[int, int]]]:
    """
    Detect column boundaries from whitespace gaps in a line.
    Returns list of (start, end) character positions for each column.
    """
    if not line:
        return None

    # Find groups of 2+ spaces that likely indicate column boundaries
    gaps = []
    i = 0
    while i < len(line):
        if line[i] == ' ':
            j = i
            while j < len(line) and line[j] == ' ':
                j += 1
            gap_size = j - i
            if gap_size >= 2:  # Column boundary threshold
                gaps.append((i, j))
            i = j
        else:
            i += 1

    if not gaps:
        return None

    # Build column ranges from gaps
    columns = []
    start = 0
    for gap_start, gap_end in gaps:
        if gap_start > start:
            columns.append((start, gap_start))
        start = gap_end

    # Last column
    if start < len(line):
        columns.append((start, len(line)))

    return columns if len(columns) >= 2 else None


def extract_number_from_range(line: str, start: int, end: int, max_value: Optional[int] = None) -> Optional[int]:
    """
    Extract the first/best number from a character range in a line.
    """
    if not line or start >= len(line):
        return None

    end = min(end, len(line))
    segment = line[start:end]
    nums = extract_numbers(segment)

    if not nums:
        return None

    # Filter by max_value if provided
    if max_value is not None:
        valid = [n for n in nums if n <= max_value]
        if not valid:
            return None
        nums = valid

    # Return the largest reasonable number
    return max(nums)


def extract_using_spatial_columns(
    promoter_line: str,
    public_line: str,
    other_line: str,
    total_line: str,
    columns: List[Tuple[int, int]],
    annexure_total: Optional[int],
    lockin_locked_hint: Optional[int] = None
) -> Optional[Dict]:
    """
    Extract values using detected spatial column positions.
    
    Returns None if ANY value is missing (promoter, public, or other).
    """
    if not total_line or not columns or len(columns) < 2:
        return None

    # SIMPLE APPROACH: Use total line as reference to find column position
    # 1. Extract all numbers from total line
    # 2. Find which position contains the known total (annexure_total)
    # 3. Use that same position for promoter/public/other

    total_nums = extract_numbers(total_line)
    if not total_nums:
        return None

    # Find which position in total_line has the total_shares value
    share_position = None
    detected_total = None
    total_verified = False

    if annexure_total:
        # Find position where total EXACTLY matches annexure_total (text extraction, not estimation)
        for i, num in enumerate(total_nums):
            if num == annexure_total:
                share_position = i
                detected_total = num
                total_verified = True
                break

    # Fallback: use largest number as total (but mark as not verified)
    if share_position is None and total_nums:
        share_position = total_nums.index(max(total_nums))
        detected_total = total_nums[share_position]
        total_verified = False

    if share_position is None:
        return None

    # Extract from same position in other lines
    promoter = None
    public = None
    other = None

    if promoter_line:
        prom_nums = extract_numbers(promoter_line)
        promoter = prom_nums[share_position] if share_position < len(prom_nums) else None

    if public_line:
        pub_nums = extract_numbers(public_line)
        public = pub_nums[share_position] if share_position < len(pub_nums) else None

    if other_line:
        oth_nums = extract_numbers(other_line)
        other = oth_nums[share_position] if share_position < len(oth_nums) else None

    # CRITICAL FIX: Return None if ANY value is missing
    if promoter is None or public is None or other is None:
        return None  # Incomplete extraction - let next strategy try

    # Look for EXACT lock-in derived locked shares in SHP total row
    # Must be in the SAME line as total (not just anywhere in text)
    locked = None
    locked_verified = False

    if lockin_locked_hint:
        # Search for EXACT number match in total line ONLY
        print(f"  [DEBUG] Looking for locked hint: {lockin_locked_hint}")
        print(f"  [DEBUG] Total numbers: {total_nums}")
        if lockin_locked_hint in total_nums:
            locked = lockin_locked_hint
            locked_verified = True
            print(f"  [DEBUG] OK Found locked: {locked}")
        else:
            print(f"  [DEBUG] XX Locked hint NOT found in total_nums")

    # Validate maths: promoter + public + other MUST equal total
    calculated_sum = promoter + public + other
    maths_verified = (calculated_sum == detected_total)

    # If maths doesn't verify, return None to try next strategy
    if not maths_verified:
        return None

    result = {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": detected_total,
        "total_verified": total_verified and maths_verified,
        "shp_locked_total": locked,
        "shp_locked_verified": locked_verified,
        # Individual found flags
        "promoter_found": True,
        "public_found": True,
        "other_found": True,
        "locked_found": locked is not None,
        # Combined validation flags
        "all_values_found": True,  # We already checked above
        "maths_verified": maths_verified,
        "sum_valid": maths_verified,  # Alias for HTML compatibility
        "source_lines": {
            "promoter": promoter_line,
            "public": public_line,
            "other": other_line,
            "total": total_line,
        },
    }

    return result


def extract_using_fixed_positions(
    promoter_line: str,
    public_line: str,
    other_line: str,
    total_line: str,
    annexure_total: Optional[int],
    lockin_locked_hint: Optional[int] = None
) -> Optional[Dict]:
    """
    Extract values using fixed character position ranges.
    Tries common table layouts.
    
    Returns None if ANY value is missing (promoter, public, or other).
    """
    # Common column layouts to try:
    # Format: [Description] [Num Investors] [Shares] [%] [Locked]
    # We want to extract from Shares column (skip investor count)

    layouts = [
        # Layout 1: With investor column - Desc(0-40), Inv(40-50), Shares(50-70), %(70-85), Locked(85-110)
        [(0, 40), (40, 50), (50, 70), (70, 85), (85, 110)],
        # Layout 2: Without investor column - Desc(0-50), Shares(50-70), %(70-85), Locked(85-110)
        [(0, 50), (50, 70), (70, 85), (85, 110)],
        # Layout 3: With investor column - Desc(0-35), Inv(35-45), Shares(45-65), %(65-80), Locked(80-100)
        [(0, 35), (35, 45), (45, 65), (65, 80), (80, 100)],
        # Layout 4: Without investor column - Desc(0-40), Shares(40-65), %(65-80), Locked(80-100)
        [(0, 40), (40, 65), (65, 80), (80, 100)],
        # Layout 5: With investor column - Desc(0-45), Inv(45-55), Shares(55-85), %(85-95), Locked(95-120)
        [(0, 45), (45, 55), (55, 85), (85, 95), (95, 120)],
        # Layout 6: Without investor column - Desc(0-60), Shares(60-85), %(85-95), Locked(95-120)
        [(0, 60), (60, 85), (85, 95), (95, 120)],
    ]

    for layout in layouts:
        if len(layout) < 2:
            continue

        # Detect layout type: 4-column (no investor) or 5-column (with investor)
        # 5-column: [Desc, Investor, Shares, %, Locked]
        # 4-column: [Desc, Shares, %, Locked]
        if len(layout) >= 5:
            # Has investor column - shares at index 2, locked at index 4
            share_range = layout[2]
            locked_range = layout[4] if len(layout) > 4 else None
        else:
            # No investor column - shares at index 1, locked at index 3
            share_range = layout[1] if len(layout) > 1 else None
            locked_range = layout[3] if len(layout) > 3 else None

        if not share_range:
            continue

        detected_total = extract_number_from_range(total_line, share_range[0], share_range[1]) if total_line else None

        if not detected_total:
            continue

        # Extract values from all lines using this column range
        promoter = extract_number_from_range(promoter_line, share_range[0], share_range[1], detected_total) if promoter_line else None
        public = extract_number_from_range(public_line, share_range[0], share_range[1], detected_total) if public_line else None
        other = extract_number_from_range(other_line, share_range[0], share_range[1], detected_total) if other_line else None

        # CRITICAL: Skip this layout if ANY value is missing
        if promoter is None or public is None or other is None:
            continue  # Try next layout

        # Extract locked shares - must be in same line as total
        locked = None
        locked_verified = False
        if locked_range and total_line:
            locked_candidate = extract_number_from_range(total_line, locked_range[0], locked_range[1])
            if lockin_locked_hint is not None:
                # Only accept if it matches the hint (exact match for verification)
                if locked_candidate == lockin_locked_hint:
                    locked = locked_candidate
                    locked_verified = True
            else:
                # No hint provided, use what we extracted
                locked = locked_candidate

        # Validate maths: promoter + public + other MUST equal detected_total
        calc_sum = promoter + public + other
        maths_verified = (calc_sum == detected_total)

        if not maths_verified:
            continue  # Try next layout

        # Valid layout found! Return with validation flags
        result = {
            "promoter_shares": promoter,
            "public_shares": public,
            "other_shares": other,
            "total_shares": detected_total,
            "shp_locked_total": locked,
            "shp_locked_verified": locked_verified,
            # Individual found flags
            "promoter_found": True,
            "public_found": True,
            "other_found": True,
            "locked_found": locked is not None,
            # Combined validation flags
            "all_values_found": True,
            "maths_verified": maths_verified,
            "sum_valid": maths_verified,  # Alias for HTML compatibility
            "source_lines": {
                "promoter": promoter_line,
                "public": public_line,
                "other": other_line,
                "total": total_line,
            },
        }

        return result

    # No valid layout found
    return None


def extract_shp_using_simple_position(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 5: Pure position-based extraction (FINAL FALLBACK - Requires hints).

    PURELY NUMBER-BASED - ZERO PATTERN MATCHING!

    Algorithm:
    1. Find Total row by known_total (and optionally known_locked)
    2. Look backwards, collect lines with 3+ numbers and at least one large number (>1000)
    3. Extract by POSITION from same column:
       - Data row 0 = Promoter
       - Data row 1 = Public
       - Data row 2 = Other (or 0 if only 2 rows)
    4. Validate: promoter + public + other == known_total

    NO text patterns, NO keywords - pure numbers only!
    REQUIRES known_total to work.
    """
    if not known_total:
        return None

    lines = text.splitlines()
    total_row_idx = None
    total_line = None

    # Step 1: Find Total row by number matching ONLY
    for i, line in enumerate(lines):
        nums = extract_numbers(line)
        if known_total in nums:
            # If we have known_locked, verify it's also present on same line
            if known_locked is not None:
                if known_locked in nums:
                    total_row_idx = i
                    total_line = line
                    break
            else:
                # No locked hint, just use total match
                total_row_idx = i
                total_line = line
                break

    if total_row_idx is None:
        print(f"    [SIMPLE POSITION-BASED] Could not find Total row")
        return None

    print(f"    [SIMPLE POSITION-BASED] Found Total row at line {total_row_idx}, total={known_total:,}")

    # Step 2: Find data lines above Total (pure number-based, NO patterns)
    # Collect up to 10 lines with 3+ numbers and at least one large number (>1000)
    data_rows = []
    for i in range(total_row_idx - 1, max(0, total_row_idx - 20), -1):
        line = lines[i]

        # Skip empty lines
        if not line.strip():
            continue

        # Extract numbers
        nums = extract_numbers(line)

        # Data row criteria (PURE number-based):
        # 1. Has at least 3 numbers
        # THRESHOLD REMOVED: No thresholds allowed in this project
        # Old code with threshold (commented out):
        # 2. Has at least one large number (>2100) for share data
        #    (filters out dates like 19/06/2025 where year=2025 < 10000)
        # if len(nums) >= 3:
        #     has_large_number = any(n > 2100 for n in nums)
        #     if has_large_number:
        # New code: Accept all rows with 3+ numbers
        if len(nums) >= 3:
            data_rows.append({
                'index': i,
                'line': line.strip(),
                'numbers': nums
            })

        # Stop when we have 10 data rows
        if len(data_rows) >= 10:
            break
    
    # Reverse to get top-to-bottom order
    data_rows.reverse()

    print(f"    [SIMPLE POSITION-BASED] Collected {len(data_rows)} data rows")
    for idx, row in enumerate(data_rows[:5]):  # Show first 5
        print(f"      Row {idx} (line {row['index']}): {row['line'][:80]}...")
        print(f"             Numbers: {row['numbers'][:10]}...")

    if len(data_rows) < 2:
        # Need at least 2 data rows (Promoter, Public; Other can be 0)
        print(f"    [SIMPLE POSITION-BASED] Not enough data rows (need 2+, got {len(data_rows)})")
        return None

    # Step 3: Find which position in Total row contains known_total
    total_nums = extract_numbers(total_line)
    share_position = None

    # Find position where total appears (exact match)
    for i, num in enumerate(total_nums):
        if num == known_total:
            share_position = i
            break

    if share_position is None:
        print(f"    [SIMPLE POSITION-BASED] Could not find known_total={known_total} in total_nums")
        return None

    print(f"    [SIMPLE POSITION-BASED] Share position: {share_position}")

    # Step 4: Extract from SAME POSITION in data rows
    # Row 0 = Promoter
    promoter_row = data_rows[0]
    promoter_nums = promoter_row['numbers']
    promoter = promoter_nums[share_position] if share_position < len(promoter_nums) else None

    # Row 1 = Public
    public_row = data_rows[1]
    public_nums = public_row['numbers']
    public = public_nums[share_position] if share_position < len(public_nums) else None

    # Row 2 = Other (if exists, else 0)
    if len(data_rows) >= 3:
        other_row = data_rows[2]
        other_nums = other_row['numbers']
        other = other_nums[share_position] if share_position < len(other_nums) else None
    else:
        # Only 2 data rows - no separate Other category
        other = 0

    print(f"    [SIMPLE POSITION-BASED] Extracted: promoter={promoter}, public={public}, other={other}")

    # Validate: promoter + public + other should equal known_total
    if promoter and public:
        calc_sum = promoter + public + (other or 0)
        sum_valid = (calc_sum == known_total)

        print(f"    [SIMPLE POSITION-BASED] Validation: {promoter:,} + {public:,} + {other or 0:,} = {calc_sum:,}, expected={known_total:,}, valid={sum_valid}")

        if not sum_valid:
            print(f"    [SIMPLE POSITION-BASED] Validation failed!")
            return None
    else:
        print(f"    [SIMPLE POSITION-BASED] Missing promoter or public!")
        return None

    # Extract locked from Total line (must be on same line)
    locked = None
    locked_verified = False
    if known_locked is not None and known_locked in total_nums:
        locked = known_locked
        locked_verified = True

    result = {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": known_total,
        "total_verified": True,
        "shp_locked_total": locked,
        "shp_locked_verified": locked_verified,
        # Individual found flags
        "promoter_found": True,
        "public_found": True,
        "other_found": other is not None and other != 0,  # False if only 2 rows (other=0)
        "locked_found": locked is not None,
        # Combined validation flags
        "all_values_found": True,
        "maths_verified": True,  # We already validated above
        "sum_valid": True,  # Alias for HTML compatibility
        "source_lines": {
            "promoter": promoter_row['line'],
            "public": public_row['line'],
            "other": other_row['line'] if len(data_rows) >= 3 else "",
            "total": total_line,
        },
        "extraction_method": "simple_position"
    }

    return result


def extract_shp_using_boundary_detection(
    text: str,
    annexure_total: Optional[int],      # DB total - ORIGINAL (try first)
    lockin_locked_hint: Optional[int] = None,
    total_hint_computed: Optional[int] = None  # [FALLBACK 2026-03-09] Computed total - safe to remove if issues
) -> Optional[Dict]:
    """
    Strategy 6: Boundary-detection position-based extraction.

    Goes UP from Total row until hitting data section boundary.
    More elegant than Strategy 5 - detects boundaries dynamically instead of fixed window.

    Algorithm:
    1. Find Total row containing annexure_total (DB total - try first)
    2. If not found, try total_hint_computed (computed total - fallback) [2026-03-09]
    3. Go UP line by line from Total
    4. Check if line is data: 3+ numbers AND (>10,000 OR max ≤100)
    5. If data: collect it, reset consecutive_non_data counter
    
    [FALLBACK 2026-03-09] If you need to rollback: remove total_hint_computed parameter and fallback loop
    5. If non-data: increment consecutive_non_data
    6. Stop if consecutive_non_data >= 3 (hit boundary - headers/dates section)
    7. Extract values from same column position as known_total

    Current Boundary Detection Logic:
    - Data row: has 3+ numbers AND (has number >10,000 OR max ≤100)
    - Non-data: has <3 numbers OR (has 3+ numbers but max in range 100-10,000)
    - Boundary: 3 consecutive non-data lines

    This filters:
    ✓ Collects share rows: [promoter, public with values >10,000]
    ✓ Collects zero rows: [0, 0, 0, ...] or [2, 0, 0, ...] (max ≤100)
    ✗ Filters dates: [19, 6, 2025] (max=2025, not >10k, not ≤100)
    ✗ Filters headers: "Category Shareholder" (< 3 numbers)

    TODO - Future Enhancements (next 3-4 days):
    ──────────────────────────────────────────────────────────────
    1. Pattern-based header detection:
       - Look for keywords: "Category", "Shareholder", "As On", "Date"
       - Stop immediately when header pattern detected (more accurate than 3 consecutive)

    2. Smarter zero-row detection:
       - Current: max ≤100 (crude but works)
       - Better: Check if most values are 0 (e.g., 80% zeros)
       - Handle edge case: percentage rows might have values like [45, 67, 12]

    3. Table structure detection:
       - Detect column alignment / table boundaries
       - Use whitespace/separator patterns
       - More robust than just counting numbers

    4. Configurable boundary threshold:
       - Current: hardcoded 3 consecutive non-data lines
       - Make configurable: boundary_threshold parameter
       - Different docs might need 2 or 4 consecutive

    5. Bi-directional validation:
       - Go UP to find data, but also check DOWN from Total
       - Validate that we didn't stop too early
       - Cross-check with table structure below Total

    6. Debug mode / visualization:
       - Add optional debug parameter to show boundary detection process
       - Log: line → is_data → consecutive_count → decision
       - Helps tune boundary detection for edge cases

    Args:
        text: SHP text content
        annexure_total: DB total shares (try first - original)
        lockin_locked_hint: Known locked shares (optional)
        total_hint_computed: Computed total shares (fallback) [2026-03-09]

    Returns:
        Dict with extracted values or None if extraction fails
        
    [FALLBACK 2026-03-09] Rollback: Remove total_hint_computed param and fallback loop below
    """
    # [FALLBACK 2026-03-09] Need at least one hint
    if not annexure_total and not total_hint_computed:
        return None

    lines = text.splitlines()

    # Step 1: Find Total row
    # ORIGINAL: Try annexure_total (DB total) first
    total_row_idx = None
    total_line = None
    found_total = None  # Track which total was actually found [FALLBACK 2026-03-09]

    if annexure_total:
        for i, line in enumerate(lines):
            nums = extract_numbers(line)
            if annexure_total in nums:
                total_row_idx = i
                total_line = line
                found_total = annexure_total  # [FALLBACK 2026-03-09]
                break

    # [FALLBACK 2026-03-09] If annexure_total not found, try total_hint_computed
    if total_row_idx is None and total_hint_computed:
        for i, line in enumerate(lines):
            nums = extract_numbers(line)
            if total_hint_computed in nums:
                total_row_idx = i
                total_line = line
                found_total = total_hint_computed  # [FALLBACK 2026-03-09]
                break

    if total_row_idx is None:
        return None

    # Step 2: Go UP from Total, collecting data rows until boundary
    # ═══════════════════════════════════════════════════════════════════
    # BOUNDARY DETECTION LOGIC - Enhance here over next 3-4 days
    # ═══════════════════════════════════════════════════════════════════
    data_rows = []
    consecutive_non_data = 0
    max_rows = 10  # Safety limit

    # TODO: Make configurable for future enhancements
    boundary_threshold = 3  # Stop after N consecutive non-data lines

    # TODO: Add pattern-based header detection (see docstring for ideas)
    # header_patterns = ['category', 'shareholder', 'as on', 'date']

    for i in range(total_row_idx - 1, -1, -1):
        line = lines[i]

        # TODO: Add header pattern check here (future enhancement)
        # if any(pattern in line.lower() for pattern in header_patterns):
        #     break  # Hit header boundary immediately

        if not line.strip():
            consecutive_non_data += 1
            if consecutive_non_data >= boundary_threshold:
                break  # Hit boundary
            continue

        nums = extract_numbers(line)

        # ───────────────────────────────────────────────────────────────
        # Data row detection criteria (not thresholds - pattern detection):
        # ───────────────────────────────────────────────────────────────
        # Share data characteristics:
        # - Has 3+ numbers (eliminates headers like "Category")
        # - Contains share counts (typically >10,000) OR all-zero rows (max ≤100)
        # - Excludes dates ([19, 6, 2025]), percentages, and other metadata
        # ───────────────────────────────────────────────────────────────
        has_enough_numbers = len(nums) >= 3

        if has_enough_numbers:
            # Check if row contains share data (not dates or other metadata)
            # Share data pattern: large numbers (share counts) or all-zeros
            has_share_count = any(n > 10000 for n in nums)  # Typical share count magnitude
            is_zero_row = max(nums) <= 100 if nums else False  # Zero/small category markers

            if has_share_count or is_zero_row:
                # This is likely a data row (not a date like [19, 6, 2025])
                data_rows.append({
                    'index': i,
                    'line': line.strip(),
                    'numbers': nums
                })
                consecutive_non_data = 0  # Reset counter
            else:
                # Has numbers but not share data pattern (likely date/metadata)
                consecutive_non_data += 1
                if consecutive_non_data >= boundary_threshold:
                    break  # Hit boundary
        else:
            # Has <3 numbers (likely header or separator)
            consecutive_non_data += 1
            if consecutive_non_data >= 3:
                break  # Hit boundary

        if len(data_rows) >= max_rows:
            break  # Safety limit

    # Reverse to get top-to-bottom order
    data_rows.reverse()

    if len(data_rows) < 2:
        return None

    # Step 3: Find share position in Total row
    total_nums = extract_numbers(total_line)
    share_position = None

    # [FALLBACK 2026-03-09] Use found_total (could be annexure_total or total_hint_computed)
    for i, num in enumerate(total_nums):
        if num == found_total:
            share_position = i
            break

    if share_position is None:
        return None

    # Step 4: Extract from same position in data rows
    # Row 0 = Promoter, Row 1 = Public, Row 2+ = Other (if exists)
    promoter_row = data_rows[0]
    promoter_nums = promoter_row['numbers']
    promoter = promoter_nums[share_position] if share_position < len(promoter_nums) else None

    public_row = data_rows[1]
    public_nums = public_row['numbers']
    public = public_nums[share_position] if share_position < len(public_nums) else None

    # Handle Other (optional)
    other = None
    if len(data_rows) >= 3:
        other_row = data_rows[2]
        other_nums = other_row['numbers']
        other = other_nums[share_position] if share_position < len(other_nums) else None
    else:
        # Only 2 rows: assume other = 0
        other = 0

    if promoter is None or public is None:
        return None

    # Step 5: Validation
    calc_sum = promoter + public + (other or 0)
    sum_valid = (calc_sum == found_total)  # [FALLBACK 2026-03-09]

    if not sum_valid:
        return None

    # Extract locked value from Total row
    locked = None
    locked_verified = False
    # [FALLBACK 2026-03-09] Use lockin_locked_hint (parameter name)
    if lockin_locked_hint and lockin_locked_hint in total_nums:
        locked = lockin_locked_hint
        locked_verified = True

    result = {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": found_total,  # [FALLBACK 2026-03-09] Use found_total
        "total_verified": True,
        "shp_locked_total": locked,
        "shp_locked_verified": locked_verified,
        # Individual found flags
        "promoter_found": promoter is not None,
        "public_found": public is not None,
        "other_found": other is not None and other != 0,
        "locked_found": locked is not None,
        # Combined validation flags
        "all_values_found": (promoter is not None and public is not None and other is not None and locked is not None),
        "maths_verified": sum_valid,  # We already validated above
        "sum_valid": sum_valid,  # Alias for HTML compatibility
        "locked_verified": locked_verified,
        "strategy_used": "boundary_detection",
        "source_lines": {
            "promoter": promoter_row['line'],
            "public": public_row['line'],
            "other": data_rows[2]['line'] if len(data_rows) >= 3 else "",
            "total": total_line,
        },
        "extraction_method": "boundary_detection"
    }

    return result


def extract_shp_with_column_count_validation(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 7: Column count validation with math verification.

    PURE NUMBER-BASED - filters rows by column count, then validates math.

    Algorithm:
    1. Find Total row by known_total
    2. Count columns in Total row (number of extracted values)
    3. Scan UP, collect rows with similar column count (≥ total_cols - 5)
    4. Extract values from same position as Total
    5. VALIDATE: promoter + public + other == known_total

    This filters out:
    - Headers (too few columns: 2-4 vs ~30)
    - OCR garbage lines
    - Formula reference artifacts

    Args:
        text: SHP text content
        known_total: Known total shares from database
        known_locked: Optional locked shares for additional validation

    Returns:
        Dict with extracted values or None if extraction/validation fails
    """
    if not known_total:
        return None

    lines = text.splitlines()
    total_row_idx = None
    total_line = None

    # Step 1: Find Total row
    for i, line in enumerate(lines):
        nums = extract_numbers(line)
        if known_total in nums:
            if known_locked is not None:
                if known_locked in nums:
                    total_row_idx = i
                    total_line = line
                    break
            else:
                total_row_idx = i
                total_line = line
                break

    if total_row_idx is None:
        return None

    # Step 2: Count columns in Total row
    total_nums = extract_numbers(total_line)
    total_column_count = len(total_nums)
    min_columns = total_column_count - 5  # Allow ±5 tolerance

    # Find share position in Total row
    share_position = None
    for i, num in enumerate(total_nums):
        if num == known_total:
            share_position = i
            break

    if share_position is None:
        return None

    # Step 3: Scan UP from Total, collect rows with similar column count
    data_rows = []
    consecutive_non_data = 0
    boundary_threshold = 3
    max_rows = 10

    for i in range(total_row_idx - 1, -1, -1):
        line = lines[i]

        if not line.strip():
            consecutive_non_data += 1
            if consecutive_non_data >= boundary_threshold:
                break
            continue

        nums = extract_numbers(line)

        # Column count filter: accept rows with similar column count
        if len(nums) >= min_columns:
            data_rows.append({
                'index': i,
                'line': line.strip(),
                'numbers': nums
            })
            consecutive_non_data = 0
        else:
            # Too few columns - likely header or garbage
            consecutive_non_data += 1
            if consecutive_non_data >= boundary_threshold:
                break

        if len(data_rows) >= max_rows:
            break

    # Reverse to get top-to-bottom order
    data_rows.reverse()

    if len(data_rows) < 2:
        return None

    # Step 4: Extract from same position
    promoter_row = data_rows[0]
    promoter_nums = promoter_row['numbers']
    promoter = promoter_nums[share_position] if share_position < len(promoter_nums) else None

    public_row = data_rows[1]
    public_nums = public_row['numbers']
    public = public_nums[share_position] if share_position < len(public_nums) else None

    # Handle Other (optional)
    other = None
    if len(data_rows) >= 3:
        other_row = data_rows[2]
        other_nums = other_row['numbers']
        other = other_nums[share_position] if share_position < len(other_nums) else None
    else:
        other = 0

    if promoter is None or public is None:
        return None

    # Step 5: CRITICAL VALIDATION - Math check
    calc_sum = promoter + public + (other or 0)
    sum_valid = (calc_sum == known_total)

    if not sum_valid:
        # Math doesn't match - wrong column indices or wrong rows
        return None

    # Extract locked value from Total row
    locked = None
    locked_verified = False
    if known_locked and known_locked in total_nums:
        locked = known_locked
        locked_verified = True

    result = {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": known_total,
        "total_verified": True,
        "shp_locked_total": locked,
        "shp_locked_verified": locked_verified,
        # Individual found flags
        "promoter_found": promoter is not None,
        "public_found": public is not None,
        "other_found": other is not None and other != 0,
        "locked_found": locked is not None,
        # Combined validation flags
        "all_values_found": (promoter is not None and public is not None and other is not None and locked is not None),
        "maths_verified": sum_valid,
        "sum_valid": sum_valid,
        "locked_verified": locked_verified,
        "strategy_used": "column_count_validation",
        "source_lines": {
            "promoter": promoter_row['line'],
            "public": public_row['line'],
            "other": data_rows[2]['line'] if len(data_rows) >= 3 else "",
            "total": total_line,
        },
        "extraction_method": "column_count_validation",
        "column_count_info": {
            "total_columns": total_column_count,
            "min_required": min_columns,
            "rows_collected": len(data_rows)
        }
    }

    return result


def extract_shp_using_position_from_total(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """
    Deterministic SHP extraction using position-based approach.

    Strategy:
    1. Find Total row that contains both known_total and known_locked values
    2. Look ABOVE Total row and find all data rows (rows with numbers)
    3. First data row = Promoter shares
    4. Second data row = Public shares
    5. Line just above Total (last data row) = Non-promoter/Other shares

    This eliminates the need for pattern matching and works for both Java and pdfplumber.
    Used as fallback when pattern-based methods fail.
    """
    if not known_total:
        return None

    lines = text.splitlines()
    total_row_idx = None
    total_line = None

    # Step 1: Find the Total row containing known values
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if 'total' in line_lower:
            nums = extract_numbers(line)
            # Must contain the known_total
            if known_total in nums:
                # If we have known_locked, verify it's also present
                if known_locked is not None:
                    if known_locked in nums:
                        total_row_idx = i
                        total_line = line
                        break
                else:
                    total_row_idx = i
                    total_line = line
                    break

    if total_row_idx is None:
        return None

    print(f"    [POSITION-FALLBACK] Found Total row at line {total_row_idx}")

    # Step 2: Find all data rows above Total (working backwards)
    data_rows = []
    for i in range(total_row_idx - 1, -1, -1):
        line = lines[i]

        # Skip empty or whitespace-only lines
        if not line.strip():
            continue

        nums = extract_numbers(line)

        # Data row must have at least 2 numbers (investor count + shares)
        if len(nums) >= 2:
            # Skip header rows
            line_lower = line.lower()
            if 'shareholding' in line_lower or 'equity' in line_lower or 'no.' in line_lower:
                continue

            data_rows.append({
                'index': i,
                'line': line.strip(),
                'numbers': nums
            })

    # Reverse to get top-to-bottom order
    data_rows.reverse()

    print(f"    [POSITION-FALLBACK] Found {len(data_rows)} data rows above Total")

    if len(data_rows) < 2:
        print(f"    [POSITION-FALLBACK] Not enough data rows (need at least 2)")
        return None

    # Step 3: Find which position in Total row contains known_total
    total_nums = extract_numbers(total_line)
    share_position = None

    print(f"    [POSITION-FALLBACK] Total row numbers: {total_nums}")

    # Find position where total appears (exact match)
    for i, num in enumerate(total_nums):
        if num == known_total:
            share_position = i
            print(f"    [POSITION-FALLBACK] Found known_total={known_total} at position {i}")
            break

    if share_position is None:
        print(f"    [POSITION-FALLBACK] Could not find known_total={known_total} in Total row")
        return None

    # Step 4: Extract values from SAME POSITION in each data row
    # First data row = Promoter
    promoter_row = data_rows[0]
    promoter_line = promoter_row['line']
    promoter_nums = promoter_row['numbers']
    promoter = promoter_nums[share_position] if share_position < len(promoter_nums) else None

    # Second data row = Public
    public_row = data_rows[1] if len(data_rows) > 1 else None
    public_line = public_row['line'] if public_row else ""
    public_nums = public_row['numbers'] if public_row else []
    public = public_nums[share_position] if public_row and share_position < len(public_nums) else None

    # Last data row before Total = Other/Non-promoter
    other_row = data_rows[-1] if len(data_rows) > 2 else None
    other_line = other_row['line'] if other_row else ""
    other_nums = other_row['numbers'] if other_row else []
    other = other_nums[share_position] if other_row and share_position < len(other_nums) else None

    # If there are only 2 data rows (A and B), then C = 0
    if len(data_rows) == 2:
        other = 0

    print(f"    [POSITION-FALLBACK] Extracted from position {share_position}: promoter={promoter}, public={public}, other={other}")

    # Validate: promoter + public + other should equal known_total
    if promoter and public:
        calc_sum = promoter + public + (other or 0)
        sum_valid = (calc_sum == known_total)

        if not sum_valid:
            print(f"    [POSITION-FALLBACK] Validation failed: {calc_sum} != {known_total}")
            return None
    else:
        sum_valid = None
        calc_sum = None

    print(f"    [POSITION-FALLBACK] OK Validation passed")

    result = {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": known_total,
        "total_verified": True,
        "shp_locked_total": known_locked,
        "shp_locked_verified": known_locked is not None,
        "source_lines": {
            "promoter": promoter_line,
            "public": public_line,
            "other": other_line,
            "total": total_line,
        },
        "sum_valid": sum_valid,
        "calculated_sum": calc_sum,
        "extraction_method": "position_from_total"
    }

    return result


def extract_shp_values_from_text_java(
    text: str, 
    annexure_total: Optional[int] = None, 
    lockin_locked_hint: Optional[int] = None,
    total_hint_computed: Optional[int] = None  # [FALLBACK 2026-03-09] Computed total - safe to remove if issues
) -> Dict:
    """
    Extract SHP values from Java-extracted text using spatial/column-based approach.
    This is a fallback when pdfplumber's sequential approach fails.

    VERSION: 2.2 (2026-03-02) - Column count validation strategy

    Hybrid approach (tries in order):
    1. Detect columns from whitespace gaps (flexible, pattern-based)
    2. Fall back to fixed character positions (pattern-based)
    3. Deterministic position-based (uses known total/locked to find rows by position)
    4. Sequential number extraction (pattern-based)
    6. Boundary detection (scans UP from Total until boundary)
    7. Column count validation (NEW: filters by column count, validates by math)
    5. Simple position-based (FINAL FALLBACK - pure numbers, no validation)

    Returns result dict with validation flags. Strategies 1-3 return None if incomplete,
    forcing cascade to next strategy. Strategy 4+ always returns (even if partial).
    """
    print("<span class='shp-version' style='color: #666; font-size: 0.9em;'>[SHP Extraction v2.2]</span>")

    # Track which strategy succeeded
    strategy_results = {
        "spatial_columns": False,
        "fixed_positions": False,
        "position_based": False,
        "sequential": False,
        "boundary_detection": False,
        "column_count_validation": False,
        "simple_position": False,
    }
    
    # Find lines using pattern matching and track which patterns matched
    promoter_line, promoter_pattern = find_line_and_pattern(text, SHP_PATTERNS_A)
    public_line, public_pattern = find_line_and_pattern(text, SHP_PATTERNS_B)
    other_line, other_pattern = find_line_and_pattern(text, SHP_PATTERNS_C)
    total_line = find_total_line(text)

    # Strategy 1: Detect columns from whitespace gaps
    columns = detect_columns_from_whitespace(total_line) if total_line else None
    if columns:
        result = extract_using_spatial_columns(
            promoter_line, public_line, other_line, total_line,
            columns, annexure_total, lockin_locked_hint
        )
        if result and result.get('total_verified'):  # Must be FULLY verified
            strategy_results["spatial_columns"] = True
            # Add matched patterns to result
            result["matched_patterns"] = {
                "promoter": promoter_pattern,
                "public": public_pattern,
                "other": other_pattern
            }
            result["strategy_used"] = "spatial_columns"
            result["strategy_results"] = strategy_results
            return result

    # Strategy 2: Try fixed character positions
    result = extract_using_fixed_positions(
        promoter_line, public_line, other_line, total_line,
        annexure_total, lockin_locked_hint
    )
    if result and result.get('total_verified'):  # Must be FULLY verified
        strategy_results["fixed_positions"] = True
        # Add matched patterns to result
        result["matched_patterns"] = {
            "promoter": promoter_pattern,
            "public": public_pattern,
            "other": other_pattern
        }
        result["strategy_used"] = "fixed_positions"
        result["strategy_results"] = strategy_results
        return result

    # Strategy 3: Try deterministic position-based approach (NEW FALLBACK)
    # This uses known total and locked from lock-in to find Total row,
    # then works backwards to find promoter/public/other by position
    if annexure_total:
        print(f"  [TRYING POSITION-BASED FALLBACK]")
        result = extract_shp_using_position_from_total(text, annexure_total, lockin_locked_hint)
        if result and result.get('total_verified'):  # Must be FULLY verified
            strategy_results["position_based"] = True
            # Add matched patterns (will be None since we didn't use patterns)
            result["matched_patterns"] = {
                "promoter": None,
                "public": None,
                "other": None
            }
            result["strategy_used"] = "position_based"
            result["strategy_results"] = strategy_results
            print(f"  [POSITION-BASED FALLBACK] OK Success")
            return result
        else:
            print(f"  [POSITION-BASED FALLBACK] Failed")

    # Strategy 4: Sequential fallback (pattern-based)
    # This always returns (even if partial) - maintains backward compatibility
    result = extract_shp_values_from_text(text, annexure_total)
    
    # Check if Strategy 4 returned complete data
    if result:
        all_found = result.get('all_values_found', False)
        maths_ok = result.get('maths_verified', False)

        # CRITICAL VALIDATION: Check if promoter + public + other = total_shares
        # This catches column misalignment bugs from formula references like "(A)(1)+(A)(2)"
        total_verified = False
        if all_found and result.get('total_shares'):
            promoter = result.get('promoter_shares') or 0
            public = result.get('public_shares') or 0
            other = result.get('other_shares') or 0
            total = result.get('total_shares')
            calculated_total = promoter + public + other

            if calculated_total == total:
                total_verified = True
            else:
                print(f"  <span class='validation-reject' style='color: #d9534f; font-weight: bold;'>[STRATEGY 4] REJECT: promoter+public+other={calculated_total:,} != total_shares={total:,}</span>")
                print(f"    <span style='color: #999;'>(promoter={promoter:,}, public={public:,}, other={other:,})</span>")

        # If complete AND totals match, return it (backward compatible)
        if all_found and maths_ok and total_verified:
            strategy_results["sequential"] = True
            result["matched_patterns"] = {
                "promoter": promoter_pattern,
                "public": public_pattern,
                "other": other_pattern
            }
            result["strategy_used"] = "sequential"
            result["strategy_results"] = strategy_results
            return result
        
        # If incomplete, try Strategy 5 as improvement
        # But keep Strategy 4 result as fallback if Strategy 5 fails
        strategy4_result = result
        strategy4_result["matched_patterns"] = {
            "promoter": promoter_pattern,
            "public": public_pattern,
            "other": other_pattern
        }
        strategy4_result["strategy_used"] = "sequential"
        strategy4_result["strategy_results"] = strategy_results
    else:
        strategy4_result = None

    # Strategy 6: Boundary-detection position-based (requires hints)
    # More elegant than Strategy 5 - detects boundaries dynamically
    # [FALLBACK 2026-03-09] Pass total_hint_computed as fallback
    if annexure_total or total_hint_computed:
        print(f"  <span class='strategy-trying' style='color: #0275d8;'>[TRYING BOUNDARY DETECTION (Strategy 6)]</span>")
        result = extract_shp_using_boundary_detection(
            text, 
            annexure_total,       # DB total (try first - original)
            lockin_locked_hint,
            total_hint_computed   # Computed total (fallback) [2026-03-09]
        )
        if result and result.get('total_verified'):  # Must be FULLY verified
            strategy_results["boundary_detection"] = True
            # Add matched patterns (will be None since we didn't use patterns)
            result["matched_patterns"] = {
                "promoter": None,
                "public": None,
                "other": None
            }
            result["strategy_used"] = "boundary_detection"
            result["strategy_results"] = strategy_results
            print(f"  <span class='strategy-success' style='color: #5cb85c; font-weight: bold;'>[BOUNDARY DETECTION] SUCCESS</span>")
            return result
        else:
            print(f"  <span class='strategy-fail' style='color: #f0ad4e;'>[BOUNDARY DETECTION] Failed</span>")

    # Strategy 7: Column count validation with math verification (NEW)
    # Pure number-based: filters by column count, validates by math
    if annexure_total:
        print(f"  <span class='strategy-trying' style='color: #0275d8;'>[TRYING COLUMN COUNT VALIDATION (Strategy 7)]</span>")
        result = extract_shp_with_column_count_validation(text, annexure_total, lockin_locked_hint)
        if result and result.get('total_verified') and result.get('maths_verified'):
            strategy_results["column_count_validation"] = True
            result["matched_patterns"] = {
                "promoter": None,
                "public": None,
                "other": None
            }
            result["strategy_used"] = "column_count_validation"
            result["strategy_results"] = strategy_results
            print(f"  <span class='strategy-success' style='color: #5cb85c; font-weight: bold;'>[COLUMN COUNT VALIDATION] SUCCESS (cols={result.get('column_count_info', {}).get('total_columns')}, verified by math)</span>")
            return result
        else:
            print(f"  <span class='strategy-fail' style='color: #f0ad4e;'>[COLUMN COUNT VALIDATION] Failed</span>")

    # Strategy 5: Pure position-based (FINAL FALLBACK - requires hints)
    # Runs if Strategies 6 & 7 failed AND we have known_total
    if annexure_total:
        print(f"  [TRYING SIMPLE POSITION-BASED (Strategy 5)]")
        result = extract_shp_using_simple_position(text, annexure_total, lockin_locked_hint)
        if result and result.get('total_verified'):  # Must be FULLY verified
            strategy_results["simple_position"] = True
            # Add matched patterns (will be None since we didn't use patterns)
            result["matched_patterns"] = {
                "promoter": None,
                "public": None,
                "other": None
            }
            result["strategy_used"] = "simple_position"
            result["strategy_results"] = strategy_results
            print(f"  [SIMPLE POSITION-BASED] OK Success")
            return result
        else:
            print(f"  [SIMPLE POSITION-BASED] Failed")
    
    # Strategy 5 failed - return Strategy 4 result (even if partial)
    return strategy4_result


def derive_shp_candidates(stem: str, method: str) -> List[str]:
    """
    Build SHP text filename candidates for a lock-in stem.
    Handles common variants:
      - EPWINDIA-CML72045 -> SHP-EPWINDIA_{method}.txt
      - 544677-DEFRAIL-Annexure-I -> SHP-DEFRAIL_{method}.txt
      - fallback to SHP-{stem}_{method}.txt
    """
    candidates: List[str] = [f"SHP-{stem}_{method}.txt"]

    # NSE style: SYMBOL-CML12345
    if "-CML" in stem.upper():
        sym = stem.split("-CML", 1)[0].strip()
        if sym:
            candidates.append(f"SHP-{sym}_{method}.txt")

    # BSE style: CODE-SYMBOL-Annexure-I
    parts = stem.split("-")
    if len(parts) >= 2:
        if parts[0].isdigit():
            sym = parts[1].strip()
            if sym:
                candidates.append(f"SHP-{sym}_{method}.txt")

    # Unique order
    seen = set()
    uniq = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def resolve_shp_text_file(shp_dir: Path, stem: str, method: str) -> Optional[Path]:
    """Return the first existing SHP text file candidate."""
    for name in derive_shp_candidates(stem, method):
        p = shp_dir / name
        if p.exists():
            return p
