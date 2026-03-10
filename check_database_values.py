#!/usr/bin/env python3
"""Check database values for failing symbols"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import db

# First, show table schema
print("Checking sme_ipo_master table schema...")
schema_sql = "SHOW COLUMNS FROM sme_ipo_master"
schema = db.execute_query(schema_sql, fetch='all')
if schema:
    print("\nTable columns:")
    for col in schema:
        print(f"  - {col.get('Field', 'N/A')}")

# Query for failing symbols using BSE codes
sql = """
SELECT ipo_name, bse_script_code, post_issue_shares, allotment_date, listing_date_actual
FROM sme_ipo_master
WHERE bse_script_code IN ('544616', '544458', '544483')
ORDER BY bse_script_code
"""

print("\nDatabase values for GALLARD, SHREEREF, ICODEX:")
print("=" * 120)

result = db.execute_query(sql, fetch='all')
if result:
    for row in result:
        code = row.get('bse_script_code', 'N/A')
        name = row.get('ipo_name', 'N/A')
        total = row.get('post_issue_shares', 0)
        allotment = row.get('allotment_date', 'N/A')
        print(f"Code: {code:8} Name: {name:25} Declared Total: {total:>15,}  Allotment: {allotment}")
else:
    print("No records found")

print("=" * 120)
