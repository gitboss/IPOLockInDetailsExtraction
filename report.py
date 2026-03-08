"""
Processing Report - View extracted data from database
Shows what was extracted and validated for each symbol
"""

import sys
from pathlib import Path
import json
import db


def get_processing_record(unique_symbol: str = None, processing_id: int = None):
    """Get processing record from database"""

    if processing_id:
        sql = "SELECT * FROM ipo_processing_log WHERE id = %s"
        params = (processing_id,)
    elif unique_symbol:
        sql = "SELECT * FROM ipo_processing_log WHERE unique_symbol = %s ORDER BY processed_at DESC LIMIT 1"
        params = (unique_symbol,)
    else:
        print("ERROR: Must provide either unique_symbol or processing_id")
        return None

    return db.execute_query(sql, params, fetch="one")


def get_lockin_rows(processing_log_id: int):
    """Get lock-in detail rows"""
    sql = """
        SELECT * FROM ipo_lockin_rows
        WHERE processing_log_id = %s
        ORDER BY row_order
    """
    return db.execute_query(sql, (processing_log_id,), fetch="all")


def display_report(record, rows):
    """Display formatted report"""

    print("=" * 80)
    print("PROCESSING REPORT")
    print("=" * 80)

    # Header
    print(f"\nSymbol:        {record['unique_symbol']}")
    print(f"Exchange:      {record['exchange']}")
    print(f"File:          {record['file_name']}")
    print(f"Status:        {record['status']}")
    print(f"Processed:     {record['processed_at']}")
    if record['finalized_at']:
        print(f"Finalized:     {record['finalized_at']}")

    print(f"\n{'-' * 80}")
    print("LOCK-IN EXTRACTION")
    print(f"{'-' * 80}")
    print(f"Computed Total:    {record['computed_total']:,} shares")
    print(f"Locked Total:      {record['locked_total']:,} shares ({record['locked_total']/record['computed_total']*100:.1f}%)" if record['computed_total'] > 0 else "Locked Total:      0 shares")
    print(f"Free Total:        {record['free_total']:,} shares ({record['free_total']/record['computed_total']*100:.1f}%)" if record['computed_total'] > 0 else "Free Total:        0 shares")
    print(f"Rows Extracted:    {len(rows)}")

    print(f"\n{'-' * 80}")
    print("SHP EXTRACTION")
    print(f"{'-' * 80}")
    print(f"Total Shares:      {record['shp_total_shares']:,}")
    print(f"Locked Shares:     {record['shp_locked_shares']:,}")
    print(f"Promoter:          {record['shp_promoter_shares']:,} shares ({record['shp_promoter_shares']/record['shp_total_shares']*100:.1f}%)" if record['shp_total_shares'] > 0 else "Promoter:          0 shares")
    print(f"Public:            {record['shp_public_shares']:,} shares ({record['shp_public_shares']/record['shp_total_shares']*100:.1f}%)" if record['shp_total_shares'] > 0 else "Public:            0 shares")
    print(f"Others:            {record['shp_others_shares']:,} shares ({record['shp_others_shares']/record['shp_total_shares']*100:.1f}%)" if record['shp_total_shares'] > 0 else "Others:            0 shares")

    print(f"\n{'-' * 80}")
    print("VALIDATION RESULTS")
    print(f"{'-' * 80}")
    print(f"All Rules Passed:  {'YES' if record['all_rules_passed'] else 'NO'}")

    if record['failed_rules']:
        print(f"Failed Rules:      {record['failed_rules']}")

    # Parse validation JSON
    if record['validation_results']:
        validations = json.loads(record['validation_results'])
        for rule_id, result in validations.items():
            status = "OK" if result['passed'] else "FAIL"
            print(f"  {status} {rule_id}: {result['message']}")

    print(f"\n{'-' * 80}")
    print("LOCK-IN DETAIL ROWS (First 10)")
    print(f"{'-' * 80}")
    print(f"{'Row':<5} {'Status':<8} {'Shares':>12} {'From':>12} {'To':>12} {'Bucket':<15} {'Lock-in Date':<12}")
    print(f"{'-' * 80}")

    for i, row in enumerate(rows[:10]):
        print(f"{i+1:<5} {row['status']:<8} {row['shares']:>12,} {row['distinctive_from']:>12,} {row['distinctive_to']:>12,} {row['bucket']:<15} {row['lockin_date_to'] or 'N/A':<12}")

    if len(rows) > 10:
        print(f"... and {len(rows) - 10} more rows")

    # Show summary by bucket
    print(f"\n{'-' * 80}")
    print("SHARES BY LOCK-IN BUCKET")
    print(f"{'-' * 80}")

    bucket_summary = {}
    for row in rows:
        bucket = row['bucket']
        bucket_summary[bucket] = bucket_summary.get(bucket, 0) + row['shares']

    for bucket, shares in sorted(bucket_summary.items(), key=lambda x: x[1], reverse=True):
        pct = shares / record['computed_total'] * 100 if record['computed_total'] > 0 else 0
        print(f"{bucket:<20} {shares:>12,} shares ({pct:>5.1f}%)")

    print(f"\n{'=' * 80}")


def list_all_processing():
    """List all processing records"""
    sql = """
        SELECT id, unique_symbol, exchange, file_name, status,
               all_rules_passed, processed_at, finalized_at
        FROM ipo_processing_log
        ORDER BY processed_at DESC
        LIMIT 20
    """

    records = db.execute_query(sql, fetch="all")

    if not records:
        print("No processing records found")
        return

    print("=" * 120)
    print("ALL PROCESSING RECORDS (Last 20)")
    print("=" * 120)
    print(f"{'ID':<5} {'Symbol':<20} {'Exchange':<10} {'Status':<12} {'Rules':<8} {'Processed':<20}")
    print("=" * 120)

    for r in records:
        rules_status = "PASS" if r['all_rules_passed'] else "FAIL"
        print(f"{r['id']:<5} {r['unique_symbol']:<20} {r['exchange']:<10} {r['status']:<12} {rules_status:<8} {str(r['processed_at']):<20}")

    print("=" * 120)
    print(f"\nTotal records: {len(records)}")


def main():
    """Main report function"""

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python report.py <unique_symbol>     # Show report for symbol")
        print("  python report.py <processing_id>     # Show report for ID")
        print("  python report.py --list              # List all records")
        print()
        print("Examples:")
        print("  python report.py BSE:544711")
        print("  python report.py 1")
        print("  python report.py --list")
        sys.exit(1)

    arg = sys.argv[1]

    # List all records
    if arg == '--list':
        list_all_processing()
        return

    # Get by ID or symbol
    if arg.isdigit():
        processing_id = int(arg)
        record = get_processing_record(processing_id=processing_id)
    else:
        unique_symbol = arg
        record = get_processing_record(unique_symbol=unique_symbol)

    if not record:
        print(f"ERROR: No processing record found for '{arg}'")
        sys.exit(1)

    # Get detail rows
    rows = get_lockin_rows(record['id'])

    # Display report
    display_report(record, rows)


if __name__ == "__main__":
    main()
