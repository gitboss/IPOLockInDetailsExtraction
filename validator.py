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


def validate_rule2(lockin: LockinData, declared_total: int) -> ValidationResult:
    """
    RULE 2: Total Shares = Computed Shares (from declared total in master)
    Lock-in PDF validation
    """
    expected = declared_total
    actual = lockin.computed_total

    passed = (expected == actual)

    message = (
        f"Computed Total ({actual:,}) {'==' if passed else '!='} "
        f"Declared Total ({expected:,})"
    )

    return ValidationResult(
        rule_id="RULE2",
        passed=passed,
        message=message,
        expected=expected,
        actual=actual
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
    anchor_letter_url: str = None
) -> List[ValidationResult]:
    """
    Run all validation rules (RULE1-RULE6)

    Args:
        lockin: Lock-in extraction data
        shp: SHP extraction data
        declared_total: Declared total from sme_ipo_master
        anchor_letter_url: Anchor letter URL from sme_ipo_master

    Returns:
        List of ValidationResult for each rule
    """
    results = []

    # Lock-in PDF rules
    results.append(validate_rule1(lockin))
    results.append(validate_rule2(lockin, declared_total))

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
