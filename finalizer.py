"""
File Finalization Module
Moves processed files to finalized/ folders and updates database status
"""

from pathlib import Path
from typing import Optional, List, Tuple
import shutil
from database import mark_finalized


def create_finalized_folders(exchange: str, base_path: Path = Path("downloads")):
    """
    Create finalized/ subdirectories if they don't exist

    Args:
        exchange: BSE or NSE
        base_path: Base downloads folder

    Returns:
        List of created folder paths
    """
    folders = [
        base_path / exchange.lower() / "pdf" / "lockin" / "finalized",
        base_path / exchange.lower() / "pdf" / "shp" / "finalized",
        base_path / exchange.lower() / "pdf" / "lockin" / "txt" / "finalized",
        base_path / exchange.lower() / "pdf" / "shp" / "txt" / "finalized",
        base_path / exchange.lower() / "pdf" / "lockin" / "png" / "finalized",
    ]

    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)

    return folders


def move_file_to_finalized(source_file: Path) -> Optional[Path]:
    """
    Move a single file to its finalized/ folder

    Args:
        source_file: Path to file to move

    Returns:
        Destination path if successful, None otherwise
    """
    if not source_file or not source_file.exists():
        return None

    # Determine finalized folder
    finalized_dir = source_file.parent / "finalized"
    finalized_dir.mkdir(parents=True, exist_ok=True)

    # Move file
    dest = finalized_dir / source_file.name

    # If destination already exists, remove it first (reprocessing case)
    if dest.exists():
        dest.unlink()

    shutil.move(str(source_file), str(dest))

    return dest


def finalize_files(
    lockin_pdf: Optional[Path],
    shp_pdf: Optional[Path],
    lockin_txt_java: Optional[Path],
    shp_txt_java: Optional[Path],
    lockin_png: Optional[Path],
    exchange: str,
    processing_log_id: int,
    dryrun: bool = False
) -> bool:
    """
    Finalize all files for a processed IPO

    Args:
        lockin_pdf: Path to lock-in PDF
        shp_pdf: Path to SHP PDF
        lockin_txt_java: Path to lock-in TXT (java)
        shp_txt_java: Path to SHP TXT (java)
        lockin_png: Path to lock-in PNG
        exchange: BSE or NSE
        processing_log_id: ID from ipo_processing_log
        dryrun: If True, don't actually move files

    Returns:
        True if successful
    """
    if dryrun:
        print("  [DRYRUN] Would move files to finalized/ folders:")
        files_to_show = [
            ("Lock-in PDF", lockin_pdf),
            ("SHP PDF", shp_pdf),
            ("Lock-in TXT", lockin_txt_java),
            ("SHP TXT", shp_txt_java),
            ("Lock-in PNG", lockin_png),
        ]
        for label, path in files_to_show:
            if path and path.exists():
                print(f"    - {label}: {path.name}")
        print("  [DRYRUN] Would update database status to FINALIZED")
        return True

    files_to_move = [
        ("Lock-in PDF", lockin_pdf),
        ("SHP PDF", shp_pdf),
        ("Lock-in TXT", lockin_txt_java),
        ("SHP TXT", shp_txt_java),
        ("Lock-in PNG", lockin_png),
    ]

    moved_files: List[Tuple[Path, Path]] = []

    try:
        # Move all files
        for label, source_file in files_to_move:
            if source_file and source_file.exists():
                dest = move_file_to_finalized(source_file)
                if dest:
                    moved_files.append((source_file, dest))
                    print(f"  OK Moved: {source_file.name} -> finalized/")

        # Update database status
        if not mark_finalized(processing_log_id):
            raise Exception("Failed to update database status")

        print(f"  OK Database status updated to FINALIZED")

        return True

    except Exception as e:
        # Rollback file moves if database update failed
        print(f"  ERROR during finalization: {e}")
        print(f"  Rolling back file moves...")

        for source, dest in moved_files:
            if dest.exists():
                # Move back to original location
                dest_parent = source.parent
                dest_parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(source))
                print(f"  OK Restored: {source.name}")

        return False


def rollback_file_move(dest_file: Path, original_dir: Path) -> Optional[Path]:
    """
    Move a file from finalized/ back to its original location
    
    Args:
        dest_file: Path to file in finalized/ folder
        original_dir: Original directory where file should be restored
    
    Returns:
        Source path if successful, None otherwise
    """
    if not dest_file or not dest_file.exists():
        return None
    
    # Create original directory if needed
    original_dir.mkdir(parents=True, exist_ok=True)
    
    # Move file back
    source = original_dir / dest_file.name
    
    # If source already exists, remove it first
    if source.exists():
        source.unlink()
    
    shutil.move(str(dest_file), str(source))
    
    return source


def rollback_files(
    lockin_pdf: Optional[Path],
    shp_pdf: Optional[Path],
    lockin_txt_java: Optional[Path],
    shp_txt_java: Optional[Path],
    lockin_png: Optional[Path],
    exchange: str,
    processing_log_id: int,
    dryrun: bool = False,
    log_file=None
) -> Tuple[bool, list]:
    """
    Reverse of finalize_files() - move files from finalized/ back to original locations
    
    Args:
        lockin_pdf: Path to lock-in PDF in finalized/
        shp_pdf: Path to SHP PDF in finalized/
        lockin_txt_java: Path to lock-in TXT in finalized/
        shp_txt_java: Path to SHP TXT in finalized/
        lockin_png: Path to lock-in PNG in finalized/
        exchange: BSE or NSE
        processing_log_id: ID from ipo_processing_log
        dryrun: If True, don't actually move files
        log_file: Optional file object for logging
    
    Returns:
        (success, list of restored files)
    """
    def log(msg):
        """Helper to print and log"""
        print(msg)
        if log_file:
            log_file.write(msg + '\n')
    
    if dryrun:
        log("  [DRYRUN] Would restore files from finalized/ folders:")
        files_to_show = [
            ("Lock-in PDF", lockin_pdf),
            ("SHP PDF", shp_pdf),
            ("Lock-in TXT", lockin_txt_java),
            ("SHP TXT", shp_txt_java),
            ("Lock-in PNG", lockin_png),
        ]
        for label, path in files_to_show:
            if path and path.exists():
                log(f"    - {label}: {path.name}")
        log("  [DRYRUN] Would update database status to VALIDATING")
        return True, []
    
    # Define original directories
    base = Path("downloads") / exchange.lower()
    original_dirs = {
        lockin_pdf: base / "pdf" / "lockin",
        shp_pdf: base / "pdf" / "shp",
        lockin_txt_java: base / "pdf" / "lockin" / "txt",
        shp_txt_java: base / "pdf" / "shp" / "txt",
        lockin_png: base / "pdf" / "lockin" / "png",
    }
    
    files_to_restore = [
        ("Lock-in PDF", lockin_pdf),
        ("SHP PDF", shp_pdf),
        ("Lock-in TXT", lockin_txt_java),
        ("SHP TXT", shp_txt_java),
        ("Lock-in PNG", lockin_png),
    ]
    
    restored_files: List[Path] = []
    
    try:
        # Restore all files
        for label, dest_file in files_to_restore:
            if dest_file and dest_file.exists():
                original_dir = original_dirs.get(dest_file)
                if original_dir:
                    source = rollback_file_move(dest_file, original_dir)
                    if source:
                        restored_files.append(source)
                        log(f"  ✓ Restored: {source.name}")
                    else:
                        log(f"  ✗ Failed to restore: {label}")
                else:
                    log(f"  ✗ Unknown original directory for: {label}")
            else:
                log(f"  ⊗ Not in finalized/: {label} (may not have been finalized)")
        
        # Update database status
        from database import mark_unfinalized
        if not mark_unfinalized(processing_log_id):
            raise Exception("Failed to update database status")
        
        log(f"  ✓ Database updated: FINALIZED → VALIDATING")
        
        return True, restored_files
        
    except Exception as e:
        # Log error but don't rollback (user can re-run rollback)
        log(f"  ✗ ERROR during rollback: {e}")
        log(f"  ⚠ Some files may have been restored. Re-run rollback to continue.")
        return False, restored_files


def check_can_rollback(status: str) -> Tuple[bool, str]:
    """
    Check if file can be rollbacked
    
    Args:
        status: Current processing status
    
    Returns:
        (can_rollback, reason)
    """
    if status != 'FINALIZED':
        return False, f"Cannot rollback: status is '{status}' (must be FINALIZED)"
    
    return True, "Ready for rollback"


def check_can_finalize(all_rules_passed: bool, status: str) -> Tuple[bool, str]:
    """
    Check if file can be finalized

    Args:
        all_rules_passed: Whether all validation rules passed
        status: Current processing status

    Returns:
        (can_finalize, reason)
    """
    if status == 'FINALIZED':
        return False, "Already finalized"

    if status == 'FAILED':
        return False, "Processing failed"

    if not all_rules_passed:
        return False, "Not all validation rules passed"

    if status != 'VALIDATING':
        return False, f"Invalid status: {status} (expected VALIDATING)"

    return True, "Ready for finalization"


def main():
    """Test finalizer with a processing log ID"""
    import sys
    from database import get_processing_status
    import db

    if len(sys.argv) < 2:
        print("Usage: python finalizer.py <processing_log_id> [--dryrun]")
        print("Example: python finalizer.py 42")
        print("Example: python finalizer.py 42 --dryrun")
        sys.exit(1)

    processing_log_id = int(sys.argv[1])
    dryrun = '--dryrun' in sys.argv

    print(f"Finalizing processing_log_id: {processing_log_id}")
    print("=" * 70)

    # Get processing status from database
    sql = "SELECT * FROM ipo_processing_log WHERE id = %s"
    result = db.execute_query(sql, (processing_log_id,), fetch="one")

    if not result:
        print(f"ERROR: No processing record found for ID {processing_log_id}")
        sys.exit(1)

    # Check if can finalize
    can_finalize, reason = check_can_finalize(
        result.get('all_rules_passed', False),
        result.get('status', '')
    )

    print(f"\nPre-checks:")
    print(f"  Symbol: {result.get('unique_symbol')}")
    print(f"  Exchange: {result.get('exchange')}")
    print(f"  Status: {result.get('status')}")
    print(f"  All Rules Passed: {result.get('all_rules_passed')}")

    if not can_finalize:
        print(f"\n  ERROR Cannot finalize: {reason}")
        sys.exit(1)

    print(f"  OK {reason}")

    # Get file paths
    lockin_pdf = Path(result['lockin_pdf_path']) if result.get('lockin_pdf_path') else None
    shp_pdf = Path(result['shp_pdf_path']) if result.get('shp_pdf_path') else None
    lockin_txt = Path(result['lockin_txt_java_path']) if result.get('lockin_txt_java_path') else None
    shp_txt = Path(result['shp_txt_java_path']) if result.get('shp_txt_java_path') else None
    lockin_png = Path(result['lockin_png_path']) if result.get('lockin_png_path') else None

    print(f"\nMoving files:")

    # Finalize
    success = finalize_files(
        lockin_pdf=lockin_pdf,
        shp_pdf=shp_pdf,
        lockin_txt_java=lockin_txt,
        shp_txt_java=shp_txt,
        lockin_png=lockin_png,
        exchange=result['exchange'],
        processing_log_id=processing_log_id,
        dryrun=dryrun
    )

    if success:
        print(f"\n{'=' * 70}")
        print(f"SUCCESS FINALIZATION COMPLETE")
        print(f"{'=' * 70}")
        print(f"\n  Symbol: {result.get('unique_symbol')}")
        print(f"  Files moved to: finalized/")
        print(f"  Database ID: {processing_log_id}")
        sys.exit(0)
    else:
        print(f"\n{'=' * 70}")
        print(f"FAIL FINALIZATION FAILED")
        print(f"{'=' * 70}")
        sys.exit(1)


if __name__ == "__main__":
    main()
