#!/usr/bin/env python3
import subprocess
import sys
import os
import db

PYTHON_EXE = sys.executable


def _build_subprocess_env():
    env = os.environ.copy()
    # Force UTF-8 in child Python processes to avoid cp1252 emoji crashes.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


SUBPROCESS_ENV = _build_subprocess_env()


def run_command_with_yes(cmd):
    """Run a command and send 'yes' followed by newline twice."""
    print(f"\n[{' '.join(cmd)}] Running with automatic 'yes' responses...")
    # Rollback asks for confirmation twice.
    subprocess.run(
        cmd,
        input="YES\nYES\n",
        text=True,
        check=False,
        env=SUBPROCESS_ENV
    )

def run_command(cmd):
    """Run a command normally."""
    print(f"\n[{' '.join(cmd)}] Running...")
    subprocess.run(cmd, check=False, env=SUBPROCESS_ENV)

def reset_db():
    """Reset the database tables as requested."""
    print("\n[Database] Resetting tables...")
    conn = db.get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            print("  - Deleting all records from ipo_lockin_rows")
            cursor.execute("DELETE FROM ipo_lockin_rows")
            print("  - Resetting auto increment for ipo_lockin_rows to 1")
            cursor.execute("ALTER TABLE ipo_lockin_rows AUTO_INCREMENT = 1")
            
            print("  - Deleting all records from ipo_processing_log")
            cursor.execute("DELETE FROM ipo_processing_log")
            print("  - Resetting auto increment for ipo_processing_log to 1")
            cursor.execute("ALTER TABLE ipo_processing_log AUTO_INCREMENT = 1")
            
            conn.commit()
            print("  OK Database reset complete.")
        except Exception as e:
            print(f"  ERROR resetting database: {e}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()
    else:
        print("  ERROR Failed to connect to database.")

def main():
    print("=" * 60)
    print("IPO Lock-in Testing Automation")
    print("=" * 60)

    # 1. Rollback BSE
    run_command_with_yes([PYTHON_EXE, "app.py", "--bse", "--rollback"])
    
    # 2. Rollback NSE
    run_command_with_yes([PYTHON_EXE, "app.py", "--nse", "--rollback"])
    
    # 3. Reset database
    reset_db()
    
    # 4. Processing BSE
    run_command([PYTHON_EXE, "app.py", "--bse", "--movefiles"])
    
    # 5. Processing NSE
    run_command([PYTHON_EXE, "app.py", "--nse", "--movefiles"])

    print("\n" + "=" * 60)
    print("Automation complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
