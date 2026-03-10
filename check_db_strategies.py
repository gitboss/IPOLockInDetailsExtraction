#!/usr/bin/env python3
"""Check strategy info in database"""

import db
import json

sql = """
    SELECT unique_symbol, validation_results, processed_at
    FROM ipo_processing_log
    ORDER BY processed_at DESC
    LIMIT 5
"""

results = db.execute_query(sql, fetch="all")

print("Last 5 processed records:")
print("=" * 80)

for rec in results:
    print(f"\n{rec['unique_symbol']}")
    print(f"  Processed: {rec['processed_at']}")
    
    if rec['validation_results']:
        vr = json.loads(rec['validation_results'])
        strategies = vr.get('_strategies', {})
        print(f"  Strategies: {strategies}")
        
        if not strategies:
            print(f"  ⚠️  NO _strategies field in validation_results!")
            print(f"  Keys in validation_results: {list(vr.keys())[:10]}")
    else:
        print(f"  ⚠️  validation_results is NULL")
