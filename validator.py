"""
Validation Rules Implementation
Implements RULE1-RULE10 for lock-in and SHP data validation
"""

from typing import List
from models import LockinData, SHPData, ValidationResult


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


def validate_rule6(lockin: LockinData, anchor_letter_url: str) -> ValidationResult:
    """
    RULE 6: Anchor validation
    If anchor_letter_url exists → must find anchor rows
    If anchor_letter_url is NULL → must NOT find anchor rows
    """
    # Count anchor rows
    anchor_rows = [
        row for row in lockin.rows
        if row.bucket.value in ('ANCHOR_90DAYS', 'ANCHOR_30DAYS')
    ]
    anchor_count = len(anchor_rows)
    has_anchor_rows = anchor_count > 0

    # Check anchor_letter_url
    has_anchor_url = anchor_letter_url is not None and anchor_letter_url.strip() != ''

    # Validation logic
    if has_anchor_url and has_anchor_rows:
        # Expected: anchor URL exists and anchor rows found
        passed = True
        message = f"Anchor letter URL exists and {anchor_count} anchor row(s) found"
    elif not has_anchor_url and not has_anchor_rows:
        # Expected: no anchor URL and no anchor rows
        passed = True
        message = "No anchor letter URL and no anchor rows (correct)"
    elif has_anchor_url and not has_anchor_rows:
        # Error: anchor URL exists but no anchor rows found
        passed = False
        message = f"Anchor letter URL exists but no anchor rows found (expected anchor)"
    else:  # not has_anchor_url and has_anchor_rows
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


def validate_all_rules(
    lockin: LockinData,
    shp: SHPData,
    declared_total: int,
    anchor_letter_url: str = None,
    db_computed_total: int = None,
    db_declared_total: int = None,
    parsed_declared_total: int = None
) -> List[ValidationResult]:
    """
    Run all validation rules (RULE1-RULE6)

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
    results.append(validate_rule6(lockin, anchor_letter_url))

    # Note: RULE7-RULE10 are for GEMINI extraction (Step 5)
    # Will be implemented when --GEMAPPROVED flag is used

    return results


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
