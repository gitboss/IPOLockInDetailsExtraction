"""
SHP (Shareholding Pattern) Parser
Unified parser for both NSE and BSE SHP TXT files
Uses CASCADE of 8 strategies from production code
"""

from pathlib import Path
import re
from models import SHPData
from shp_parser_production_unified import extract_shp_values_from_text_java as extract_shp_with_cascade


def _is_result_math_valid(result: dict) -> bool:
    total = result.get('total_shares')
    promoter = result.get('promoter_shares')
    public = result.get('public_shares')
    other = result.get('other_shares')
    if total is None or promoter is None or public is None or other is None:
        return False
    try:
        return int(promoter) + int(public) + int(other) == int(total)
    except (TypeError, ValueError):
        return False


def _reconcile_other_shares(result: dict) -> dict:
    """
    Backward-compatible reconciliation:
    If strategy produced promoter/public + total but missing/incorrect others,
    fill others via residual math:
        other = total - promoter - public

    This is intentionally conservative and only runs when promoter/public/total
    are present and residual is non-negative.
    """
    total = result.get('total_shares')
    promoter = result.get('promoter_shares')
    public = result.get('public_shares')
    other = result.get('other_shares')

    if total is None or promoter is None or public is None:
        return result

    try:
        total_i = int(total)
        promoter_i = int(promoter)
        public_i = int(public)
        other_i = int(other) if other is not None else 0
    except (TypeError, ValueError):
        return result

    if total_i <= 0 or promoter_i < 0 or public_i < 0:
        return result

    # Guard: avoid masking obviously bad parses (e.g., both zero)
    if promoter_i == 0 and public_i == 0:
        return result

    current_sum = promoter_i + public_i + other_i
    needs_reconcile = (other is None) or (other_i == 0) or (current_sum != total_i)
    if not needs_reconcile:
        return result

    residual = total_i - promoter_i - public_i
    if residual < 0:
        return result

    result = dict(result)  # don't mutate caller reference in-place
    result['other_shares'] = residual
    result['other_found'] = residual > 0
    result['all_values_found'] = (
        result.get('promoter_shares') is not None and
        result.get('public_shares') is not None and
        result.get('other_shares') is not None
    )
    result['maths_verified'] = ((promoter_i + public_i + residual) == total_i)
    return result


def _extract_int_tokens(line: str) -> list[int]:
    vals = []
    for m in re.findall(r'(?<!\d)\d[\d,]*(?!\d)', line or ''):
        try:
            vals.append(int(m.replace(',', '')))
        except ValueError:
            pass
    return vals


def _number_exists_in_text(text: str, value: int) -> bool:
    if value is None:
        return False
    target = int(value)
    for token in _extract_int_tokens(text):
        if token == target:
            return True
    return False


def _looks_implausible_shp_parse(result: dict, known_total: int = None, known_locked: int = None) -> bool:
    total = result.get('total_shares')
    promoter = result.get('promoter_shares')
    public = result.get('public_shares')
    shp_locked = result.get('shp_locked_total')

    try:
        total_i = int(total) if total is not None else 0
        promoter_i = int(promoter) if promoter is not None else 0
        public_i = int(public) if public is not None else 0
        shp_locked_i = int(shp_locked) if shp_locked is not None else 0
        known_total_i = int(known_total) if known_total is not None else None
        known_locked_i = int(known_locked) if known_locked is not None else None
    except (TypeError, ValueError):
        return True

    # Clearly suspicious: tiny promoter/public against very large total.
    if total_i >= 100000 and (promoter_i + public_i) > 0 and (promoter_i + public_i) <= 10000:
        return True

    # If hints are present and parse deviates strongly, allow recovery attempt.
    if known_total_i is not None and total_i > 0 and total_i != known_total_i:
        return True
    if known_locked_i is not None and shp_locked_i > 0 and shp_locked_i != known_locked_i:
        return True

    return not _is_result_math_valid(result)


def _recover_from_ab_total_lines(
    text: str,
    preferred_total: int | None,
    declared_total: int,
    known_locked: int,
    base_result: dict
) -> dict | None:
    lines = text.splitlines()
    a_line = None
    b_line = None
    total_line = None

    for ln in lines:
        l = ln.strip()
        if not l:
            continue
        if a_line is None and re.search(r'\(A\)', l, re.IGNORECASE) and re.search(r'promoter', l, re.IGNORECASE):
            a_line = l
        if b_line is None and re.search(r'\(B\)', l, re.IGNORECASE) and re.search(r'public', l, re.IGNORECASE):
            b_line = l
        if total_line is None and re.search(r'total\s*a\+b', l, re.IGNORECASE):
            total_line = l
        elif total_line is None and re.match(r'^\s*total\b', l, re.IGNORECASE):
            total_line = l

    if not a_line or not b_line:
        return None

    a_nums = _extract_int_tokens(a_line)
    b_nums = _extract_int_tokens(b_line)
    if not a_nums or not b_nums:
        return None

    promoter = max(a_nums)
    public = max(b_nums)
    total = int(preferred_total) if preferred_total is not None else int(declared_total)
    others = total - promoter - public
    if others < 0:
        return None

    recovered = dict(base_result)
    recovered['promoter_shares'] = promoter
    recovered['public_shares'] = public
    recovered['other_shares'] = others
    recovered['total_shares'] = total
    recovered['promoter_found'] = True
    recovered['public_found'] = True
    recovered['other_found'] = True
    recovered['all_values_found'] = True
    recovered['maths_verified'] = True
    recovered['strategy_used'] = f"{base_result.get('strategy_used') or 'unknown'}+hint_recovery"

    # Keep locked shares conservative: prefer known_locked only when explicitly present in text.
    if known_locked is not None and _number_exists_in_text(text, int(known_locked)):
        recovered['shp_locked_total'] = int(known_locked)
    elif total_line:
        t_nums = _extract_int_tokens(total_line)
        if t_nums:
            recovered['shp_locked_total'] = max(t_nums)

    return recovered


def _apply_locked_hint_fallback(result: dict, text: str, known_locked: int | None) -> dict:
    """
    Conservative fallback for SHP locked shares:
    if parsed SHP locked appears as a tiny artifact (e.g. from split percent token)
    and known_locked exists verbatim in SHP text, trust known_locked.
    """
    if known_locked is None:
        return result
    try:
        known_locked_i = int(known_locked)
    except (TypeError, ValueError):
        return result
    if known_locked_i <= 0:
        return result
    if not _number_exists_in_text(text, known_locked_i):
        return result

    current = result.get('shp_locked_total')
    try:
        current_i = int(current) if current is not None else 0
    except (TypeError, ValueError):
        current_i = 0

    # Trigger only when current looks obviously implausible compared to known hint.
    tiny_artifact = current_i <= 100000 and known_locked_i >= 1000000
    very_small_ratio = current_i > 0 and known_locked_i >= 100000 and (current_i * 100) < known_locked_i
    if current_i == known_locked_i or not (tiny_artifact or very_small_ratio or current_i == 0):
        return result

    patched = dict(result)
    patched['shp_locked_total'] = known_locked_i
    return patched


def parse_shp_file(txt_path: Path, known_total: int = None, total_hint_computed: int = None, known_locked: int = None) -> SHPData:
    """
    Parse SHP TXT file using CASCADE of 8 strategies (unified for NSE and BSE)

    Args:
        txt_path: Path to SHP *_java.txt file
        known_total: Declared total from sme_ipo_master (may have inaccuracies)
        total_hint_computed: Computed total from lock-in PDF (most reliable)
        known_locked: Known locked shares from lock-in (optional)

    Returns:
        SHPData with total, locked, promoter, public, others

    Raises:
        FileNotFoundError: If txt_path doesn't exist
        ValueError: If extraction fails with all strategies
    """
    if not txt_path.exists():
        raise FileNotFoundError(f"SHP TXT file not found: {txt_path}")

    # Read file
    with open(txt_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Extract using cascade of 8 strategies
    # [FALLBACK 2026-03-09] Pass total_hint_computed as fallback
    result = extract_shp_with_cascade(
        text=text,
        annexure_total=known_total,
        lockin_locked_hint=known_locked,
        total_hint_computed=total_hint_computed  # [FALLBACK 2026-03-09]
    )

    path_norm = str(txt_path).lower().replace('\\', '/')

    # Backward-compatible dual-hint arbitration (BSE only):
    # If DB total and computed total conflict, and selected result aligns to DB total,
    # try one alternate parse anchored to computed total. Switch only when alternate is
    # mathematically valid and aligns to computed total.
    if (
        '/bse/' in path_norm
        and known_total is not None
        and total_hint_computed is not None
        and known_total != total_hint_computed
        and result.get('total_shares') == known_total
    ):
        alt_result = extract_shp_with_cascade(
            text=text,
            annexure_total=total_hint_computed,
            lockin_locked_hint=known_locked,
            total_hint_computed=known_total
        )
        alt_result = _reconcile_other_shares(alt_result)
        if alt_result.get('total_shares') == total_hint_computed and _is_result_math_valid(alt_result):
            print(
                f"ℹ️  BSE dual-hint arbitration: switched SHP total from DB hint "
                f"{known_total:,} to computed hint {total_hint_computed:,}"
            )
            result = alt_result

    # Backward-compatible enhancement for NSE/BSE:
    # reconcile "others" only when promoter/public/total are present.
    if '/bse/' in path_norm or '/nse/' in path_norm:
        reconciled = _reconcile_other_shares(result)
        if reconciled is not result and reconciled.get('other_shares') != result.get('other_shares'):
            ex = "BSE" if '/bse/' in path_norm else "NSE"
            print(f"ℹ️  {ex} reconciliation: other_shares adjusted to {reconciled.get('other_shares'):,} by residual math")
        result = reconciled

    # Backward-compatible hint recovery:
    # Run only after normal cascade/reconciliation and only when current parse looks implausible.
    # Guarded by explicit hint existence in SHP text to avoid changing normal successful cases.
    if known_total is not None and known_locked is not None:
        declared_exists = _number_exists_in_text(text, int(known_total))
        locked_exists = _number_exists_in_text(text, int(known_locked))
        if declared_exists and locked_exists and _looks_implausible_shp_parse(result, known_total, known_locked):
            preferred_total = result.get('total_shares')
            try:
                preferred_total = int(preferred_total) if preferred_total is not None else None
            except (TypeError, ValueError):
                preferred_total = None
            recovered = _recover_from_ab_total_lines(
                text,
                preferred_total,
                int(known_total),
                int(known_locked),
                result
            )
            if recovered and _is_result_math_valid(recovered):
                print(
                    "ℹ️  SHP hint recovery applied: declared+locked hints found in SHP text; "
                    "recovered promoter/public/others from A/B/Total lines"
                )
                result = recovered

    # Locked-hint fallback: fix obvious percentage-fragment artifacts (e.g., 9829 instead of 14,344,200).
    locked_patched = _apply_locked_hint_fallback(result, text, known_locked)
    if locked_patched is not result and locked_patched.get('shp_locked_total') != result.get('shp_locked_total'):
        print(
            f"ℹ️  SHP locked fallback applied: corrected SHP locked from "
            f"{int(result.get('shp_locked_total') or 0):,} to {int(locked_patched.get('shp_locked_total') or 0):,}"
        )
        result = locked_patched

    # Check if extraction succeeded
    if not result.get('all_values_found'):
        # Partial extraction - warn but continue
        print(f"⚠️  Warning: Partial SHP extraction from {txt_path.name}")
        print(f"   Strategy: {result.get('strategy_used')}")
        print(f"   Found: promoter={result.get('promoter_found')}, public={result.get('public_found')}, other={result.get('other_found')}")

    # Validate math if we have all values
    if result.get('promoter_shares') and result.get('public_shares'):
        computed_total = (result.get('promoter_shares') or 0) + \
                        (result.get('public_shares') or 0) + \
                        (result.get('other_shares') or 0)

        if result.get('total_shares'):
            diff = abs(computed_total - result.get('total_shares'))
            if diff > 100:  # More than 100 shares difference = problem
                print(f"⚠️  Warning: Math mismatch in {txt_path.name}")
                print(f"   Promoter+Public+Others ({computed_total:,}) != Total ({result.get('total_shares'):,})")

    # Create SHPData
    return SHPData(
        total_shares=result.get('total_shares') or 0,
        locked_shares=result.get('shp_locked_total') or 0,
        promoter_shares=result.get('promoter_shares') or 0,
        public_shares=result.get('public_shares') or 0,
        others_shares=result.get('other_shares') or 0,
        strategy_used=result.get('strategy_used'),  # [STRATEGY-TRACKING 2026-03-09]
    )


def main():
    """Test parser with sample file"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parser_shp.py <path_to_shp_java.txt> [declared_total] [computed_total] [known_locked]")
        print("Example: python parser_shp.py downloads/bse/pdf/shp/txt/544324-CITICHEM-Annexure-II_java.txt 1800000 1800000 1500000")
        sys.exit(1)

    txt_path = Path(sys.argv[1])
    known_total = int(sys.argv[2]) if len(sys.argv) >= 3 else None
    total_hint_computed = int(sys.argv[3]) if len(sys.argv) >= 4 else None
    known_locked = int(sys.argv[4]) if len(sys.argv) >= 5 else None

    print(f"Parsing SHP: {txt_path}")
    if known_total:
        print(f"Declared Total:  {known_total:,}")
    if total_hint_computed:
        print(f"Computed Total:  {total_hint_computed:,}")
    if known_locked:
        print(f"Known Locked:    {known_locked:,}")
    print("=" * 70)

    try:
        result = parse_shp_file(txt_path, known_total, total_hint_computed, known_locked)

        print(f"\n✓ SHP Data Extracted:")
        print(f"  Total Shares:    {result.total_shares:,}")
        print(f"  Locked Shares:   {result.locked_shares:,}")
        if result.total_shares > 0:
            print(f"  Promoter:        {result.promoter_shares:,} ({result.promoter_shares/result.total_shares*100:.1f}%)")
            print(f"  Public:          {result.public_shares:,} ({result.public_shares/result.total_shares*100:.1f}%)")
            print(f"  Others:          {result.others_shares:,} ({result.others_shares/result.total_shares*100:.1f}%)")
        else:
            print(f"  Promoter:        {result.promoter_shares:,}")
            print(f"  Public:          {result.public_shares:,}")
            print(f"  Others:          {result.others_shares:,}")

        # Validation
        computed = result.promoter_shares + result.public_shares + result.others_shares
        print(f"\n  Computed Sum:    {computed:,}")
        print(f"  Difference:      {abs(computed - result.total_shares):,}")

        # Show if known totals match
        if known_total:
            match = "✓" if result.total_shares == known_total else "✗"
            print(f"\n  {match} Total Match:    {result.total_shares:,} vs {known_total:,}")

        if known_locked:
            match = "✓" if result.locked_shares == known_locked else "✗"
            print(f"  {match} Locked Match:   {result.locked_shares:,} vs {known_locked:,}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
