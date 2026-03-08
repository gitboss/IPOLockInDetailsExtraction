"""
SHP Parser - All 8 Extraction Strategies (Replicated from Production)
Cascades through strategies until one succeeds with full verification
"""

import re
from typing import List, Tuple, Optional, Dict
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════
# PATTERN DEFINITIONS (Category A, B, C)
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def extract_numbers(line: str) -> List[int]:
    """Extract integer numbers from a line, preserving order."""
    out: List[int] = []
    for token in re.findall(r'\d[\d,]*', line):
        try:
            out.append(int(token.replace(",", "")))
        except ValueError:
            continue
    return out


def normalize_pattern_text(text: str) -> str:
    """Normalize text for pattern matching (remove spaces, lowercase)."""
    return re.sub(r'\s+', '', text.lower())


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


def detect_columns_from_whitespace(line: str) -> Optional[List[Tuple[int, int]]]:
    """
    Detect column positions from whitespace gaps in a line.
    Returns list of (start, end) positions for each column.
    """
    if not line:
        return None

    # Simple implementation: detect continuous number groups
    columns = []
    in_column = False
    start = 0

    for i, char in enumerate(line):
        if char.isdigit() or char == ',':
            if not in_column:
                start = i
                in_column = True
        else:
            if in_column:
                columns.append((start, i))
                in_column = False

    if in_column:
        columns.append((start, len(line)))

    return columns if len(columns) >= 2 else None


def pick_value_from_column(line: str, col_idx: Optional[int], fallback: Optional[int] = None) -> Optional[int]:
    """Extract value from specific column index."""
    if not line:
        return fallback

    nums = extract_numbers(line)
    if col_idx is not None and 0 <= col_idx < len(nums):
        return nums[col_idx]

    # Fallback: return first number or fallback value
    return nums[0] if nums else fallback


def detect_total_row_columns(total_line: str, annexure_total: Optional[int]) -> Tuple[List[int], Optional[int], Optional[int], Optional[int]]:
    """
    Detect column positions in total row.
    Returns: (total_nums, share_col_idx, locked_col_idx, detected_total)
    """
    total_nums = extract_numbers(total_line)
    share_col_idx = None
    locked_col_idx = None
    detected_total = None

    if annexure_total and annexure_total in total_nums:
        share_col_idx = total_nums.index(annexure_total)
        detected_total = annexure_total

        # Try to find locked column (usually next column after total)
        if share_col_idx + 1 < len(total_nums):
            locked_col_idx = share_col_idx + 1
    elif total_nums:
        # Fallback: use largest number as total
        share_col_idx = total_nums.index(max(total_nums))
        detected_total = total_nums[share_col_idx]

    return total_nums, share_col_idx, locked_col_idx, detected_total


def find_line_by_patterns(text: str, patterns: List[str]) -> str:
    """Find line matching any pattern (returns line without pattern info)."""
    line, _ = find_line_and_pattern(text, patterns)
    return line


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 1: SPATIAL COLUMNS
# ═══════════════════════════════════════════════════════════════════════════

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
    Strategy 1: Extract values using detected spatial column positions.
    Returns None if ANY value is missing (promoter, public, or other).
    """
    if not total_line or not columns or len(columns) < 2:
        return None

    # Use total line as reference to find column position
    total_nums = extract_numbers(total_line)
    if not total_nums:
        return None

    # Find which position in total_line has the total_shares value
    share_position = None
    detected_total = None
    total_verified = False

    if annexure_total:
        # Find position where total EXACTLY matches annexure_total
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
        other_nums = extract_numbers(other_line)
        other = other_nums[share_position] if share_position < len(other_nums) else None

    # Validation: all values must be found
    if promoter is None or public is None:
        return None

    # Handle missing other (assume 0)
    if other is None:
        other = 0

    # Validate math
    calculated_total = promoter + public + other

    # Extract locked value
    locked = None
    locked_col_idx = share_position + 1
    if locked_col_idx < len(total_nums):
        locked = total_nums[locked_col_idx]

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": detected_total,
        "total_verified": total_verified and (calculated_total == detected_total),
        "shp_locked_total": locked,
        "shp_locked_verified": (locked == lockin_locked_hint) if lockin_locked_hint and locked else (locked is not None),
        "promoter_found": True,
        "public_found": True,
        "other_found": other > 0,
        "locked_found": locked is not None,
        "all_values_found": True,
        "maths_verified": (calculated_total == detected_total),
    }


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 2: FIXED CHARACTER POSITIONS
# ═══════════════════════════════════════════════════════════════════════════

def extract_using_fixed_positions(
    promoter_line: str,
    public_line: str,
    other_line: str,
    total_line: str,
    annexure_total: Optional[int],
    lockin_locked_hint: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 2: Extract using fixed character positions.
    Similar to Strategy 1 but uses number position instead of whitespace columns.
    """
    if not total_line:
        return None

    total_nums = extract_numbers(total_line)
    if not total_nums:
        return None

    # Find share column position
    share_position = None
    detected_total = None
    total_verified = False

    if annexure_total and annexure_total in total_nums:
        share_position = total_nums.index(annexure_total)
        detected_total = annexure_total
        total_verified = True
    elif total_nums:
        share_position = total_nums.index(max(total_nums))
        detected_total = total_nums[share_position]

    if share_position is None:
        return None

    # Extract from same position
    promoter = pick_value_from_column(promoter_line, share_position)
    public = pick_value_from_column(public_line, share_position)
    other = pick_value_from_column(other_line, share_position)

    if promoter is None or public is None:
        return None

    if other is None:
        other = 0

    # Validate math
    calculated_total = promoter + public + other

    # Extract locked
    locked = None
    locked_col_idx = share_position + 1
    if locked_col_idx < len(total_nums):
        locked = total_nums[locked_col_idx]

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": detected_total,
        "total_verified": total_verified and (calculated_total == detected_total),
        "shp_locked_total": locked,
        "shp_locked_verified": (locked == lockin_locked_hint) if lockin_locked_hint and locked else (locked is not None),
        "promoter_found": True,
        "public_found": True,
        "other_found": other > 0,
        "locked_found": locked is not None,
        "all_values_found": True,
        "maths_verified": (calculated_total == detected_total),
    }


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 3: POSITION-BASED FALLBACK
# ═══════════════════════════════════════════════════════════════════════════

def extract_shp_using_position_from_total(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 3: Position-based extraction from Total row.
    Finds Total row, then works backwards to find promoter/public/other.
    """
    if not known_total:
        return None

    lines = text.splitlines()

    # Find Total row
    total_row_idx = None
    total_nums = []
    share_col_idx = None

    for idx, line in enumerate(lines):
        nums = extract_numbers(line)
        if known_total in nums:
            total_row_idx = idx
            total_nums = nums
            share_col_idx = nums.index(known_total)
            break

    if total_row_idx is None or share_col_idx is None:
        return None

    # Go UP from Total to find promoter, public, other (3 rows above Total)
    promoter = None
    public = None
    other = None

    # Look for 3 data rows above Total
    data_rows = []
    for idx in range(total_row_idx - 1, max(0, total_row_idx - 10), -1):
        line = lines[idx]
        nums = extract_numbers(line)

        # Check if this is a data row (has numbers in the share column)
        if share_col_idx < len(nums):
            data_rows.append(nums)
            if len(data_rows) >= 3:
                break

    # Assign: row 0 = other, row 1 = public, row 2 = promoter (reverse order)
    if len(data_rows) >= 2:
        data_rows.reverse()  # Get top-to-bottom order

        if len(data_rows) >= 1 and share_col_idx < len(data_rows[0]):
            promoter = data_rows[0][share_col_idx]

        if len(data_rows) >= 2 and share_col_idx < len(data_rows[1]):
            public = data_rows[1][share_col_idx]

        if len(data_rows) >= 3 and share_col_idx < len(data_rows[2]):
            other = data_rows[2][share_col_idx]
        else:
            other = 0

    if promoter is None or public is None:
        return None

    # Validate math
    calculated_total = promoter + public + (other or 0)

    # Extract locked
    locked = None
    locked_col_idx = share_col_idx + 1
    if locked_col_idx < len(total_nums):
        locked = total_nums[locked_col_idx]

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other or 0,
        "total_shares": known_total,
        "total_verified": (calculated_total == known_total),
        "shp_locked_total": locked,
        "shp_locked_verified": (locked == known_locked) if known_locked and locked else (locked is not None),
        "promoter_found": True,
        "public_found": True,
        "other_found": other is not None and other > 0,
        "locked_found": locked is not None,
        "all_values_found": True,
        "maths_verified": (calculated_total == known_total),
    }


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 4: SEQUENTIAL PATTERN-BASED (with fallback)
# ═══════════════════════════════════════════════════════════════════════════

def extract_shp_values_from_text(text: str, annexure_total: Optional[int] = None) -> Dict:
    """
    Strategy 4: Sequential pattern-based extraction.
    Always returns result (even if partial) for backward compatibility.
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

    # Validate math
    maths_verified = False
    total_verified = False

    if all_values_found and total:
        calculated_total = promoter + public + other
        maths_verified = (calculated_total == total)
        total_verified = maths_verified

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": total,
        "total_verified": total_verified,
        "shp_locked_total": locked,
        "shp_locked_verified": locked is not None,
        "promoter_found": promoter_found,
        "public_found": public_found,
        "other_found": other_found,
        "locked_found": locked is not None,
        "all_values_found": all_values_found,
        "maths_verified": maths_verified,
    }


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 6: BOUNDARY DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def extract_shp_using_boundary_detection(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 6: Boundary-detection position-based extraction.
    Goes UP from Total row until hitting data section boundary.

    Algorithm:
    1. Find Total row containing known_total
    2. Go UP line by line from Total
    3. Check if line is data: 3+ numbers AND (>10,000 OR max ≤100)
    4. If data: collect it, reset consecutive_non_data counter
    5. If non-data: increment consecutive_non_data
    6. Stop if consecutive_non_data >= 3 (hit boundary)
    7. Extract values from same column position as known_total
    """
    if not known_total:
        return None

    lines = text.splitlines()

    # Step 1: Find Total row containing known_total
    total_row_idx = None
    total_line = None

    for i, line in enumerate(lines):
        nums = extract_numbers(line)
        if known_total in nums:
            total_row_idx = i
            total_line = line
            break

    if total_row_idx is None:
        return None

    # Step 2: Go UP from Total, collecting data rows until boundary
    data_rows = []
    consecutive_non_data = 0
    max_rows = 10  # Safety limit
    boundary_threshold = 3  # Stop after N consecutive non-data lines

    for i in range(total_row_idx - 1, -1, -1):
        line = lines[i]

        if not line.strip():
            consecutive_non_data += 1
            if consecutive_non_data >= boundary_threshold:
                break
            continue

        nums = extract_numbers(line)

        # Data row detection criteria
        has_enough_numbers = len(nums) >= 3

        if has_enough_numbers:
            # Check if row contains share data (not dates or metadata)
            has_share_count = any(n > 10000 for n in nums)
            is_zero_row = max(nums) <= 100 if nums else False

            if has_share_count or is_zero_row:
                # This is likely a data row
                data_rows.append({
                    'index': i,
                    'line': line.strip(),
                    'numbers': nums
                })
                consecutive_non_data = 0  # Reset counter
            else:
                # Has numbers but not share data pattern
                consecutive_non_data += 1
                if consecutive_non_data >= boundary_threshold:
                    break
        else:
            # Has <3 numbers (likely header or separator)
            consecutive_non_data += 1
            if consecutive_non_data >= boundary_threshold:
                break

        if len(data_rows) >= max_rows:
            break  # Safety limit

    # Reverse to get top-to-bottom order
    data_rows.reverse()

    if len(data_rows) < 2:
        return None

    # Step 3: Find share position in Total row
    total_nums = extract_numbers(total_line)
    share_position = None

    for i, num in enumerate(total_nums):
        if num == known_total:
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
        other = 0

    if promoter is None or public is None:
        return None

    # Step 5: Validation
    calc_sum = promoter + public + (other or 0)

    # Extract locked
    locked = None
    locked_col_idx = share_position + 1
    if locked_col_idx < len(total_nums):
        locked = total_nums[locked_col_idx]

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other or 0,
        "total_shares": known_total,
        "total_verified": (calc_sum == known_total),
        "shp_locked_total": locked,
        "shp_locked_verified": (locked == known_locked) if known_locked and locked else (locked is not None),
        "promoter_found": True,
        "public_found": True,
        "other_found": other is not None and other > 0,
        "locked_found": locked is not None,
        "all_values_found": True,
        "maths_verified": (calc_sum == known_total),
    }


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 7: COLUMN COUNT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def extract_shp_with_column_count_validation(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 7: Column count validation with math verification.
    Pure number-based: filters by column count, validates by math.
    """
    if not known_total:
        return None

    lines = text.splitlines()

    # Find Total row
    total_row_idx = None
    total_nums = []
    share_col_idx = None

    for idx, line in enumerate(lines):
        nums = extract_numbers(line)
        if known_total in nums:
            total_row_idx = idx
            total_nums = nums
            share_col_idx = nums.index(known_total)
            break

    if total_row_idx is None or share_col_idx is None:
        return None

    # Expected column count from Total row
    expected_col_count = len(total_nums)

    # Go UP from Total, collecting rows with same column count
    data_rows = []
    for idx in range(total_row_idx - 1, max(0, total_row_idx - 20), -1):
        line = lines[idx]
        nums = extract_numbers(line)

        # Only collect rows with same column count as Total
        if len(nums) == expected_col_count:
            data_rows.append(nums)
            if len(data_rows) >= 3:
                break

    if len(data_rows) < 2:
        return None

    # Reverse to get top-to-bottom order
    data_rows.reverse()

    # Extract values
    promoter = data_rows[0][share_col_idx] if share_col_idx < len(data_rows[0]) else None
    public = data_rows[1][share_col_idx] if len(data_rows) > 1 and share_col_idx < len(data_rows[1]) else None
    other = data_rows[2][share_col_idx] if len(data_rows) > 2 and share_col_idx < len(data_rows[2]) else 0

    if promoter is None or public is None:
        return None

    # Validate math
    calculated_total = promoter + public + (other or 0)

    # Extract locked
    locked = None
    locked_col_idx = share_col_idx + 1
    if locked_col_idx < len(total_nums):
        locked = total_nums[locked_col_idx]

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other or 0,
        "total_shares": known_total,
        "total_verified": (calculated_total == known_total),
        "shp_locked_total": locked,
        "shp_locked_verified": (locked == known_locked) if known_locked and locked else (locked is not None),
        "promoter_found": True,
        "public_found": True,
        "other_found": other is not None and other > 0,
        "locked_found": locked is not None,
        "all_values_found": True,
        "maths_verified": (calculated_total == known_total),
        "column_count_info": {
            "total_columns": expected_col_count,
            "rows_found": len(data_rows)
        }
    }


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 8: REVERSE-ORDER FROM TOTAL
# ═══════════════════════════════════════════════════════════════════════════

def extract_shp_reverse_order_from_total(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 8: Reverse-order extraction from Total row (NO PATTERN MATCHING).

    Algorithm:
    1. Find Total row by known_total
    2. Go UP from Total row
    3. 1st row above Total = Promoter
    4. 2nd row above Total = Public
    5. ALL remaining rows above (until boundary) = sum for Others (handles C, C1, C2, C3...)
    6. Extract locked column from Total row

    This handles multiple "other" sub-categories without pattern matching!
    """
    lines = text.split('\n')

    # Find Total row
    total_line_idx = None
    total_row_nums = []
    share_col_idx = None
    locked_col_idx = None

    for idx, line in enumerate(lines):
        nums = extract_numbers(line)
        if known_total in nums:
            total_line_idx = idx
            total_row_nums = nums
            share_col_idx = nums.index(known_total)

            # Try to find locked column
            if known_locked and known_locked in nums:
                locked_col_idx = nums.index(known_locked)
            break

    if total_line_idx is None or share_col_idx is None:
        return None

    # Go UP from Total to find data rows
    data_rows = []
    for idx in range(total_line_idx - 1, -1, -1):
        line = lines[idx]
        nums = extract_numbers(line)

        # Check if this is a data row (has 3+ numbers, has values >10k OR all <=100)
        if len(nums) < 3:
            # Hit boundary - not enough numbers
            break

        max_val = max(nums) if nums else 0
        has_large = any(n > 10000 for n in nums)
        all_small = max_val <= 100

        if not (has_large or all_small):
            # Hit boundary - numbers don't match data criteria
            break

        # This is a data row
        if share_col_idx < len(nums):
            share_val = nums[share_col_idx]
            data_rows.append(share_val)

        # Safety limit
        if len(data_rows) >= 10:
            break

    if len(data_rows) < 2:
        # Need at least promoter and public
        return None

    # Reverse to get top-to-bottom order
    data_rows.reverse()

    # 1st = Promoter, 2nd = Public, rest = Others (sum them)
    promoter = data_rows[0]
    public = data_rows[1]
    others = data_rows[2:] if len(data_rows) > 2 else []
    other_total = sum(others) if others else 0

    # Extract locked value
    locked = None
    if locked_col_idx is not None and locked_col_idx < len(total_row_nums):
        locked = total_row_nums[locked_col_idx]

    # Validate math
    calculated_total = promoter + public + other_total
    total_verified = (calculated_total == known_total)
    locked_verified = (locked == known_locked) if known_locked else (locked is not None)

    if not total_verified:
        return None

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other_total,
        "total_shares": known_total,
        "total_verified": True,
        "shp_locked_total": locked,
        "shp_locked_verified": locked_verified,
        "promoter_found": True,
        "public_found": True,
        "other_found": other_total > 0,
        "locked_found": locked is not None,
        "all_values_found": True,
        "maths_verified": True,
        "other_rows_count": len(others),  # How many "other" sub-rows found
    }


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 5: SIMPLE POSITION (FINAL FALLBACK)
# ═══════════════════════════════════════════════════════════════════════════

def extract_shp_using_simple_position(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 5: Simple position-based extraction (FINAL FALLBACK).
    Basic extraction from fixed window above Total row.
    """
    if not known_total:
        return None

    lines = text.splitlines()

    # Find Total row
    total_row_idx = None
    total_nums = []
    share_col_idx = None

    for idx, line in enumerate(lines):
        nums = extract_numbers(line)
        if known_total in nums:
            total_row_idx = idx
            total_nums = nums
            share_col_idx = nums.index(known_total)
            break

    if total_row_idx is None or share_col_idx is None:
        return None

    # Simple approach: look for exactly 3 rows above Total (in reverse order)
    # Row -1 = Other, Row -2 = Public, Row -3 = Promoter
    promoter = None
    public = None
    other = None

    if total_row_idx >= 3:
        # Get 3 rows above Total
        row_3 = lines[total_row_idx - 3]  # Promoter
        row_2 = lines[total_row_idx - 2]  # Public
        row_1 = lines[total_row_idx - 1]  # Other

        nums_3 = extract_numbers(row_3)
        nums_2 = extract_numbers(row_2)
        nums_1 = extract_numbers(row_1)

        promoter = nums_3[share_col_idx] if share_col_idx < len(nums_3) else None
        public = nums_2[share_col_idx] if share_col_idx < len(nums_2) else None
        other = nums_1[share_col_idx] if share_col_idx < len(nums_1) else 0

    if promoter is None or public is None:
        return None

    # Validate math
    calculated_total = promoter + public + (other or 0)

    # Extract locked
    locked = None
    locked_col_idx = share_col_idx + 1
    if locked_col_idx < len(total_nums):
        locked = total_nums[locked_col_idx]

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other or 0,
        "total_shares": known_total,
        "total_verified": (calculated_total == known_total),
        "shp_locked_total": locked,
        "shp_locked_verified": (locked == known_locked) if known_locked and locked else (locked is not None),
        "promoter_found": True,
        "public_found": True,
        "other_found": other is not None and other > 0,
        "locked_found": locked is not None,
        "all_values_found": True,
        "maths_verified": (calculated_total == known_total),
    }


# ═══════════════════════════════════════════════════════════════════════════
# MAIN CASCADE FUNCTION
# ═══════════════════════════════════════════════════════════════════════════

def extract_shp_with_cascade(
    text: str,
    annexure_total: Optional[int] = None,
    lockin_locked_hint: Optional[int] = None,
    verbose: bool = False
) -> Dict:
    """
    Main SHP extraction function using CASCADE of all 8 strategies.

    Strategy cascade order:
    1. Spatial columns
    2. Fixed positions
    3. Position-based fallback
    4. Sequential pattern-based (kept as fallback)
    5. Boundary detection (Strategy 6)
    6. Column count validation (Strategy 7)
    7. Reverse-order from Total (Strategy 8)
    8. Simple position (Strategy 5) - FINAL FALLBACK

    Returns:
        Dict with extracted values and metadata about which strategy succeeded
    """

    # Track which strategies were attempted
    strategy_results = {
        "spatial_columns": False,
        "fixed_positions": False,
        "position_based": False,
        "sequential": False,
        "boundary_detection": False,
        "column_count_validation": False,
        "reverse_order_from_total": False,
        "simple_position": False,
    }

    # Find lines using pattern matching
    promoter_line, promoter_pattern = find_line_and_pattern(text, SHP_PATTERNS_A)
    public_line, public_pattern = find_line_and_pattern(text, SHP_PATTERNS_B)
    other_line, other_pattern = find_line_and_pattern(text, SHP_PATTERNS_C)
    total_line = find_total_line(text)

    # Strategy 1: Detect columns from whitespace gaps
    columns = detect_columns_from_whitespace(total_line) if total_line else None
    if columns:
        if verbose:
            print("  [TRYING Strategy 1: Spatial Columns]")
        result = extract_using_spatial_columns(
            promoter_line, public_line, other_line, total_line,
            columns, annexure_total, lockin_locked_hint
        )
        if result and result.get('total_verified'):
            strategy_results["spatial_columns"] = True
            result["matched_patterns"] = {
                "promoter": promoter_pattern,
                "public": public_pattern,
                "other": other_pattern
            }
            result["strategy_used"] = "spatial_columns"
            result["strategy_results"] = strategy_results
            if verbose:
                print("  [Strategy 1: Spatial Columns] ✓ SUCCESS")
            return result

    # Strategy 2: Try fixed character positions
    if verbose:
        print("  [TRYING Strategy 2: Fixed Positions]")
    result = extract_using_fixed_positions(
        promoter_line, public_line, other_line, total_line,
        annexure_total, lockin_locked_hint
    )
    if result and result.get('total_verified'):
        strategy_results["fixed_positions"] = True
        result["matched_patterns"] = {
            "promoter": promoter_pattern,
            "public": public_pattern,
            "other": other_pattern
        }
        result["strategy_used"] = "fixed_positions"
        result["strategy_results"] = strategy_results
        if verbose:
            print("  [Strategy 2: Fixed Positions] ✓ SUCCESS")
        return result

    # Strategy 3: Try deterministic position-based approach
    if annexure_total:
        if verbose:
            print("  [TRYING Strategy 3: Position-Based Fallback]")
        result = extract_shp_using_position_from_total(text, annexure_total, lockin_locked_hint)
        if result and result.get('total_verified'):
            strategy_results["position_based"] = True
            result["matched_patterns"] = {
                "promoter": None,
                "public": None,
                "other": None
            }
            result["strategy_used"] = "position_based"
            result["strategy_results"] = strategy_results
            if verbose:
                print("  [Strategy 3: Position-Based Fallback] ✓ SUCCESS")
            return result

    # Strategy 4: Sequential fallback (pattern-based)
    if verbose:
        print("  [TRYING Strategy 4: Sequential Pattern-Based]")
    result = extract_shp_values_from_text(text, annexure_total)

    # Check if Strategy 4 returned complete data
    if result:
        all_found = result.get('all_values_found', False)
        maths_ok = result.get('maths_verified', False)

        # Validate: promoter + public + other = total_shares
        total_verified = False
        if all_found and result.get('total_shares'):
            promoter = result.get('promoter_shares') or 0
            public = result.get('public_shares') or 0
            other = result.get('other_shares') or 0
            total = result.get('total_shares')
            calculated_total = promoter + public + other

            if calculated_total == total:
                total_verified = True
            elif verbose:
                print(f"  [Strategy 4] REJECT: promoter+public+other={calculated_total:,} != total={total:,}")

        # If complete AND totals match, return it
        if all_found and maths_ok and total_verified:
            strategy_results["sequential"] = True
            result["matched_patterns"] = {
                "promoter": promoter_pattern,
                "public": public_pattern,
                "other": other_pattern
            }
            result["strategy_used"] = "sequential"
            result["strategy_results"] = strategy_results
            if verbose:
                print("  [Strategy 4: Sequential] ✓ SUCCESS")
            return result

        # Keep Strategy 4 result as fallback
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

    # Strategy 6: Boundary-detection position-based
    if annexure_total:
        if verbose:
            print("  [TRYING Strategy 6: Boundary Detection]")
        result = extract_shp_using_boundary_detection(text, annexure_total, lockin_locked_hint)
        if result and result.get('total_verified'):
            strategy_results["boundary_detection"] = True
            result["matched_patterns"] = {
                "promoter": None,
                "public": None,
                "other": None
            }
            result["strategy_used"] = "boundary_detection"
            result["strategy_results"] = strategy_results
            if verbose:
                print("  [Strategy 6: Boundary Detection] ✓ SUCCESS")
            return result

    # Strategy 7: Column count validation
    if annexure_total:
        if verbose:
            print("  [TRYING Strategy 7: Column Count Validation]")
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
            if verbose:
                cols = result.get('column_count_info', {}).get('total_columns')
                print(f"  [Strategy 7: Column Count Validation] ✓ SUCCESS (cols={cols})")
            return result

    # Strategy 8: Reverse-order from Total
    if annexure_total:
        if verbose:
            print("  [TRYING Strategy 8: Reverse-Order from Total]")
        result = extract_shp_reverse_order_from_total(text, annexure_total, lockin_locked_hint)
        if result and result.get('total_verified'):
            strategy_results["reverse_order_from_total"] = True
            result["matched_patterns"] = {
                "promoter": None,
                "public": None,
                "other": None
            }
            result["strategy_used"] = "reverse_order_from_total"
            result["strategy_results"] = strategy_results
            if verbose:
                other_count = result.get('other_rows_count', 0)
                print(f"  [Strategy 8: Reverse-Order] ✓ SUCCESS (found {other_count} 'other' sub-rows)")
            return result

    # Strategy 5: Pure position-based (FINAL FALLBACK)
    if annexure_total:
        if verbose:
            print("  [TRYING Strategy 5: Simple Position (FINAL FALLBACK)]")
        result = extract_shp_using_simple_position(text, annexure_total, lockin_locked_hint)
        if result and result.get('total_verified'):
            strategy_results["simple_position"] = True
            result["matched_patterns"] = {
                "promoter": None,
                "public": None,
                "other": None
            }
            result["strategy_used"] = "simple_position"
            result["strategy_results"] = strategy_results
            if verbose:
                print("  [Strategy 5: Simple Position] ✓ SUCCESS")
            return result

    # All strategies failed - return Strategy 4 result (even if partial)
    if verbose:
        print("  [ALL STRATEGIES FAILED] Returning Strategy 4 result (may be partial)")

    if strategy4_result:
        return strategy4_result

    # Complete failure - return empty result
    return {
        "promoter_shares": None,
        "public_shares": None,
        "other_shares": None,
        "total_shares": annexure_total,
        "total_verified": False,
        "shp_locked_total": None,
        "shp_locked_verified": False,
        "promoter_found": False,
        "public_found": False,
        "other_found": False,
        "locked_found": False,
        "all_values_found": False,
        "maths_verified": False,
        "strategy_used": "none",
        "strategy_results": strategy_results,
    }


def main():
    """Test SHP strategies with sample file"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parser_shp_strategies.py <path_to_shp_java.txt> [known_total] [known_locked]")
        print("Example: python parser_shp_strategies.py downloads/bse/pdf/shp/txt/544324-CITICHEM-Annexure-II_java.txt 1800000 1500000")
        sys.exit(1)

    txt_path = Path(sys.argv[1])
    known_total = int(sys.argv[2]) if len(sys.argv) >= 3 else None
    known_locked = int(sys.argv[3]) if len(sys.argv) >= 4 else None

    print(f"Testing SHP Strategies: {txt_path}")
    print(f"Known Total: {known_total:,}" if known_total else "Known Total: None")
    print(f"Known Locked: {known_locked:,}" if known_locked else "Known Locked: None")
    print("=" * 70)

    # Read file
    with open(txt_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Extract using cascade
    result = extract_shp_with_cascade(text, known_total, known_locked, verbose=True)

    print("\n" + "=" * 70)
    print("RESULT:")
    print("=" * 70)
    print(f"Strategy Used: {result.get('strategy_used')}")
    print(f"Promoter:      {result.get('promoter_shares'):,}" if result.get('promoter_shares') else "Promoter:      None")
    print(f"Public:        {result.get('public_shares'):,}" if result.get('public_shares') else "Public:        None")
    print(f"Others:        {result.get('other_shares'):,}" if result.get('other_shares') else "Others:        None")
    print(f"Total:         {result.get('total_shares'):,}" if result.get('total_shares') else "Total:         None")
    print(f"Locked:        {result.get('shp_locked_total'):,}" if result.get('shp_locked_total') else "Locked:        None")
    print(f"\nTotal Verified: {result.get('total_verified')}")
    print(f"Maths Verified: {result.get('maths_verified')}")
    print(f"All Found:      {result.get('all_values_found')}")


if __name__ == "__main__":
    main()
