"""
Database Operations
Handles all database interactions for IPO processing
Reuses sme_ipo_master and sme_ipo_lockin_ocr tables
"""

import json
from datetime import date, datetime
from typing import Optional, Tuple, Dict, Any
from pathlib import Path

from models import LockinData, SHPData, ValidationResult, ProcessingStatus
import db


def get_master_data(unique_symbol: str) -> Optional[Tuple[date, int, str]]:
    """
    Get data from sme_ipo_master table

    Args:
        unique_symbol: e.g., "BSE:544324" or "NSE:AAKAAR"

    Returns:
        (allotment_date, declared_total, anchor_letter_url) or None if not found
    """
    # Parse unique_symbol
    parts = unique_symbol.split(':')
    if len(parts) != 2:
        return None

    exchange, code_or_symbol = parts

    # Query based on exchange
    if exchange == "BSE":
        # For BSE, unique_symbol uses CODE
        sql = """
            SELECT allotment_date, post_issue_shares, anchor_letter_url
            FROM sme_ipo_master
            WHERE exchange = 'BSE SME' AND bse_script_code = %s
            LIMIT 1
        """
        params = (code_or_symbol,)
    else:  # NSE
        # For NSE, unique_symbol uses SYMBOL
        sql = """
            SELECT allotment_date, post_issue_shares, anchor_letter_url
            FROM sme_ipo_master
            WHERE exchange = 'NSE SME' AND nse_symbol = %s
            LIMIT 1
        """
        params = (code_or_symbol,)

    result = db.execute_query(sql, params, fetch="one")

    if not result:
        return None

    return (
        result.get('allotment_date'),
        result.get('post_issue_shares'),
        result.get('anchor_letter_url')
    )


def save_processing_log(status: ProcessingStatus) -> Optional[int]:
    """
    Save processing log to database

    Args:
        status: ProcessingStatus object with all data

    Returns:
        processing_log_id or None on failure
    """
    # Prepare validation_results JSON
    validation_json = json.dumps({
        v.rule_id: {
            'passed': v.passed,
            'message': v.message,
            'expected': v.expected,
            'actual': v.actual,
        }
        for v in status.validations
    })

    # Get failed rules
    failed_rules = ','.join([v.rule_id for v in status.get_failed_rules()])

    # Insert into ipo_processing_log
    sql = """
        INSERT INTO ipo_processing_log (
            unique_symbol, exchange, file_name, status,
            lockin_pdf_path, shp_pdf_path,
            lockin_txt_java_path, shp_txt_java_path, lockin_png_path,
            computed_total, locked_total, free_total,
            shp_total_shares, shp_locked_shares,
            shp_promoter_shares, shp_public_shares, shp_others_shares,
            allotment_date, declared_total,
            validation_results, all_rules_passed, failed_rules,
            processed_at
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            NOW()
        )
        ON DUPLICATE KEY UPDATE
            status = VALUES(status),
            computed_total = VALUES(computed_total),
            locked_total = VALUES(locked_total),
            free_total = VALUES(free_total),
            shp_total_shares = VALUES(shp_total_shares),
            shp_locked_shares = VALUES(shp_locked_shares),
            shp_promoter_shares = VALUES(shp_promoter_shares),
            shp_public_shares = VALUES(shp_public_shares),
            shp_others_shares = VALUES(shp_others_shares),
            validation_results = VALUES(validation_results),
            all_rules_passed = VALUES(all_rules_passed),
            failed_rules = VALUES(failed_rules),
            processed_at = NOW()
    """

    params = (
        status.unique_symbol,
        status.exchange,
        status.file_name,
        'VALIDATING',  # status
        str(status.lockin_pdf) if status.lockin_pdf else None,
        str(status.shp_pdf) if status.shp_pdf else None,
        str(status.lockin_txt_java) if status.lockin_txt_java else None,
        str(status.shp_txt_java) if status.shp_txt_java else None,
        str(status.lockin_png) if status.lockin_png else None,
        status.lockin_data.computed_total if status.lockin_data else None,
        status.lockin_data.locked_total if status.lockin_data else None,
        status.lockin_data.free_total if status.lockin_data else None,
        status.shp_data.total_shares if status.shp_data else None,
        status.shp_data.locked_shares if status.shp_data else None,
        status.shp_data.promoter_shares if status.shp_data else None,
        status.shp_data.public_shares if status.shp_data else None,
        status.shp_data.others_shares if status.shp_data else None,
        status.allotment_date,
        status.declared_total,
        validation_json,
        status.all_rules_passed,
        failed_rules if failed_rules else None,
    )

    conn = db.get_db_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        processing_log_id = cursor.lastrowid

        # Save lock-in rows
        if status.lockin_data and status.lockin_data.rows:
            save_lockin_rows(conn, processing_log_id, status.lockin_data)

        conn.commit()
        cursor.close()
        conn.close()

        return processing_log_id

    except Exception as e:
        print(f"❌ Error saving processing log: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return None


def save_lockin_rows(conn, processing_log_id: int, lockin_data: LockinData):
    """
    Save lock-in rows to ipo_lockin_rows table

    Args:
        conn: Database connection (already open)
        processing_log_id: ID from ipo_processing_log
        lockin_data: LockinData with rows
    """
    # Delete existing rows for this processing_log_id (if re-processing)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ipo_lockin_rows WHERE processing_log_id = %s", (processing_log_id,))

    # Insert new rows
    sql = """
        INSERT INTO ipo_lockin_rows (
            processing_log_id, shares, distinctive_from, distinctive_to,
            security_type, lockin_date_from, lockin_date_to, share_form,
            status, bucket, row_order
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
    """

    for idx, row in enumerate(lockin_data.rows):
        params = (
            processing_log_id,
            row.shares,
            row.distinctive_from,
            row.distinctive_to,
            row.security_type,
            row.lockin_date_from,
            row.lockin_date_to,
            row.share_form,
            row.status.value,
            row.bucket.value,
            idx,  # row_order
        )
        cursor.execute(sql, params)

    cursor.close()


def update_processing_log_error(processing_log_id: int, error_message: str) -> bool:
    """Update error_message field in processing log"""
    conn = db.get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE ipo_processing_log
            SET error_message = %s
            WHERE id = %s
        """, (error_message, processing_log_id))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating processing log: {e}")
        if conn:
            conn.close()
        return False


def mark_finalized(processing_log_id: int) -> bool:
    """
    Mark processing as finalized

    Args:
        processing_log_id: ID from ipo_processing_log

    Returns:
        True if successful
    """
    sql = """
        UPDATE ipo_processing_log
        SET status = 'FINALIZED', finalized_at = NOW()
        WHERE id = %s
    """

    operations = [(sql, (processing_log_id,))]
    return db.execute_transaction(operations)


def mark_failed(unique_symbol: str, exchange: str, error_message: str) -> bool:
    """
    Mark processing as failed

    Args:
        unique_symbol: Symbol identifier
        exchange: BSE or NSE
        error_message: Error description

    Returns:
        True if successful
    """
    sql = """
        INSERT INTO ipo_processing_log (
            unique_symbol, exchange, file_name, status, error_message, processed_at
        ) VALUES (
            %s, %s, '', 'FAILED', %s, NOW()
        )
        ON DUPLICATE KEY UPDATE
            status = 'FAILED',
            error_message = VALUES(error_message),
            processed_at = NOW()
    """

    operations = [(sql, (unique_symbol, exchange, error_message))]
    return db.execute_transaction(operations)


def get_processing_status(unique_symbol: str) -> Optional[Dict[str, Any]]:
    """
    Get current processing status from database

    Args:
        unique_symbol: Symbol identifier

    Returns:
        Dictionary with processing status or None
    """
    sql = """
        SELECT *
        FROM ipo_processing_log
        WHERE unique_symbol = %s
        ORDER BY processed_at DESC
        LIMIT 1
    """

    return db.execute_query(sql, (unique_symbol,), fetch="one")


def main():
    """Test database operations"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python database.py <unique_symbol>")
        print("Example: python database.py BSE:544324")
        sys.exit(1)

    unique_symbol = sys.argv[1]

    print(f"Testing database operations for: {unique_symbol}")
    print("=" * 70)

    # Test get_master_data
    print("\n1. Getting master data...")
    master_data = get_master_data(unique_symbol)

    if master_data:
        allotment_date, declared_total, anchor_url = master_data
        print(f"   ✓ Allotment Date: {allotment_date}")
        print(f"   ✓ Declared Total: {declared_total:,}")
        print(f"   ✓ Anchor URL: {anchor_url or 'None'}")
    else:
        print(f"   ✗ No master data found for {unique_symbol}")

    # Test get_processing_status
    print("\n2. Getting processing status...")
    status = get_processing_status(unique_symbol)

    if status:
        print(f"   ✓ Status: {status.get('status')}")
        print(f"   ✓ All Rules Passed: {status.get('all_rules_passed')}")
        print(f"   ✓ Failed Rules: {status.get('failed_rules') or 'None'}")
    else:
        print(f"   ✗ No processing record found for {unique_symbol}")


if __name__ == "__main__":
    main()
