#!/usr/bin/env python3
"""
Unified SHP Parser - Combines all 8 strategies into a single parser.

Version: 1.0.0

This module provides a unified interface for extracting SHP (Shareholding Pattern)
values from extracted text using cascading strategies.

Strategies:
    1. spatial_columns - Detect columns from whitespace gaps
    2. fixed_positions - Fixed character positions
    3. position_based - Uses known total/locked to find rows by position
    4. sequential - Sequential number extraction (pattern-based)
    5. boundary_detection - Scans UP from Total until boundary
    6. column_count_validation - Filters by column count, validates by math
    7. simple_position - Pure numbers, no validation (fallback)
    8. reverse_order - Reverse order parsing for special cases

Usage:
    from shp_parser_unified import parse_shp_text
    
    result = parse_shp_text(text, annexure_total=5000000, lockin_locked_hint=3000000)
    print(result)
"""

from typing import Dict, List, Optional, Tuple
import re


# ============================================================================
# CONSTANTS - SHP Pattern Detection
# ============================================================================

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

JAVA_PATTERNS = [
    ("(a)promoter&promotergroup", "(A) Promoter & Promoter Group"),
    ("(a)promotergroup", "(A) Promoter Group"),
    ("(b)public", "(B) Public"),
    ("(c)nonpromoternonpublic", "(C) Non Promoter Non Public"),
    ("(c)nonpromoternonepublic", "(C) Non Promoter None Public"),
    ("(c)nonpublic", "(C) Non Public"),
    ("(c)nonpromoter", "(C) Non Promoter"),
    ("totalshareholdingofpromoters", "Total Shareholding of Promoters"),
    ("totalshareholdingofpromoter", "Total Shareholding of Promoter"),
    ("totalshareholding", "Total Shareholding"),
    ("totalpublicshareholding", "Total Public Shareholding"),
    ("totalpublic", "Total Public"),
    ("totalnonpromoter", "Total Non Promoter"),
]

JAVA_CORE_GROUPS = [
    ["(a)promoter&promotergroup", "(a)promotergroup"],
    ["(b)public"],
    ["(c)nonpromoternonpublic", "(c)nonpromoternonepublic", "(c)nonpublic", "(c)nonpromoter"],
    ["totalshareholdingofpromoters", "totalshareholdingofpromoter", "totalshareholding"],
    ["totalpublicshareholding", "totalpublic"],
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def normalize_pattern_text(text: str) -> str:
    """Normalize text for robust pattern matching."""
    return text.lower().replace(" ", "").replace("-", "")


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces into single space, preserve line breaks."""
    lines = []
    for line in text.splitlines():
        collapsed = re.sub(r' {2,}', ' ', line.strip())
        if collapsed:
            lines.append(collapsed)
    return '\n'.join(lines)


def extract_numbers(line: str) -> List[int]:
    """Extract integer numbers from a line, preserving order."""
    out: List[int] = []
    for token in re.findall(r'\d[\d,]*', line):
        try:
            out.append(int(token.replace(",", "")))
        except ValueError:
            continue
    return out


def normalize_java_pattern_text(text: str) -> str:
    return text.lower().replace(" ", "").replace("-", "")


def scan_java_patterns(text: str) -> Dict:
    """Scan for Java patterns in text."""
    normalized = normalize_java_pattern_text(text)
    found = set()
    for pattern, _ in JAVA_PATTERNS:
        if pattern in normalized:
            found.add(pattern)

    core_matched = sum(
        1 for group in JAVA_CORE_GROUPS if any(p in found for p in group)
    )
    return {
        "found_count": len(found),
        "total_count": len(JAVA_PATTERNS),
        "core_matched": core_matched,
        "core_total": len(JAVA_CORE_GROUPS),
        "core_all_matched": core_matched == len(JAVA_CORE_GROUPS),
    }


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
    """Find grand total row for Table I."""
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


def detect_total_row_columns(line: str, total_hint: Optional[int] = None) -> Tuple[List[int], Optional[int], Optional[int], Optional[int]]:
    """
    Detect column indexes from Total row.
    
    Returns:
        nums, share_col_idx, locked_col_idx, total_value
    """
    nums = extract_numbers(line)
    if not nums:
        return [], None, None, None

    share_col_idx: Optional[int] = None
    total_value: Optional[int] = None

    # Find the share column (the largest number - total shares)
    if total_hint is not None:
        for i, n in enumerate(nums):
            if n == total_hint:
                share_col_idx = i
                total_value = n
                break

    if share_col_idx is None:
        if nums:
            share_col_idx, total_value = max(enumerate(nums), key=lambda x: x[1])

    if share_col_idx is None:
        return nums, None, None, None

    # Locked shares: find the first number AFTER share_col_idx that:
    # - Is > 0
    # - Is < total_value
    # - Is NOT equal to any earlier number in the row (to avoid duplicates)
    locked_col_idx: Optional[int] = None
    
    if total_value is not None:
        # Get all unique numbers before share_col_idx to avoid duplicates
        earlier_numbers = set(nums[:share_col_idx])
        
        for i in range(share_col_idx + 1, len(nums)):
            v = nums[i]
            # Must be positive, less than total, and not a duplicate of earlier data
            if v > 0 and v < total_value and v not in earlier_numbers:
                locked_col_idx = i
                break

    return nums, share_col_idx, locked_col_idx, total_value


def pick_value_from_column(line: str, col_idx: Optional[int], total_hint: Optional[int] = None) -> Optional[int]:
    """Strict column extraction."""
    if col_idx is None:
        return None
    nums = extract_numbers(line)
    if col_idx >= len(nums):
        return None
    v = nums[col_idx]
    if total_hint is not None and v > total_hint:
        return None
    return v


# ============================================================================
# STRATEGY 1: Spatial Columns Detection
# ============================================================================

def detect_columns_from_whitespace(line: str) -> Optional[List[Tuple[int, int]]]:
    """Detect column boundaries from whitespace gaps in a line."""
    if not line:
        return None

    gaps = []
    i = 0
    while i < len(line):
        if line[i] == ' ':
            j = i
            while j < len(line) and line[j] == ' ':
                j += 1
            gap_size = j - i
            if gap_size >= 2:
                gaps.append((i, j))
            i = j
        else:
            i += 1

    if not gaps:
        return None

    columns = []
    start = 0
    for gap_start, gap_end in gaps:
        if gap_start > start:
            columns.append((start, gap_start))
        start = gap_end

    if start < len(line):
        columns.append((start, len(line)))

    return columns if len(columns) >= 2 else None


def extract_using_spatial_columns(
    promoter_line: str,
    public_line: str,
    other_line: str,
    total_line: str,
    columns: List[Tuple[int, int]],
    annexure_total: Optional[int],
    lockin_locked_hint: Optional[int] = None
) -> Optional[Dict]:
    """Extract values using detected spatial column positions."""
    if not total_line or not columns or len(columns) < 2:
        return None

    total_nums = extract_numbers(total_line)
    if not total_nums:
        return None

    share_position = None
    detected_total = None
    total_verified = False

    if annexure_total:
        for i, num in enumerate(total_nums):
            if num == annexure_total:
                share_position = i
                detected_total = num
                total_verified = True
                break

    if share_position is None and total_nums:
        share_position = total_nums.index(max(total_nums))
        detected_total = total_nums[share_position]
        total_verified = False

    if share_position is None:
        return None

    promoter = None
    public = None
    other = None
    locked = None

    if promoter_line and share_position < len(extract_numbers(promoter_line)):
        promoter = extract_numbers(promoter_line)[share_position]

    if public_line and share_position < len(extract_numbers(public_line)):
        public = extract_numbers(public_line)[share_position]

    if other_line and share_position < len(extract_numbers(other_line)):
        other = extract_numbers(other_line)[share_position]

    if total_line and detected_total:
        total_nums_full = extract_numbers(total_line)
        # Find locked shares by checking each position after share_col_idx
        # Locked shares are at a FIXED column position in the table
        # We find it by looking for the first value that's NOT a duplicate of earlier values
        # and is in the reasonable share count range (> 1000)
        seen_values = set()
        for i, num in enumerate(total_nums_full):
            if i <= share_position:
                continue
            if num > 1000 and num < detected_total:
                # Check if this value is already seen (duplicate of earlier data column)
                if num not in seen_values:
                    locked = num
                    break
            seen_values.add(num)

    all_found = promoter is not None and public is not None and other is not None
    maths_verified = False
    if all_found and annexure_total:
        maths_verified = (promoter + public + other) == annexure_total

    if all_found and detected_total:
        if (promoter + public + other) != detected_total:
            maths_verified = False

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": detected_total,
        "shp_locked_total": locked,
        "total_verified": total_verified and maths_verified,
        "maths_verified": maths_verified,
    }


# ============================================================================
# STRATEGY 2: Fixed Positions
# ============================================================================

def extract_using_fixed_positions(
    promoter_line: str,
    public_line: str,
    other_line: str,
    total_line: str,
    annexure_total: Optional[int],
    lockin_locked_hint: Optional[int] = None
) -> Optional[Dict]:
    """Extract using fixed character positions."""
    if not total_line:
        return None

    total_nums = extract_numbers(total_line)
    if not total_nums:
        return None

    share_col_idx, locked_col_idx, detected_total = None, None, None
    _, share_col_idx, locked_col_idx, detected_total = detect_total_row_columns(total_line, annexure_total)

    if share_col_idx is None:
        return None

    promoter = pick_value_from_column(promoter_line, share_col_idx, annexure_total) if promoter_line else None
    public = pick_value_from_column(public_line, share_col_idx, annexure_total) if public_line else None
    other = pick_value_from_column(other_line, share_col_idx, annexure_total) if other_line else None

    locked = None
    if locked_col_idx is not None and total_line:
        nums = extract_numbers(total_line)
        if locked_col_idx < len(nums):
            locked = nums[locked_col_idx]

    all_found = promoter is not None and public is not None and other is not None
    maths_verified = False
    if all_found and annexure_total:
        maths_verified = (promoter + public + other) == annexure_total

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": detected_total,
        "shp_locked_total": locked,
        "total_verified": maths_verified,
        "maths_verified": maths_verified,
    }


# ============================================================================
# STRATEGY 3: Position Based (from Total)
# ============================================================================

def extract_shp_using_position_from_total(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """
    Use known total to find Total row, then extract values by position.
    """
    lines = text.splitlines()
    total_line_idx = None
    total_line = None

    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if not re.match(r'^total\b', low):
            continue
        if "shareholding of promoters" in low or "public shareholding" in low:
            continue
        nums = extract_numbers(s)
        if len(nums) >= 2:
            for j, num in enumerate(nums):
                if num == known_total:
                    total_line_idx = i
                    total_line = s
                    break
            if total_line_idx is not None:
                break

    if total_line is None:
        return None

    share_col_idx = None
    nums = extract_numbers(total_line)
    for i, num in enumerate(nums):
        if num == known_total:
            share_col_idx = i
            break

    if share_col_idx is None:
        share_col_idx = nums.index(max(nums)) if nums else 0

    data_lines = []
    for i in range(max(0, total_line_idx - 10), total_line_idx):
        line = lines[i].strip()
        if line and extract_numbers(line):
            data_lines.append((i, line))

    if len(data_lines) >= 3:
        promoter_line = data_lines[0][1]
        public_line = data_lines[1][1]
        other_line = data_lines[2][1]
    else:
        promoter_line = ""
        public_line = ""
        other_line = ""

    promoter = pick_value_from_column(promoter_line, share_col_idx, known_total) if promoter_line else None
    public = pick_value_from_column(public_line, share_col_idx, known_total) if public_line else None
    other = pick_value_from_column(other_line, share_col_idx, known_total) if other_line else None
    locked = known_locked

    all_found = promoter is not None and public is not None and other is not None
    maths_verified = False
    if all_found and known_total:
        maths_verified = (promoter + public + other) == known_total

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": known_total,
        "shp_locked_total": locked,
        "total_verified": maths_verified,
        "maths_verified": maths_verified,
    }


# ============================================================================
# STRATEGY 4: Sequential (Pattern-based)
# ============================================================================

def extract_shp_values_from_text(text: str, annexure_total: Optional[int] = None) -> Dict:
    """Extract promoter/public/other/total/locked from SHP text - Strategy 4."""
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

    promoter_found = promoter is not None
    public_found = public is not None
    other_found = other is not None
    all_values_found = promoter_found and public_found and other_found

    maths_verified = False
    if all_values_found and annexure_total is not None:
        calculated_sum = promoter + public + other
        maths_verified = (calculated_sum == annexure_total)

        if maths_verified and total is not None:
            if calculated_sum != total:
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
        "promoter_found": promoter_found,
        "public_found": public_found,
        "other_found": other_found,
        "locked_found": locked is not None,
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


# ============================================================================
# STRATEGY 5: Boundary Detection
# ============================================================================

def extract_shp_using_boundary_detection(
    text: str,
    annexure_total: Optional[int] = None,
    lockin_locked_hint: Optional[int] = None
) -> Optional[Dict]:
    """
    Strategy 5: Boundary-detection position-based extraction.
    Goes UP from Total row until hitting data section boundary.

    Algorithm:
    1. Find Total row containing annexure_total
    2. Go UP line by line from Total
    3. Check if line is data: 3+ numbers AND (>10,000 OR max ≤100)
    4. If data: collect it, reset consecutive_non_data counter
    5. If non-data: increment consecutive_non_data
    6. Stop if consecutive_non_data >= 3 (hit boundary)
    7. Extract values from same column position as annexure_total
    """
    if not annexure_total:
        return None

    lines = text.splitlines()

    # Step 1: Find Total row containing annexure_total
    total_row_idx = None
    total_line = None

    for i, line in enumerate(lines):
        nums = extract_numbers(line)
        if annexure_total in nums:
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
        if num == annexure_total:
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

    # Validate math
    calculated_total = promoter + public + (other or 0)

    # Extract locked using lockin_locked_hint
    locked = None
    if lockin_locked_hint and lockin_locked_hint in total_nums:
        locked_idx = total_nums.index(lockin_locked_hint)
        locked = total_nums[locked_idx]
    else:
        for i in range(share_position + 1, len(total_nums)):
            if 0 < total_nums[i] < annexure_total:
                locked = total_nums[i]
                break

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other or 0,
        "total_shares": annexure_total,
        "shp_locked_total": locked,
        "total_verified": (calculated_total == annexure_total),
        "maths_verified": (calculated_total == annexure_total),
    }


# ============================================================================
# STRATEGY 6: Column Count Validation
# ============================================================================

def extract_shp_with_column_count_validation(
    text: str,
    annexure_total: Optional[int] = None,
    lockin_locked_hint: Optional[int] = None
) -> Optional[Dict]:
    """Filter by column count, validate by math."""
    lines = text.splitlines()
    total_line = find_total_line(text)

    if not total_line:
        return None

    total_nums, share_col_idx, locked_col_idx, detected_total = detect_total_row_columns(
        total_line, annexure_total
    )

    if share_col_idx is None:
        return None

    total_cols = len(total_nums)
    if total_cols < 2:
        return None

    promoter_line = find_line_by_patterns(text, SHP_PATTERNS_A)
    public_line = find_line_by_patterns(text, SHP_PATTERNS_B)
    other_line = find_line_by_patterns(text, SHP_PATTERNS_C)

    promoter = None
    public = None
    other = None
    locked = None

    if promoter_line:
        nums = extract_numbers(promoter_line)
        if len(nums) == total_cols:
            promoter = pick_value_from_column(promoter_line, share_col_idx, annexure_total)

    if public_line:
        nums = extract_numbers(public_line)
        if len(nums) == total_cols:
            public = pick_value_from_column(public_line, share_col_idx, annexure_total)

    if other_line:
        nums = extract_numbers(other_line)
        if len(nums) == total_cols:
            other = pick_value_from_column(other_line, share_col_idx, annexure_total)

    if locked_col_idx is not None:
        if locked_col_idx < len(total_nums):
            locked = total_nums[locked_col_idx]

    all_found = promoter is not None and public is not None and other is not None
    maths_verified = False
    if all_found and annexure_total:
        maths_verified = (promoter + public + other) == annexure_total

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": detected_total or annexure_total,
        "shp_locked_total": locked,
        "total_verified": maths_verified,
        "maths_verified": maths_verified,
    }


# ============================================================================
# STRATEGY 7: Simple Position (Fallback)
# ============================================================================

def extract_shp_using_simple_position(
    text: str,
    annexure_total: Optional[int] = None,
    lockin_locked_hint: Optional[int] = None
) -> Optional[Dict]:
    """Pure numbers, no validation - final fallback."""
    promoter_line = find_line_by_patterns(text, SHP_PATTERNS_A)
    public_line = find_line_by_patterns(text, SHP_PATTERNS_B)
    other_line = find_line_by_patterns(text, SHP_PATTERNS_C)
    total_line = find_total_line(text)

    total_nums = extract_numbers(total_line) if total_line else []
    detected_total = total_nums[-1] if total_nums else annexure_total

    share_col_idx = 0

    promoter = pick_value_from_column(promoter_line, share_col_idx, detected_total) if promoter_line else None
    public = pick_value_from_column(public_line, share_col_idx, detected_total) if public_line else None
    other = pick_value_from_column(other_line, share_col_idx, detected_total) if other_line else None

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": detected_total,
        "shp_locked_total": lockin_locked_hint,
        "total_verified": False,
        "maths_verified": False,
    }


# ============================================================================
# STRATEGY 8: Reverse Order
# ============================================================================

def extract_shp_reverse_order(
    text: str,
    known_total: int,
    known_locked: Optional[int] = None
) -> Optional[Dict]:
    """Reverse order parsing for special cases."""
    lines = text.splitlines()
    lines.reverse()

    total_line = None
    for line in lines:
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if not re.match(r'^total\b', low):
            continue
        if "shareholding of promoters" in low or "public shareholding" in low:
            continue
        nums = extract_numbers(s)
        if nums and known_total in nums:
            total_line = s
            break

    if not total_line:
        return None

    idx = lines.index(total_line)
    data_lines = lines[idx+1:idx+4]

    if len(data_lines) < 3:
        return None

    share_col_idx = 0
    promoter = pick_value_from_column(data_lines[0], share_col_idx, known_total)
    public = pick_value_from_column(data_lines[1], share_col_idx, known_total)
    other = pick_value_from_column(data_lines[2], share_col_idx, known_total)

    all_found = promoter is not None and public is not None and other is not None
    maths_verified = False
    if all_found and known_total:
        maths_verified = (promoter + public + other) == known_total

    return {
        "promoter_shares": promoter,
        "public_shares": public,
        "other_shares": other,
        "total_shares": known_total,
        "shp_locked_total": known_locked,
        "total_verified": maths_verified,
        "maths_verified": maths_verified,
    }


# ============================================================================
# MAIN UNIFIED PARSER
# ============================================================================

def parse_shp_text(
    text: str,
    annexure_total: Optional[int] = None,
    lockin_locked_hint: Optional[int] = None
) -> Dict:
    """
    Unified SHP parser that cascades through all 8 strategies.
    
    Args:
        text: Java-extracted text from SHP PDF
        annexure_total: Known total from lock-in (for validation/hints)
        lockin_locked_hint: Known locked shares from lock-in
    
    Returns:
        Dict with:
            - promoter_shares: int
            - public_shares: int
            - other_shares: int (sum of C1+C2+C3)
            - total_shares: int
            - locked_shares: int
            - strategy_used: str
            - total_verified: bool
            - validation_errors: list
    """
    strategy_results = {
        "spatial_columns": False,
        "fixed_positions": False,
        "position_based": False,
        "sequential": False,
        "boundary_detection": False,
        "column_count_validation": False,
        "simple_position": False,
        "reverse_order": False,
    }

    promoter_line, promoter_pattern = find_line_and_pattern(text, SHP_PATTERNS_A)
    public_line, public_pattern = find_line_and_pattern(text, SHP_PATTERNS_B)
    other_line, other_pattern = find_line_and_pattern(text, SHP_PATTERNS_C)
    total_line = find_total_line(text)

    # Strategy 1: Spatial Columns
    columns = detect_columns_from_whitespace(total_line) if total_line else None
    if columns:
        result = extract_using_spatial_columns(
            promoter_line, public_line, other_line, total_line,
            columns, annexure_total, lockin_locked_hint
        )
        if result and result.get('total_verified'):
            strategy_results["spatial_columns"] = True
            result["strategy_used"] = "spatial_columns"
            result["strategy_results"] = strategy_results
            result["matched_patterns"] = {
                "promoter": promoter_pattern,
                "public": public_pattern,
                "other": other_pattern
            }
            return result

    # Strategy 2: Fixed Positions
    result = extract_using_fixed_positions(
        promoter_line, public_line, other_line, total_line,
        annexure_total, lockin_locked_hint
    )
    if result and result.get('total_verified'):
        strategy_results["fixed_positions"] = True
        result["strategy_used"] = "fixed_positions"
        result["strategy_results"] = strategy_results
        result["matched_patterns"] = {
            "promoter": promoter_pattern,
            "public": public_pattern,
            "other": other_pattern
        }
        return result

    # Strategy 3: Position Based (from Total)
    if annexure_total:
        result = extract_shp_using_position_from_total(text, annexure_total, lockin_locked_hint)
        if result and result.get('total_verified'):
            strategy_results["position_based"] = True
            result["strategy_used"] = "position_based"
            result["strategy_results"] = strategy_results
            result["matched_patterns"] = {"promoter": None, "public": None, "other": None}
            return result

    # Strategy 4: Sequential (Pattern-based)
    result = extract_shp_values_from_text(text, annexure_total)
    if result and result.get('all_values_found') and result.get('maths_verified'):
        strategy_results["sequential"] = True
        result["strategy_used"] = "sequential"
        result["strategy_results"] = strategy_results
        return result

    # Strategy 5: Boundary Detection
    result = extract_shp_using_boundary_detection(text, annexure_total, lockin_locked_hint)
    if result and result.get('total_verified'):
        strategy_results["boundary_detection"] = True
        result["strategy_used"] = "boundary_detection"
        result["strategy_results"] = strategy_results
        return result

    # Strategy 6: Column Count Validation
    result = extract_shp_with_column_count_validation(text, annexure_total, lockin_locked_hint)
    if result and result.get('total_verified'):
        strategy_results["column_count_validation"] = True
        result["strategy_used"] = "column_count_validation"
        result["strategy_results"] = strategy_results
        return result

    # Strategy 7: Simple Position (Fallback)
    result = extract_shp_using_simple_position(text, annexure_total, lockin_locked_hint)
    strategy_results["simple_position"] = True
    result["strategy_used"] = "simple_position"
    result["strategy_results"] = strategy_results
    return result

    # Strategy 8: Reverse Order (if all else fails and we have known_total)
    # Note: This is rarely needed, only for very unusual layouts
    # Uncomment if needed for edge cases:
    # if annexure_total:
    #     result = extract_shp_reverse_order(text, annexure_total, lockin_locked_hint)
    #     if result:
    #         strategy_results["reverse_order"] = True
    #         result["strategy_used"] = "reverse_order"
    #         result["strategy_results"] = strategy_results
    #         return result


# ============================================================================
# VALIDATION FUNCTION
# ============================================================================

def validate_shp_result(shp_data: dict, lockin_locked_sum: int = None) -> Tuple[bool, List[str]]:
    """
    Validate SHP extraction result.
    
    Args:
        shp_data: Result from parse_shp_text()
        lockin_locked_sum: Known locked sum from lock-in (optional)
    
    Returns:
        Tuple of (is_valid, list of reasons)
    """
    reasons = []
    
    if not shp_data:
        reasons.append("No SHP data")
        return False, reasons
    
    promoter = shp_data.get("promoter_shares")
    public = shp_data.get("public_shares")
    other = shp_data.get("other_shares")
    total = shp_data.get("total_shares")
    locked = shp_data.get("shp_locked_total")
    
    if promoter is None:
        reasons.append("Promoter shares not found")
    if public is None:
        reasons.append("Public shares not found")
    if total is None:
        reasons.append("Total shares not found")
    
    if reasons:
        return False, reasons
    
    # Validate math: promoter + public + other = total
    other_val = other if other is not None else 0
    calculated_sum = promoter + public + other_val
    
    if total and calculated_sum != total:
        reasons.append(f"Math mismatch: {promoter} + {public} + {other_val} = {calculated_sum} != {total}")
        return False, reasons
    
    # Validate against lock-in locked sum if provided
    if lockin_locked_sum is not None and locked is not None:
        if locked != lockin_locked_sum:
            reasons.append(f"SHP locked {locked} != lock-in locked {lockin_locked_sum}")
            return False, reasons
    
    return True, reasons


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python shp_parser_unified.py <text_file> [known_total] [known_locked]")
        sys.exit(1)

    text_file = sys.argv[1]
    known_total = int(sys.argv[2]) if len(sys.argv) >= 3 else None
    known_locked = int(sys.argv[3]) if len(sys.argv) >= 4 else None

    with open(text_file, 'r', encoding='utf-8') as f:
        text = f.read()

    result = parse_shp_text(text, known_total, known_locked)
    print(result)
