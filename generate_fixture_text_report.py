"""
Generate concise text report from fixture files
Shows key metrics and errors for efficient debugging.
"""
from pathlib import Path
from lockin_parser_production_unified import parse_lockin_table, parse_bse_text

FIXTURES_DIR = "fixtures"
OUTPUT_FILE = "fixture_report.txt"

def parse_fixture(fixture_path):
    """Parse a fixture file and return results."""
    with open(fixture_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Determine parser based on parent directory
    exchange = fixture_path.parent.name.upper()
    if exchange == 'BSE':
        result = parse_bse_text(text)
    else:  # NSE
        result = parse_lockin_table(text)

    return exchange, result

def generate_text_report():
    """Generate text report from all fixtures."""
    fixtures_path = Path(FIXTURES_DIR)

    if not fixtures_path.exists():
        print(f"Error: Fixtures directory not found: {fixtures_path}")
        return

    # Scan both nse/ and bse/ subdirectories
    nse_files = sorted((fixtures_path / "nse").glob("*.txt")) if (fixtures_path / "nse").exists() else []
    bse_files = sorted((fixtures_path / "bse").glob("*.txt")) if (fixtures_path / "bse").exists() else []
    fixture_files = nse_files + bse_files

    if not fixture_files:
        print("No fixture files found!")
        return

    # Start text report
    lines = []
    lines.append("=" * 100)
    lines.append(f"FIXTURE TEST REPORT - Total: {len(fixture_files)} (NSE: {len(nse_files)}, BSE: {len(bse_files)})")
    lines.append("=" * 100)
    lines.append("")

    # Track stats
    total_pass = 0
    total_fail = 0
    total_mismatch = 0
    total_distinctive_errors = 0

    # Process each fixture
    for fixture_file in fixture_files:
        fixture_name = f"{fixture_file.parent.name}/{fixture_file.name}"

        try:
            exchange, result = parse_fixture(fixture_file)
            rows = result.get('rows', [])

            total_rows = len(rows)
            free_count = sum(1 for r in rows if r.get('is_free', False))
            locked_count = total_rows - free_count
            computed_total = sum(r['shares'] for r in rows)
            declared_total = result.get('declared_total')

            # Check for match
            match = computed_total == declared_total if declared_total else None

            # Check distinctive numbers
            distinctive_errors = 0
            error_details = []
            for i, r in enumerate(rows):
                from_num = r.get('from', 0)
                to_num = r.get('to', 0)
                if from_num and to_num:
                    expected_shares = to_num - from_num + 1
                    if expected_shares != r['shares']:
                        distinctive_errors += 1
                        if len(error_details) < 3:  # Show first 3 errors
                            error_details.append(f"  Row {i+1}: {r['shares']:,} ≠ {expected_shares:,}")

            # Determine status
            if distinctive_errors > 0:
                status = "✗ DISTINCTIVE ERROR"
                total_fail += 1
                total_distinctive_errors += distinctive_errors
            elif declared_total and computed_total != declared_total:
                status = "⚠ TOTAL MISMATCH"
                total_mismatch += 1
            else:
                status = "✓ PASS"
                total_pass += 1

            # Format line
            declared_str = f"{declared_total:,}" if declared_total else "N/A"
            match_str = "✓" if match else ("✗" if match is not None else "-")

            lines.append(f"{status:25} {fixture_name:45} Rows:{total_rows:3} Free:{free_count:3} Locked:{locked_count:3}")
            lines.append(f"{'':25} Computed:{computed_total:12,} Declared:{declared_str:12} {match_str}")

            if distinctive_errors > 0:
                lines.append(f"{'':25} Distinctive Errors: {distinctive_errors}")
                for detail in error_details:
                    lines.append(detail)
                if distinctive_errors > 3:
                    lines.append(f"  ... +{distinctive_errors - 3} more errors")

            lines.append("")

        except Exception as e:
            status = "✗ PARSE ERROR"
            total_fail += 1
            lines.append(f"{status:25} {fixture_name:45}")
            lines.append(f"{'':25} {str(e)}")
            lines.append("")

    # Summary
    lines.append("=" * 100)
    lines.append(f"SUMMARY: PASS={total_pass}, MISMATCH={total_mismatch}, FAIL={total_fail}, Total Distinctive Errors={total_distinctive_errors}")
    lines.append("=" * 100)

    # Write to file
    report_text = "\n".join(lines)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(report_text)

    print(f"Text report generated: {Path(OUTPUT_FILE).absolute()}")
    print(f"\nSummary: PASS={total_pass}, MISMATCH={total_mismatch}, FAIL={total_fail}")
    if total_distinctive_errors > 0:
        print(f"⚠ Total Distinctive Errors: {total_distinctive_errors}")

    # Also print to console
    print("\n" + report_text)

if __name__ == '__main__':
    generate_text_report()
