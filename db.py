"""
Database utilities for IPO Lock-in Processor v2.0
Handles connections, queries, and transactions
"""

import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv

# Find .env file
ENV_CANDIDATES = [
    Path("/home/bluenile/.env"),
    Path.home() / ".env",
    Path(__file__).parent.parent / ".env",  # ScripUnlockDetails/.env
]
ENV_PATH = next((p for p in ENV_CANDIDATES if p.exists()), ENV_CANDIDATES[0])

# Load environment
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    print(f"⚠️  Warning: .env file not found. Checked: {[str(p) for p in ENV_CANDIDATES]}")

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'ipo_lockin_db'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci',
    'autocommit': False,  # Explicit transaction control
}

# Connection pool (reuse connections for performance)
connection_pool = None


def initialize_pool():
    """Initialize connection pool (call once at startup)"""
    global connection_pool

    if connection_pool is not None:
        return

    try:
        connection_pool = pooling.MySQLConnectionPool(
            pool_name="ipo_pool",
            pool_size=5,
            pool_reset_session=True,
            **DB_CONFIG
        )
    except mysql.connector.Error as err:
        print(f"❌ Error initializing connection pool: {err}")
        connection_pool = None


def get_db_connection(max_retries: int = 3, retry_delay: float = 2.0) -> Optional[mysql.connector.MySQLConnection]:
    """
    Get database connection with retry logic

    Args:
        max_retries: Number of connection attempts
        retry_delay: Seconds to wait between retries

    Returns:
        Database connection or None on failure
    """
    global connection_pool

    # Initialize pool if not done yet
    if connection_pool is None:
        initialize_pool()

    for attempt in range(1, max_retries + 1):
        try:
            if connection_pool:
                # Get from pool
                conn = connection_pool.get_connection()
            else:
                # Direct connection (fallback if pool init failed)
                conn = mysql.connector.connect(**DB_CONFIG)

            # Test connection
            conn.ping(reconnect=True, attempts=3, delay=1)

            return conn

        except mysql.connector.Error as err:
            if attempt < max_retries:
                print(f"  ⚠️  Database connection attempt {attempt} failed: {err}")
                print(f"     Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                print(f"  ❌ Database connection failed after {max_retries} attempts: {err}")
                return None

    return None


def execute_query(sql: str, params: tuple = None, fetch: str = "all") -> Optional[List[Dict[str, Any]]]:
    """
    Execute SELECT query and return results

    Args:
        sql: SQL query string
        params: Query parameters (optional)
        fetch: "all", "one", or "none"

    Returns:
        Query results as list of dictionaries or None on error
    """
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params or ())

        if fetch == "all":
            results = cursor.fetchall()
        elif fetch == "one":
            results = cursor.fetchone()
        else:
            results = None

        cursor.close()
        conn.close()

        return results

    except mysql.connector.Error as err:
        print(f"❌ Query error: {err}")
        print(f"   SQL: {sql}")
        if conn:
            conn.close()
        return None


def execute_transaction(operations: List[tuple]) -> bool:
    """
    Execute multiple operations in a single transaction (all-or-nothing)

    Args:
        operations: List of (sql, params) tuples

    Returns:
        True if all operations succeeded, False otherwise

    Example:
        operations = [
            ("INSERT INTO table1 VALUES (%s, %s)", (1, 'value')),
            ("UPDATE table2 SET col=%s WHERE id=%s", ('new', 2)),
        ]
        success = execute_transaction(operations)
    """
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()

        # Execute all operations
        for sql, params in operations:
            cursor.execute(sql, params or ())

        # Commit transaction
        conn.commit()
        cursor.close()
        conn.close()

        return True

    except mysql.connector.Error as err:
        print(f"❌ Transaction error: {err}")
        if conn:
            conn.rollback()
            conn.close()
        return False


def test_connection() -> bool:
    """Test database connection (returns True if successful)"""
    conn = get_db_connection()
    if conn:
        conn.close()
        return True
    return False


if __name__ == "__main__":
    # Test connection when run directly
    print("Testing database connection...")
    print(f"Using .env: {ENV_PATH}")
    print(f"Host: {DB_CONFIG['host']}")
    print(f"Database: {DB_CONFIG['database']}")
    print(f"User: {DB_CONFIG['user']}")

    if test_connection():
        print("✅ Connection successful!")
    else:
        print("❌ Connection failed!")
