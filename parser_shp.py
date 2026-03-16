"""
SHP (Shareholding Pattern) Parser
Unified parser for both NSE and BSE SHP TXT files
Uses CASCADE of 8 strategies from production code
"""

from pathlib import Path
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
