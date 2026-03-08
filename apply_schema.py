"""
Apply database schema to create required tables
Run this once before using the application
"""

import db

def apply_schema():
    """Create database tables if they don't exist"""

    print("Applying database schema...")
    print("=" * 70)

    # Read schema file
    with open('database_schema.sql', 'r') as f:
        schema_sql = f.read()

    # Split into individual statements (separated by semicolons)
    statements = [s.strip() for s in schema_sql.split(';') if s.strip() and not s.strip().startswith('--')]

    conn = db.get_db_connection()
    if not conn:
        print("ERROR: Could not connect to database")
        return False

    try:
        cursor = conn.cursor()

        for idx, statement in enumerate(statements):
            # Skip comments and empty statements
            if statement.startswith('--') or not statement.strip():
                continue

            # Skip sample query comments
            if 'SELECT' in statement and 'FROM' in statement and '--' in statement:
                continue

            try:
                cursor.execute(statement)

                # Extract table name from CREATE TABLE statement
                if 'CREATE TABLE' in statement.upper():
                    table_name = statement.split('CREATE TABLE IF NOT EXISTS')[1].split('(')[0].strip()
                    print(f"  OK Created table: {table_name}")

            except Exception as e:
                print(f"  WARN Statement {idx+1}: {str(e)[:100]}")

        conn.commit()
        cursor.close()
        conn.close()

        print("\n" + "=" * 70)
        print("SUCCESS Schema applied successfully")
        print("=" * 70)

        return True

    except Exception as e:
        print(f"ERROR: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False


if __name__ == "__main__":
    apply_schema()
