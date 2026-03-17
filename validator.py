"""
Validation Rules Implementation
Implements RULE1-RULE10 for lock-in and SHP data validation
"""

from typing import List
from models import LockinData, SHPData, ValidationResult, LockBucket, RowStatus


def validate_rule1(lockin: LockinData) -> ValidationResult:
    """
    RULE 1: Locked shares + Free Shares = Total shares
    Lock-in PDF validation
    """
    expected = lockin.computed_total
    actual = lockin.locked_total + lockin.free_total

    passed = (expected == actual)

    message = (
        f"Locked ({lockin.locked_total:,}) + Free ({lockin.free_total:,}) = {actual:,} "
        f"{'==' if passed else '!='} Computed Total ({expected:,})"
    )

    return ValidationResult(
        rule_id="RULE1",
        passed=passed,
        message=message,
        expected=expected,
        actual=actual
    )


def validate_rule2(
    lockin: LockinData,
    declared_total: int,
    db_computed_total: int = None,
    db_declared_total: int = None,
    parsed_declared_total: int = None,
    shp_total: int = None
) -> ValidationResult:
    """
    RULE 2: Total Shares = Computed Shares (from declared total in master)
    Lock-in PDF validation with hints from DB and parsed data

    Supports auto-override when:
    - PDF has declared_total (from TOTAL line)
    - declared_total == computed_total (RULE 1 passes)
    - declared_total == SHP total (RULE 3 passes)
    - Master table differs -> Use PDF value (auto-override)

    Args:
        lockin: Parsed lock-in data
        declared_total: Declared total from sme_ipo_master
        db_computed_total: Computed total from DB (hint)
        db_declared_total: Declared total from DB (hint, may differ from master)
        parsed_declared_total: Declared total extracted from PDF (hint)
        shp_total: Total from SHP (for auto-override check)
    """
    expected = declared_total
    actual = lockin.computed_total

    passed = (expected == actual)

    # Build hint information
    hints = []

    # Hint 1: Check if DB totals match (strong indicator of correctness)
    if db_computed_total is not None and db_declared_total is not None:
        db_match = (db_computed_total == db_declared_total)
        if db_match:
            hints.append(f"DB: computed={db_computed_total:,} == declared={db_declared_total:,} MATCH")
        else:
            hints.append(f"DB: computed={db_computed_total:,} != declared={db_declared_total:,}")

    # Hint 2: Check if parsed declared matches parsed computed
    if parsed_declared_total is not None:
        parsed_match = (parsed_declared_total == actual)
        if parsed_match:
            hints.append(f"Parsed: declared={parsed_declared_total:,} == computed={actual:,} MATCH")
        else:
            hints.append(f"Parsed: declared={parsed_declared_total:,} != computed={actual:,}")

    # Auto-override logic
    can_override = False
    auto_override = False
    override_reason = None

    if not passed and parsed_declared_total is not None:
        # Check auto-override conditions:
        # 1. PDF declared == computed (RULE 1 passes)
        pdf_internally_consistent = (parsed_declared_total == actual)

        # 2. PDF declared == SHP total (RULE 3 passes)
        shp_matches = (shp_total is not None and parsed_declared_total == shp_total)

        if pdf_internally_consistent and shp_matches:
            # All checks pass - PDF is source of truth, master table is wrong
            auto_override = True
            override_reason = f"Auto-override: PDF internally consistent ({parsed_declared_total:,}) and matches SHP total. Master table ({expected:,}) should be updated."
            passed = True  # Override the failure
            can_override = True
        elif pdf_internally_consistent or shp_matches:
            # Partial match - allow manual override
            can_override = True

    # Build message
    message = (
        f"Computed Total ({actual:,}) {'==' if (expected == actual) else '!='} "
        f"Declared Total ({expected:,})"
    )

    # Add hints if available
    if hints:
        message += f" | Hints: {'; '.join(hints)}"

    # Add override info
    if auto_override:
        message += f" | AUTO-OVERRIDE: {override_reason}"
    elif can_override and not passed:
        message += " | CAN_OVERRIDE: PDF internally consistent, manual review recommended"

    return ValidationResult(
        rule_id="RULE2",
        passed=passed,
        message=message,
        expected=expected,
        actual=actual,
        can_override=can_override,
        overridden=auto_override,
        override_reason=override_reason
    )


def validate_rule3(shp: SHPData, lockin: LockinData) -> ValidationResult:
    """
    RULE 3: SHP Total Shares = Lock-in Total Shares
    Cross-verification between SHP and Lock-in
    """
    expected = lockin.computed_total
    actual = shp.total_shares

    passed = (expected == actual)

    message = (
        f"SHP Total ({actual:,}) {'==' if passed else '!='} "
        f"Lock-in Total ({expected:,})"
    )

    return ValidationResult(
        rule_id="RULE3",
        passed=passed,
        message=message,
        expected=expected,
        actual=actual
    )


def validate_rule4(shp: SHPData, lockin: LockinData) -> ValidationResult:
    """
    RULE 4: SHP Locked Shares = Lock-in Locked Shares
    Cross-verification between SHP and Lock-in
    """
    expected = lockin.locked_total
    actual = shp.locked_shares

    passed = (expected == actual)

    message = (
        f"SHP Locked ({actual:,}) {'==' if passed else '!='} "
        f"Lock-in Locked ({expected:,})"
    )

    return ValidationResult(
        rule_id="RULE4",
        passed=passed,
        message=message,
        expected=expected,
        actual=actual
    )


def validate_rule5(shp: SHPData) -> ValidationResult:
    """
    RULE 5: Promoter + Public + Others = Total Shares
    SHP internal consistency check
    """
    expected = shp.total_shares
    actual = shp.promoter_shares + shp.public_shares + shp.others_shares

    passed = (expected == actual)

    message = (
        f"Promoter ({shp.promoter_shares:,}) + Public ({shp.public_shares:,}) + "
        f"Others ({shp.others_shares:,}) = {actual:,} {'==' if passed else '!='} "
        f"SHP Total ({expected:,})"
    )

    return ValidationResult(
        rule_id="RULE5",
        passed=passed,
        message=message,
        expected=expected,
        actual=actual
    )


def validate_rule6(
    lockin: LockinData,
    anchor_letter_url: str,
    exchange: str = None,
    allotment_date=None,
) -> ValidationResult:
    """
    RULE 6: Anchor validation
    If anchor_letter_url exists → must find anchor rows
    If anchor_letter_url is NULL → must NOT find anchor rows
    """
    anchor_30_count = sum(1 for row in lockin.rows if row.bucket.value == 'anchor_30')
    anchor_90_count = sum(1 for row in lockin.rows if row.bucket.value == 'anchor_90')
    anchor_count = anchor_30_count + anchor_90_count
    has_anchor_rows = anchor_count > 0

    # Check anchor_letter_url
    has_anchor_url = anchor_letter_url is not None and anchor_letter_url.strip() != ''

    # Validation logic
    if has_anchor_url and anchor_30_count > 0 and anchor_90_count > 0:
        # Expected: anchor URL exists and BOTH anchor buckets found
        passed = True
        message = (
            "Anchor letter URL exists and both anchor buckets found "
            f"(anchor_30={anchor_30_count}, anchor_90={anchor_90_count})"
        )
    elif has_anchor_url:
        # Error: anchor URL exists but one/both anchor bucket(s) missing
        passed = False
        missing = []
        if anchor_30_count == 0:
            missing.append("anchor_30")
        if anchor_90_count == 0:
            missing.append("anchor_90")
        message = (
            "Anchor letter URL exists but missing required anchor bucket(s): "
            f"{', '.join(missing)} (anchor_30={anchor_30_count}, anchor_90={anchor_90_count})"
        )
    elif not has_anchor_url and not has_anchor_rows:
        # Expected: no anchor URL and no anchor rows
        passed = True
        message = "No anchor letter URL and no anchor rows (correct)"
    else:  # not has_anchor_url and has_anchor_rows
        # Legacy NSE/BSE relaxation:
        # For older allotments (<= 2024-12-02), do not fail when anchor rows exist
        # but anchor letter URL is missing.
        legacy_cutoff = "2024-12-02"
        allotment_iso = allotment_date.isoformat() if hasattr(allotment_date, "isoformat") else (str(allotment_date) if allotment_date else None)
        ex_upper = (exchange or "").upper()
        is_legacy_exchange = (
            ex_upper in {"NSE", "BSE"}
            and allotment_iso is not None
            and allotment_iso <= legacy_cutoff
        )

        if is_legacy_exchange:
            passed = True
            message = (
                f"No anchor letter URL but {anchor_count} anchor row(s) found "
                f"(legacy {ex_upper} exception: allotment_date {allotment_iso} <= {legacy_cutoff})"
            )
        else:
            # Error: no anchor URL but anchor rows found
            passed = False
            message = f"No anchor letter URL but {anchor_count} anchor row(s) found (unexpected)"

    return ValidationResult(
        rule_id="RULE6",
        passed=passed,
        message=message,
        expected=1 if has_anchor_url else 0,
        actual=anchor_count
    )


def validate_rule7_bucket_calculated(lockin: LockinData) -> ValidationResult:
    """
    RULE 7: Bucket must be calculated for locked rows with lock-in upto date.
    """
    bad_rows = []
    for idx, row in enumerate(lockin.rows, start=1):
        if row.status == RowStatus.LOCKED and row.lockin_date_to is not None:
            if row.bucket == LockBucket.FREE:
                bad_rows.append((idx, row.shares, row.lockin_date_from, row.lockin_date_to))

    passed = len(bad_rows) == 0
    if passed:
        message = "All locked rows with lock-in dates have non-free buckets"
    else:
        preview = "; ".join(
            f"row#{i} shares={s:,} from={f} to={t}"
            for i, s, f, t in bad_rows[:5]
        )
        more = f" (+{len(bad_rows)-5} more)" if len(bad_rows) > 5 else ""
        message = f"Found {len(bad_rows)} locked row(s) with lock-in date but bucket=free: {preview}{more}"

    return ValidationResult(
        rule_id="RULE7",
        passed=passed,
        message=message,
        expected=0,
        actual=len(bad_rows),
        can_override=False,
    )


def validate_rule8_negative_days(lockin: LockinData, allotment_date=None) -> ValidationResult:
    """
    RULE 8: Negative lock period is invalid (manual override allowed).
    """
    bad_rows = []
    for idx, row in enumerate(lockin.rows, start=1):
        if row.status != RowStatus.LOCKED or row.lockin_date_to is None:
            continue
        start_date = row.lockin_date_from if row.lockin_date_from is not None else allotment_date
        if start_date is None:
            continue
        days = (row.lockin_date_to - start_date).days
        if days < 0:
            start_source = "lock_from" if row.lockin_date_from is not None else "allotment"
            bad_rows.append((idx, row.shares, start_date, row.lockin_date_to, days, start_source))

    passed = len(bad_rows) == 0
    if passed:
        message = "No negative lock-period rows found"
    else:
        preview = "; ".join(
            f"row#{i} shares={s:,} start({src})={f} to={t} days={d}"
            for i, s, f, t, d, src in bad_rows[:5]
        )
        more = f" (+{len(bad_rows)-5} more)" if len(bad_rows) > 5 else ""
        message = f"Found {len(bad_rows)} row(s) with negative lock period: {preview}{more}"

    return ValidationResult(
        rule_id="RULE8",
        passed=passed,
        message=message,
        expected=0,
        actual=len(bad_rows),
        can_override=True,  # Explicitly overrideable for rare date/OCR edge cases
    )


def validate_rule10_locked_rows_have_valid_upto(lockin: LockinData) -> ValidationResult:
    """
    RULE 10: Every LOCKED row must have a parseable lock-in upto date.

    Prevents false finalization when OCR/date typos produce locked rows with no
    lockin_date_to (e.g., "Juny 19, 2028").
    """
    bad_rows = []
    for idx, row in enumerate(lockin.rows, start=1):
        if row.status != RowStatus.LOCKED:
            continue
        if row.lockin_date_to is None:
            bad_rows.append((idx, row.shares, row.security_type, row.share_form))

    passed = len(bad_rows) == 0
    if passed:
        message = "All locked rows have valid lock-in upto dates"
    else:
        preview = "; ".join(
            f"row#{i} shares={s:,} type={t or '-'} form={f or '-'}"
            for i, s, t, f in bad_rows[:5]
        )
        more = f" (+{len(bad_rows)-5} more)" if len(bad_rows) > 5 else ""
        message = (
            f"Found {len(bad_rows)} locked row(s) with missing/invalid lock-in upto date: "
            f"{preview}{more}"
        )

    return ValidationResult(
        rule_id="RULE10",
        passed=passed,
        message=message,
        expected=0,
        actual=len(bad_rows),
        can_override=False,
    )


def validate_all_rules(
    lockin: LockinData,
    shp: SHPData,
    declared_total: int,
    anchor_letter_url: str = None,
    db_computed_total: int = None,
    db_declared_total: int = None,
    parsed_declared_total: int = None,
    allotment_date=None,
    exchange: str = None,
) -> List[ValidationResult]:
    """
    Run all validation rules (RULE1-RULE10 except post-save DB rule)

    Args:
        lockin: Lock-in extraction data
        shp: SHP extraction data
        declared_total: Declared total from sme_ipo_master
        anchor_letter_url: Anchor letter URL from sme_ipo_master
        db_computed_total: Computed total from DB (hint for RULE2)
        db_declared_total: Declared total from DB (hint for RULE2)
        parsed_declared_total: Declared total extracted from PDF (hint for RULE2)

    Returns:
        List of ValidationResult for each rule
    """
    results = []

    # Lock-in PDF rules
    results.append(validate_rule1(lockin))
    results.append(validate_rule2(
        lockin,
        declared_total,
        db_computed_total=db_computed_total,
        db_declared_total=db_declared_total,
        parsed_declared_total=parsed_declared_total,
        shp_total=shp.total_shares if shp else None
    ))

    # SHP PDF rules
    results.append(validate_rule5(shp))

    # Cross-verification rules
    results.append(validate_rule3(shp, lockin))
    results.append(validate_rule4(shp, lockin))

    # Anchor validation
    results.append(validate_rule6(lockin, anchor_letter_url, exchange=exchange, allotment_date=allotment_date))

    # Additional lock-in integrity rules
    results.append(validate_rule7_bucket_calculated(lockin))
    results.append(validate_rule8_negative_days(lockin, allotment_date=allotment_date))
    results.append(validate_rule10_locked_rows_have_valid_upto(lockin))

    # Note: RULE9_DB_BUCKET is post-save DB persistence check in app.py
    # Note: Additional GEMINI-specific rules are Step 5
    # Will be implemented when --GEMAPPROVED flag is used

    return results


def get_extraction_strategies(lockin: LockinData, shp: SHPData) -> dict:
    """
    [STRATEGY-TRACKING 2026-03-09] Get which strategies were used for extraction
    
    Args:
        lockin: Lock-in extraction data
        shp: SHP extraction data
    
    Returns:
        Dict with strategy info for JSON storage
    """
    return {
        'lockin_strategy': lockin.strategy if lockin else None,
        'shp_strategy': shp.strategy_used if shp else None,
    }


def main():
    """Test validator with sample data"""
    from models import LockinRow, RowStatus, LockBucket
    from datetime import date

    # Sample lock-in data
    lockin = LockinData(rows=[
        LockinRow(shares=1000000, status=RowStatus.LOCKED, bucket=LockBucket.YEARS_3_PLUS),
        LockinRow(shares=500000, status=RowStatus.LOCKED, bucket=LockBucket.ANCHOR_90DAYS),
        LockinRow(shares=300000, status=RowStatus.FREE, bucket=LockBucket.FREE),
    ])
    lockin.compute_totals()

    # Sample SHP data
    shp = SHPData(
        total_shares=1800000,
        locked_shares=1500000,
        promoter_shares=1000000,
        public_shares=600000,
        others_shares=200000
    )

    declared_total = 1800000
    anchor_url = "https://example.com/anchor.pdf"

    # Run validations
    print("=" * 70)
    print("Validation Test")
    print("=" * 70)

    results = validate_all_rules(lockin, shp, declared_total, anchor_url)

    for result in results:
        icon = "✓" if result.passed else "✗"
        print(f"\n{icon} {result.rule_id}: {result.message}")

    # Summary
    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)
    print(f"\n{'=' * 70}")
    print(f"Summary: {passed_count}/{total_count} rules passed")

    if passed_count == total_count:
        print("✅ ALL RULES PASSED - Ready for finalization")
    else:
        failed = [r.rule_id for r in results if not r.passed]
        print(f"❌ Failed rules: {', '.join(failed)}")


if __name__ == "__main__":
    main()
